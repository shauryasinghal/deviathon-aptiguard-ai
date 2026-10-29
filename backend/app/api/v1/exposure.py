from __future__ import annotations

from collections import defaultdict
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.v1.serializers import question_summary
from app.core.deps import require
from app.core.errors import NotFound, Unprocessable
from app.db.session import get_db
from app.models import ExposureEvent, Question, Section, Slot, TestForm, User
from app.services import audit
from app.services.exposure.service import exposure_stats, leaked_families, risk_score, set_item_state
from app.services.policies import get_policy, set_policy

router = APIRouter(prefix="/exposure", tags=["exposure"])


class StateIn(BaseModel):
    reason: str = Field(min_length=5, max_length=300)


class PolicyIn(BaseModel):
    max_slot_exposures: int | None = Field(default=None, ge=1, le=100)
    max_candidate_exposures: int | None = Field(default=None, ge=1, le=1_000_000)
    min_slot_spacing: int | None = Field(default=None, ge=0, le=20)
    warn_ratio: float | None = Field(default=None, gt=0, le=1)
    exclude_leak_statuses: list[Literal["suspected", "confirmed"]] | None = None


@router.get("/items")
def items(section: str | None = None, level: str | None = None, status: str | None = None, q: str | None = None,
          sort: Literal["risk", "slots", "candidates", "recent"] = "risk", page: int = Query(1, ge=1),
          page_size: int = Query(25, ge=1, le=200), user: User = Depends(require("exposure.read")), db: Session = Depends(get_db)):
    pol = get_policy(db, user.org_id, "exposure")
    stmt = select(Question).where(Question.org_id == user.org_id, Question.status.in_(
        (status.split(",") if status else ["approved", "quarantined", "retired", "pending_review"])))
    if section:
        stmt = stmt.join(Section, Section.id == Question.section_id).where(Section.code == section)
    if q:
        stmt = stmt.where(Question.code.ilike(f"%{q}%"))
    qs = db.scalars(stmt).all()
    stats = exposure_stats(db, user.org_id)
    fams = leaked_families(db, user.org_id)
    rows = []
    for x in qs:
        r = risk_score(stats.get(x.id), x, pol, x.family_id in fams)
        if level and r["level"] != level:
            continue
        rows.append((x, stats.get(x.id), r))
    key = {"risk": lambda t: -t[2]["score"], "slots": lambda t: -(t[1].slot_count if t[1] else 0),
           "candidates": lambda t: -(t[1].candidate_exposures if t[1] else 0),
           "recent": lambda t: -(t[1].last_used_at.timestamp() if t[1] and t[1].last_used_at else 0)}[sort]
    rows.sort(key=key)
    levels = defaultdict(int)
    for _, _, r in rows:
        levels[r["level"]] += 1
    page_rows = rows[(page - 1) * page_size: page * page_size]
    out = []
    for x, s, r in page_rows:
        d = question_summary(x, s, r)
        d["slots"] = s.slots if s else []
        d["response_count"] = s.response_count if s else 0
        out.append(d)
    return {"items": out, "total": len(rows), "page": page, "page_size": page_size, "levels": dict(levels), "policy": pol}


@router.get("/timeline")
def timeline(drive: str | None = None, user: User = Depends(require("exposure.read")), db: Session = Depends(get_db)):
    stmt = (select(Slot.id, Slot.code, Slot.name, Slot.drive, Slot.sequence, Slot.starts_at,
                   func.count(func.distinct(ExposureEvent.question_id)), func.coalesce(func.sum(ExposureEvent.candidate_count), 0))
            .join(ExposureEvent, ExposureEvent.slot_id == Slot.id, isouter=True).where(Slot.org_id == user.org_id)
            .group_by(Slot.id).order_by(Slot.starts_at))
    if drive:
        stmt = stmt.where(Slot.drive == drive)
    rows = db.execute(stmt).all()
    # items first exposed in each slot (new) vs re-used
    first_seen = dict(db.execute(select(ExposureEvent.question_id, func.min(ExposureEvent.occurred_at))
                                 .group_by(ExposureEvent.question_id)).all())
    out = []
    for sid, code, name, drv, seq, starts, n_items, n_exp in rows:
        evs = db.execute(select(ExposureEvent.question_id, ExposureEvent.occurred_at).where(ExposureEvent.slot_id == sid)).all()
        new = sum(1 for qid, t in evs if first_seen.get(qid) == t)
        forms = db.scalar(select(func.count()).select_from(TestForm).where(TestForm.slot_id == sid))
        out.append({"slot_id": sid, "slot_code": code, "name": name, "drive": drv, "sequence": seq, "starts_at": starts,
                    "items_exposed": n_items, "candidate_item_exposures": int(n_exp), "new_items": new,
                    "reused_items": n_items - new, "forms": forms})
    return {"slots": out, "drives": sorted({r["drive"] for r in out})}


@router.get("/policy")
def get_pol(user: User = Depends(require("exposure.read")), db: Session = Depends(get_db)):
    return get_policy(db, user.org_id, "exposure")


@router.put("/policy")
def put_pol(body: PolicyIn, user: User = Depends(require("exposure.manage")), db: Session = Depends(get_db)):
    vals = {k: v for k, v in body.model_dump().items() if v is not None}
    if not vals:
        raise Unprocessable("No policy fields supplied")
    out = set_policy(db, user.org_id, "exposure", vals, user.id)
    audit.record(db, user, "exposure.policy_updated", "policy", "exposure", f"Exposure policy updated: {vals}", vals)
    db.commit()
    return out


@router.post("/items/{qid}/{action}")
def change_state(qid: int, action: Literal["quarantine", "retire", "release"], body: StateIn,
                 user: User = Depends(require("exposure.manage")), db: Session = Depends(get_db)):
    q = db.get(Question, qid)
    if not q or q.org_id != user.org_id:
        raise NotFound("Question not found")
    target = {"quarantine": "quarantined", "retire": "retired", "release": "approved"}[action]
    set_item_state(db, q, target, user, body.reason)
    db.commit()
    return question_summary(q)


@router.get("/items/{qid}/history")
def item_history(qid: int, user: User = Depends(require("exposure.read")), db: Session = Depends(get_db)):
    rows = db.execute(select(ExposureEvent, Slot, TestForm).join(Slot, Slot.id == ExposureEvent.slot_id)
                      .join(TestForm, TestForm.id == ExposureEvent.form_id).where(ExposureEvent.question_id == qid)
                      .order_by(ExposureEvent.occurred_at)).all()
    return [{"slot": s.name, "slot_code": s.code, "form": f.code, "event_type": e.event_type, "candidates": e.candidate_count,
             "occurred_at": e.occurred_at} for e, s, f in rows]
