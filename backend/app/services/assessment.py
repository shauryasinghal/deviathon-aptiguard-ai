"""Candidate assessment delivery. The answer key never leaves the server before (or after) submission."""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import Conflict, Forbidden, NotFound, Unprocessable
from app.db.base import utcnow
from app.models import AnswerOption, AssemblyRun, Attempt, Candidate, FormItem, Question, Response, TestForm
from app.services import audit
from app.services.exposure.service import record_administration

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


def start_attempt(db: Session, candidate: Candidate, form: TestForm) -> dict:
    if form.status != "published":
        raise Conflict("This form is not open for candidates")
    existing = db.scalar(select(Attempt).where(Attempt.candidate_id == candidate.id, Attempt.form_id == form.id))
    if existing:
        if existing.status == "in_progress" and existing.deadline_at < utcnow() - timedelta(seconds=GRACE_SECONDS):
            _finalize(db, existing, auto=True)
        return _attempt_view(db, existing)
    now = utcnow()
    a = Attempt(candidate_id=candidate.id, form_id=form.id, slot_id=form.slot_id, status="in_progress", started_at=now,
                deadline_at=now + timedelta(minutes=form.duration_minutes), is_synthetic=candidate.is_synthetic)
    db.add(a)
    db.flush()
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
        _finalize(db, a, auto=True)
    return _attempt_view(db, a)


def save_answers(db: Session, attempt_id: int, candidate: Candidate, answers: list[dict]) -> dict:
    a = _load_attempt(db, attempt_id, candidate)
    if a.status != "in_progress":
        raise Conflict("Attempt already submitted")
    if a.deadline_at < utcnow() - timedelta(seconds=GRACE_SECONDS):
        _finalize(db, a, auto=True)
        raise Conflict("Time is over; the attempt was submitted automatically")
    items = {fi.id: fi for fi in db.scalars(select(FormItem).where(FormItem.form_id == a.form_id)).all()}
    for ans in answers:
        fi = items.get(int(ans["item_ref"]))
        if fi is None:
            raise Unprocessable(f"Item {ans['item_ref']} is not part of this assessment")
        key = ans.get("selected_key")
        if key is not None and key not in ("A", "B", "C", "D"):
            raise Unprocessable(f"Invalid option '{key}'")
        r = db.scalar(select(Response).where(Response.attempt_id == a.id, Response.question_id == fi.question_id))
        t = ans.get("time_spent_ms")
        t = max(0, min(int(t), 3_600_000)) if t is not None else None
        if r:
            r.selected_key = key
            r.answered_at = utcnow()
            if t is not None:
                r.response_time_ms = (r.response_time_ms or 0) + t
        else:
            db.add(Response(attempt_id=a.id, question_id=fi.question_id, selected_key=key, response_time_ms=t))
    db.flush()
    return _attempt_view(db, a)


def _finalize(db: Session, a: Attempt, auto: bool = False) -> None:
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
    audit.record(db, None, "assessment.attempt_submitted", "attempt", a.id,
                 f"Attempt #{a.id} {'auto-' if auto else ''}submitted", org_id=form.slot.org_id)


def submit(db: Session, attempt_id: int, candidate: Candidate) -> dict:
    a = _load_attempt(db, attempt_id, candidate)
    if a.status == "submitted":
        raise Conflict("Attempt already submitted", {"attempt_id": a.id})
    _finalize(db, a)
    db.flush()
    return _attempt_view(db, a)
