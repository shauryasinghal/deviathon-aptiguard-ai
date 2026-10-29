"""Exposure tracking and explainable exposure-risk scoring."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import Conflict
from app.db.base import utcnow
from app.models import Attempt, ExposureEvent, Question, Response, Slot, User
from app.services import audit
from app.services.policies import get_policy


@dataclass
class ExposureStats:
    question_id: int
    slot_count: int = 0
    candidate_exposures: int = 0
    response_count: int = 0
    last_used_at: datetime | None = None
    slots: list[str] = field(default_factory=list)


def exposure_stats(db: Session, org_id: int, question_ids: list[int] | None = None) -> dict[int, ExposureStats]:
    q = (select(ExposureEvent.question_id, func.count(func.distinct(ExposureEvent.slot_id)),
                func.coalesce(func.sum(ExposureEvent.candidate_count), 0), func.max(ExposureEvent.occurred_at))
         .join(Question, Question.id == ExposureEvent.question_id).where(Question.org_id == org_id)
         .group_by(ExposureEvent.question_id))
    if question_ids is not None:
        q = q.where(ExposureEvent.question_id.in_(question_ids))
    out = {qid: ExposureStats(qid, int(n), int(c), 0, last) for qid, n, c, last in db.execute(q).all()}
    slot_rows = db.execute(
        select(ExposureEvent.question_id, Slot.code).join(Slot, Slot.id == ExposureEvent.slot_id)
        .where(ExposureEvent.question_id.in_(list(out))).distinct()
    ).all()
    for qid, code in slot_rows:
        out[qid].slots.append(code)
    resp = db.execute(select(Response.question_id, func.count()).join(Attempt, Attempt.id == Response.attempt_id)
                      .where(Response.question_id.in_(list(out))).group_by(Response.question_id)).all()
    for qid, n in resp:
        out[qid].response_count = int(n)
    for s in out.values():
        s.slots.sort()
    return out


def risk_score(stats: ExposureStats | None, q: Question, pol: dict, family_leak: bool = False,
               now: datetime | None = None) -> dict:
    """0–100 score with additive, explained components."""
    now = now or utcnow()
    s = stats or ExposureStats(q.id)
    comps = []
    usage = min(1.0, s.slot_count / max(pol["max_slot_exposures"], 1))
    comps.append({"factor": "slot_usage", "points": round(40 * usage, 1),
                  "detail": f"Used in {s.slot_count} slot(s); limit {pol['max_slot_exposures']}"})
    aud = min(1.0, s.candidate_exposures / max(pol["max_candidate_exposures"], 1))
    comps.append({"factor": "audience", "points": round(25 * aud, 1),
                  "detail": f"Seen by {s.candidate_exposures} candidates; limit {pol['max_candidate_exposures']}"})
    days = None
    if s.last_used_at:
        days = (now - s.last_used_at).total_seconds() / 86400
        rec = max(0.0, 1 - days / 30)
        comps.append({"factor": "recency", "points": round(15 * rec, 1), "detail": f"Last used {days:.0f} day(s) ago"})
    leak_pts = {"suspected": 20, "confirmed": 35}.get(q.leak_status, 0)
    if leak_pts:
        comps.append({"factor": "leak_status", "points": leak_pts, "detail": f"Leak status: {q.leak_status}"})
    if family_leak and not leak_pts:
        comps.append({"factor": "family_leak", "points": 10, "detail": "A sibling variant is suspected/confirmed leaked"})
    score = min(100.0, round(sum(c["points"] for c in comps), 1))
    over = s.slot_count >= pol["max_slot_exposures"] or s.candidate_exposures >= pol["max_candidate_exposures"]
    level = "high" if (score >= 60 or over or q.leak_status == "confirmed") else ("elevated" if score >= 30 else "low")
    warn = s.slot_count >= pol["warn_ratio"] * pol["max_slot_exposures"] or \
        s.candidate_exposures >= pol["warn_ratio"] * pol["max_candidate_exposures"]
    return {"score": score, "level": level, "over_limit": over, "warning": warn or over, "components": comps,
            "days_since_last_use": None if days is None else round(days, 1)}


def leaked_families(db: Session, org_id: int) -> set[int]:
    return set(db.scalars(select(Question.family_id).where(
        Question.org_id == org_id, Question.leak_status.in_(("suspected", "confirmed")))).all())


def eligibility(q: Question, s: ExposureStats | None, pol: dict) -> tuple[bool, str | None]:
    if q.status != "approved":
        return False, f"status '{q.status}'"
    if q.leak_status in pol["exclude_leak_statuses"]:
        return False, f"leak status '{q.leak_status}'"
    if s and s.slot_count >= pol["max_slot_exposures"]:
        return False, "slot exposure limit reached"
    if s and s.candidate_exposures >= pol["max_candidate_exposures"]:
        return False, "candidate exposure limit reached"
    return True, None


def set_item_state(db: Session, q: Question, target: str, user: User, reason: str) -> Question:
    allowed = {
        "quarantined": {"approved", "pending_review"},
        "retired": {"approved", "quarantined"},
        "approved": {"quarantined"},  # release from quarantine back to the pool
    }
    if target not in allowed:
        raise Conflict(f"Unsupported target state '{target}'")
    if q.status not in allowed[target]:
        raise Conflict(f"Cannot move {q.code} from '{q.status}' to '{target}'")
    if target == "approved" and q.leak_status == "confirmed":
        raise Conflict("Item has a confirmed leak and cannot be released back into the pool")
    if not reason or len(reason.strip()) < 5:
        raise Conflict("A reason (≥5 characters) is required")
    prev = q.status
    q.status, q.status_reason = target, reason
    q.version += 1
    from app.services.questions import add_revision

    add_revision(db, q, "status_change", user, f"{prev} → {target}: {reason}")
    audit.record(db, user, f"exposure.{target}", "question", q.code, f"{q.code}: {prev} → {target} ({reason})")
    from app.services.assembly.service import flag_forms_for_item, restore_forms_if_clean

    db.flush()
    if target in ("quarantined", "retired"):
        flag_forms_for_item(db, q.id, f"{q.code} {target}: {reason}", user)
    else:
        restore_forms_if_clean(db, q.id, user)
    return q


def record_administration(db: Session, form, slot_id: int, n_candidates: int = 1, when: datetime | None = None) -> None:
    """One exposure row per (form, item); candidate counts accumulate atomically.

    Uses INSERT ... ON CONFLICT DO UPDATE (PostgreSQL and SQLite) so simultaneous starts by different candidates
    neither collide on the unique key nor lose increments (a read-modify-write would do both)."""
    when = when or utcnow()
    dialect = db.get_bind().dialect.name
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as dialect_insert
    else:
        from sqlalchemy.dialects.sqlite import insert as dialect_insert
    for fi in form.items:
        stmt = dialect_insert(ExposureEvent).values(question_id=fi.question_id, slot_id=slot_id, form_id=form.id,
                                                    event_type="administered", candidate_count=n_candidates, occurred_at=when)
        stmt = stmt.on_conflict_do_update(
            index_elements=["form_id", "question_id", "event_type"],
            set_={"candidate_count": ExposureEvent.candidate_count + stmt.excluded.candidate_count,
                  "occurred_at": func.max(ExposureEvent.occurred_at, stmt.excluded.occurred_at)
                  if dialect == "sqlite" else func.greatest(ExposureEvent.occurred_at, stmt.excluded.occurred_at)},
        )
        db.execute(stmt)


def policy(db: Session, org_id: int) -> dict:
    return get_policy(db, org_id, "exposure")
