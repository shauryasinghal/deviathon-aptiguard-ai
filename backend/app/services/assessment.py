"""Candidate assessment delivery. The answer key never leaves the server before (or after) submission."""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import Conflict, Forbidden, NotFound, Unprocessable
from app.db.base import utcnow
from app.models import AnswerOption, AssemblyRun, Attempt, Candidate, CandidateAssignment, FormItem, Question, Response, TestForm
from app.services import audit
from app.services.exposure.service import record_administration
from app.services.policies import get_policy

GRACE_SECONDS = 30


def candidate_safe_form(db: Session, form: TestForm) -> dict:
    items = []
    for fi in form.items:
        q = db.get(Question, fi.question_id)
        items.append({
            "item_ref": fi.id, "position": fi.position, "section": q.section.code, "section_name": q.section.name,
            "stem": q.stem, "options": [{"key": o.key, "text": o.text} for o in q.options],
        })
    return {"form_id": form.id, "form_code": form.code, "slot": form.slot.name, "slot_starts_at": form.slot.starts_at,
            "duration_minutes": form.duration_minutes, "n_items": len(items), "items": items,
            "instructions": [
                "Each question has exactly one correct answer. There is no negative marking.",
                "Your answers are saved automatically; you can resume from another device until time runs out.",
                "The timer is enforced on the server. Unanswered questions score zero.",
                "Do not copy, photograph or share questions. Sharing content is a breach of the assessment terms.",
            ]}


def _attempt_view(db: Session, a: Attempt, include_answers: bool = True) -> dict:
    now = utcnow()
    remaining = max(0, int((a.deadline_at - now).total_seconds())) if a.status == "in_progress" else 0
    out = {"attempt_id": a.id, "form_id": a.form_id, "status": a.status, "started_at": a.started_at,
           "deadline_at": a.deadline_at, "submitted_at": a.submitted_at, "remaining_seconds": remaining}
    if include_answers:
        rs = db.scalars(select(Response).where(Response.attempt_id == a.id)).all()
        refs = {fi.question_id: fi.id for fi in db.scalars(select(FormItem).where(FormItem.form_id == a.form_id)).all()}
        out["answers"] = {str(refs[r.question_id]): r.selected_key for r in rs if r.question_id in refs}
    if a.status == "submitted":
        out["result"] = {"score": a.score, "max_score": a.max_score, "section_scores": a.section_scores}
    return out


def get_candidate(db: Session, user_id: int) -> Candidate:
    c = db.scalar(select(Candidate).where(Candidate.user_id == user_id))
    if not c:
        raise Forbidden("No candidate profile linked to this account")
    return c


def is_assigned(db: Session, candidate: Candidate, form: TestForm) -> bool:
    return db.scalar(select(CandidateAssignment.id).where(CandidateAssignment.candidate_id == candidate.id,
                                                          CandidateAssignment.form_id == form.id)) is not None


def require_access(db: Session, candidate: Candidate, form: TestForm | None) -> TestForm:
    """A candidate may only see forms assigned to them. Unassigned forms are reported as not found (no enumeration)."""
    if form is None or form.slot.org_id != candidate.org_id or not is_assigned(db, candidate, form):
        raise NotFound("Assessment not available")
    return form


def window_state(db: Session, form: TestForm) -> dict:
    pol = get_policy(db, form.slot.org_id, "assessment")
    opens = form.slot.starts_at - timedelta(minutes=pol["early_entry_minutes"])
    closes = form.slot.starts_at + timedelta(minutes=pol["late_entry_minutes"])
    now = utcnow()
    state = "open" if opens <= now <= closes else ("not_yet_open" if now < opens else "closed")
    return {"enforced": pol["enforce_slot_window"], "opens_at": opens, "closes_at": closes,
            "state": state if pol["enforce_slot_window"] else "open"}


def start_attempt(db: Session, candidate: Candidate, form: TestForm) -> dict:
    require_access(db, candidate, form)
    existing = db.scalar(select(Attempt).where(Attempt.candidate_id == candidate.id, Attempt.form_id == form.id))
    if existing:  # resume (also after the window closes) — never a second attempt
        if existing.status == "in_progress" and existing.deadline_at < utcnow() - timedelta(seconds=GRACE_SECONDS):
            _auto_finalize(db, existing)
        return _attempt_view(db, existing)
    if form.status != "published":
        raise Conflict("This assessment is not open for candidates" + (
            " (it is being re-checked after an item was withdrawn)" if form.status == "needs_review" else ""))
    w = window_state(db, form)
    if w["state"] != "open":
        raise Conflict("This assessment can only be started inside its slot window",
                       {"opens_at": w["opens_at"].isoformat(), "closes_at": w["closes_at"].isoformat(), "state": w["state"]})
    now = utcnow()
    a = Attempt(candidate_id=candidate.id, form_id=form.id, slot_id=form.slot_id, status="in_progress", started_at=now,
                deadline_at=now + timedelta(minutes=form.duration_minutes), is_synthetic=candidate.is_synthetic)
    db.add(a)
    try:
        with db.begin_nested():
            db.flush()
    except IntegrityError:  # concurrent start by the same candidate: return the attempt that won
        existing = db.scalar(select(Attempt).where(Attempt.candidate_id == candidate.id, Attempt.form_id == form.id))
        return _attempt_view(db, existing)
    record_administration(db, form, form.slot_id, 1, now)
    audit.record(db, None, "assessment.attempt_started", "attempt", a.id,
                 f"Candidate {candidate.code} started {form.code}", org_id=candidate.org_id)
    return _attempt_view(db, a)


