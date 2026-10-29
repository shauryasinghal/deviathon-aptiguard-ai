"""Candidate-facing endpoints. Responses never include answer keys, explanations or item codes.

Access rule (server-side): a candidate sees and starts only forms assigned to them; starting additionally requires the
form to be published and (when the policy enforces it) the slot window to be open.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import require
from app.core.errors import Conflict
from app.db.session import get_db
from app.models import Attempt, CandidateAssignment, TestForm, User
from app.services.assessment import (
    attempt_state,
    candidate_safe_form,
    get_candidate,
    focus_item,
    require_access,
    save_answers,
    start_attempt,
    submit,
    window_state,
)

router = APIRouter(prefix="/assessment", tags=["candidate assessment"])


class AnswerIn(BaseModel):
    item_ref: int
    selected_key: str | None = Field(default=None, pattern="^[ABCD]$")
    # Deprecated and ignored: kept only so older clients still validate. Timing is measured by the server (see /focus).
    time_spent_ms: int | None = Field(default=None, ge=0, le=3_600_000)


class FocusIn(BaseModel):
    item_ref: int


class SaveIn(BaseModel):
    answers: list[AnswerIn] = Field(max_length=200)


@router.get("/available")
def available(user: User = Depends(require("assessment.take")), db: Session = Depends(get_db)):
    cand = get_candidate(db, user.id)
    forms = db.scalars(select(TestForm).join(CandidateAssignment, CandidateAssignment.form_id == TestForm.id)
                       .where(CandidateAssignment.candidate_id == cand.id).order_by(TestForm.id)).all()
    attempts = {a.form_id: a for a in db.scalars(select(Attempt).where(Attempt.candidate_id == cand.id)).all()}
    out = []
    for f in forms:
        a = attempts.get(f.id)
        w = window_state(db, f)
        out.append({"form_id": f.id, "slot": f.slot.name, "slot_starts_at": f.slot.starts_at, "drive": f.slot.drive,
                    "duration_minutes": f.duration_minutes, "n_items": len(f.items), "form_status": f.status,
                    "window": {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in w.items()},
                    "can_start": a is None and f.status == "published" and w["state"] == "open",
                    "attempt": None if a is None else {"id": a.id, "status": a.status, "score": a.score, "max_score": a.max_score}})
    return {"candidate": {"code": cand.code, "name": cand.display_name}, "forms": out}


@router.get("/forms/{form_id}")
def form(form_id: int, user: User = Depends(require("assessment.take")), db: Session = Depends(get_db)):
    cand = get_candidate(db, user.id)
    f = require_access(db, cand, db.get(TestForm, form_id))
    return {**candidate_safe_form(db, f), "window": window_state(db, f), "form_status": f.status}


@router.post("/forms/{form_id}/attempts", status_code=201)
def start(form_id: int, user: User = Depends(require("assessment.take")), db: Session = Depends(get_db)):
    out = start_attempt(db, get_candidate(db, user.id), db.get(TestForm, form_id))
    db.commit()
    return out


@router.get("/attempts/{attempt_id}")
def state(attempt_id: int, user: User = Depends(require("assessment.take")), db: Session = Depends(get_db)):
    out = attempt_state(db, attempt_id, get_candidate(db, user.id))
    db.commit()
    return out


@router.put("/attempts/{attempt_id}/responses")
def save(attempt_id: int, body: SaveIn, user: User = Depends(require("assessment.take")), db: Session = Depends(get_db)):
    try:
        out = save_answers(db, attempt_id, get_candidate(db, user.id), [a.model_dump() for a in body.answers])
    except Conflict:
        db.commit()  # persist a server-side auto-submission (deadline passed) before reporting the conflict
        raise
    db.commit()
    return out


@router.post("/attempts/{attempt_id}/focus")
def focus(attempt_id: int, body: FocusIn, user: User = Depends(require("assessment.take")), db: Session = Depends(get_db)):
    """Tell the server which item is on screen; the server clock (not the client's) measures the interval."""
    try:
        out = focus_item(db, attempt_id, get_candidate(db, user.id), body.item_ref)
    except Conflict:
        db.commit()  # persist a server-side auto-submission (deadline passed) before reporting the conflict
        raise
    db.commit()
    return out


@router.post("/attempts/{attempt_id}/submit")
def do_submit(attempt_id: int, user: User = Depends(require("assessment.take")), db: Session = Depends(get_db)):
    out = submit(db, attempt_id, get_candidate(db, user.id))
    db.commit()
    return out