def _load_attempt(db: Session, attempt_id: int, candidate: Candidate) -> Attempt:
    a = db.get(Attempt, attempt_id)
    if not a or a.candidate_id != candidate.id:
        raise NotFound("Attempt not found")  # do not reveal other candidates' attempts
    return a


def attempt_state(db: Session, attempt_id: int, candidate: Candidate) -> dict:
    a = _load_attempt(db, attempt_id, candidate)
    if a.status == "in_progress" and a.deadline_at < utcnow() - timedelta(seconds=GRACE_SECONDS):
        _auto_finalize(db, a)
    return _attempt_view(db, a)


def save_answers(db: Session, attempt_id: int, candidate: Candidate, answers: list[dict]) -> dict:
    a = _load_attempt(db, attempt_id, candidate)
    if a.status != "in_progress":
        raise Conflict("Attempt already submitted")
    if a.deadline_at < utcnow() - timedelta(seconds=GRACE_SECONDS):
        _auto_finalize(db, a)
        raise Conflict("Time is over; the attempt was submitted automatically")
    # Claim the row before writing: a no-op UPDATE guarded on status takes the write/row lock, so a concurrent submit
    # cannot score the attempt between our status check and our writes (no responses land on a scored attempt).
    live = db.execute(update(Attempt).where(Attempt.id == a.id, Attempt.status == "in_progress")
                      .values(status="in_progress").execution_options(synchronize_session=False)).rowcount
    if live != 1:
        db.refresh(a)
        raise Conflict("Attempt already submitted")
    items = {fi.id: fi for fi in db.scalars(select(FormItem).where(FormItem.form_id == a.form_id)).all()}
    # validate the whole batch before writing anything (no partial saves)
    clean = []
    for ans in answers:
        fi = items.get(int(ans["item_ref"]))
        if fi is None:
            raise Unprocessable(f"Item {ans['item_ref']} is not part of this assessment")
        key = ans.get("selected_key")
        if key is not None and key not in ("A", "B", "C", "D"):
            raise Unprocessable(f"Invalid option '{key}'")
        t = ans.get("time_spent_ms")
        clean.append((fi, key, max(0, min(int(t), 3_600_000)) if t is not None else None))
    for fi, key, t in clean:
        r = db.scalar(select(Response).where(Response.attempt_id == a.id, Response.question_id == fi.question_id))
        if r:
            r.selected_key = key
            r.answered_at = utcnow()
            if t is not None:
                r.response_time_ms = (r.response_time_ms or 0) + t
        else:
            db.add(Response(attempt_id=a.id, question_id=fi.question_id, selected_key=key, response_time_ms=t))
    db.flush()
    return _attempt_view(db, a)


def _auto_finalize(db: Session, a: Attempt) -> None:
    """Server-side expiry: finalize once; a concurrent finalization by another request is fine."""
    try:
        _finalize(db, a, auto=True)
    except Conflict:
        db.refresh(a)


def _finalize(db: Session, a: Attempt, auto: bool = False) -> None:
    # Claim the attempt atomically: only one request can move it out of in_progress (idempotent, race-safe).
    claimed = db.execute(update(Attempt).where(Attempt.id == a.id, Attempt.status == "in_progress")
                         .values(status="scoring").execution_options(synchronize_session=False)).rowcount
    if claimed != 1:
        db.refresh(a)
        raise Conflict("Attempt already submitted", {"attempt_id": a.id})
    db.refresh(a)
    form = db.get(TestForm, a.form_id)
    weights = {}
    if form.assembly_run_id:
        run = db.get(AssemblyRun, form.assembly_run_id)
        weights = (run.config or {}).get("section_weights", {}) if run else {}
    responses = {r.question_id: r for r in db.scalars(select(Response).where(Response.attempt_id == a.id)).all()}
    correct_keys = dict(db.execute(
        select(AnswerOption.question_id, AnswerOption.key).where(
            AnswerOption.question_id.in_([fi.question_id for fi in form.items]), AnswerOption.is_correct.is_(True))
    ).all())
    score = max_score = 0.0
    sections: dict[str, dict] = {}
    for fi in form.items:
        q = db.get(Question, fi.question_id)
        w = float(weights.get(q.section.code, 1.0))
        r = responses.get(fi.question_id)
        if r is None:
            r = Response(attempt_id=a.id, question_id=fi.question_id, selected_key=None)
            db.add(r)
        r.is_correct = r.selected_key is not None and r.selected_key == correct_keys.get(fi.question_id)
        s = sections.setdefault(q.section.code, {"score": 0.0, "max": 0.0, "answered": 0, "n": 0})
        s["n"] += 1
        s["max"] += w
        max_score += w
        if r.selected_key is not None:
            s["answered"] += 1
        if r.is_correct:
            s["score"] += w
            score += w
    a.status, a.submitted_at = "submitted", utcnow()
    a.score, a.max_score, a.section_scores = score, max_score, sections
    if a.review_flags and a.review_flags.get("items"):
        db.flush()
        a.review_flags = {**a.review_flags, **_alternative_score(db, a, {i["question_id"] for i in a.review_flags["items"]})}
    audit.record(db, None, "assessment.attempt_submitted", "attempt", a.id,
                 f"Attempt #{a.id} {'auto-' if auto else ''}submitted", org_id=form.slot.org_id)


def submit(db: Session, attempt_id: int, candidate: Candidate) -> dict:
    a = _load_attempt(db, attempt_id, candidate)
    if a.status != "in_progress":
        raise Conflict("Attempt already submitted", {"attempt_id": a.id})
    _finalize(db, a)
    db.flush()
    return _attempt_view(db, a)


# ------------------------------------------------------------------ item withdrawn while attempts exist
# Policy (auditable, never silent): a candidate's attempt is NOT invalidated or interrupted when one of its items is
# quarantined, retired or leak-confirmed. The live attempt continues and is scored normally (official score). The
# attempt receives a staff-only review flag listing the withdrawn item(s), plus an alternative score that excludes them,
# so a human can decide later. Flags survive item release (annotated, not deleted). Historical forms are excluded.
def _alternative_score(db: Session, a: Attempt, excluded: set[int]) -> dict:
    form = db.get(TestForm, a.form_id)
    weights = {}
    if form.assembly_run_id:
        run = db.get(AssemblyRun, form.assembly_run_id)
        weights = (run.config or {}).get("section_weights", {}) if run else {}
    resp = {r.question_id: r for r in db.scalars(select(Response).where(Response.attempt_id == a.id)).all()}
    score = max_score = 0.0
    for fi in form.items:
        if fi.question_id in excluded:
            continue
        w = float(weights.get(db.get(Question, fi.question_id).section.code, 1.0))
        max_score += w
        if resp.get(fi.question_id) is not None and resp[fi.question_id].is_correct:
            score += w
    return {"score_excluding_flagged": score, "max_excluding_flagged": max_score}


def flag_attempts_for_item(db: Session, question_id: int, reason: str, user=None) -> list[int]:
    q = db.get(Question, question_id)
    attempts = db.scalars(select(Attempt).join(FormItem, FormItem.form_id == Attempt.form_id)
                          .join(TestForm, TestForm.id == Attempt.form_id)
                          .where(FormItem.question_id == question_id, TestForm.status != "historical")).all()
    flagged = []
    for a in attempts:
        flags = dict(a.review_flags or {"items": [], "decision": "pending", "policy": "attempt continues; official score unchanged"})
        if any(i["question_id"] == question_id for i in flags["items"]):
            continue
        flags["items"] = [*flags["items"], {"question_id": question_id, "code": q.code, "reason": reason[:300],
                                            "flagged_at": utcnow().isoformat(), "attempt_status_when_flagged": a.status}]
        if a.status == "submitted":
            flags.update(_alternative_score(db, a, {i["question_id"] for i in flags["items"]}))
        a.review_flags = flags
        flagged.append(a.id)
    if flagged:
        audit.record(db, user, "assessment.attempts_flagged", "question", q.code,
                     f"{len(flagged)} attempt(s) flagged for review after {q.code} was withdrawn (not invalidated)",
                     {"attempt_ids": flagged[:200], "reason": reason[:300]}, org_id=q.org_id)
    return flagged


def note_item_released(db: Session, question_id: int, user=None) -> None:
    attempts = db.scalars(select(Attempt).where(Attempt.review_flags.is_not(None))).all()
    for a in attempts:
        items = (a.review_flags or {}).get("items", [])
        if any(i["question_id"] == question_id and "released_at" not in i for i in items):
            a.review_flags = {**a.review_flags, "items": [{**i, "released_at": utcnow().isoformat()} if i["question_id"] == question_id else i
                                                          for i in items]}
