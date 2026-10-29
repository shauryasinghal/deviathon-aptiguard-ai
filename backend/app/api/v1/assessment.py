"""Candidate-facing endpoints. Responses never include answer keys, explanations or item codes."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import require
from app.core.errors import NotFound
from app.db.session import get_db
from app.models import Attempt, TestForm, User
from app.services.assessment import (
    attempt_state,
    candidate_safe_form,
    get_candidate,
    save_answers,
    start_attempt,
    submit,
)

router = APIRouter(prefix="/assessment", tags=["candidate assessment"])


class AnswerIn(BaseModel):
    item_ref: int
    selected_key: str | None = Field(default=None, pattern="^[ABCD]$")
    time_spent_ms: int | None = Field(default=None, ge=0, le=3_600_000)


class SaveIn(BaseModel):
    answers: list[AnswerIn] = Field(max_length=200)


@router.get("/available")
def available(user: User = Depends(require("assessment.take")), db: Session = Depends(get_db)):
    cand = get_candidate(db, user.id)
    forms = db.scalars(select(TestForm).where(TestForm.status == "published").order_by(TestForm.id)).all()
    attempts = {a.form_id: a for a in db.scalars(select(Attempt).where(Attempt.candidate_id == cand.id)).all()}
    return {"candidate": {"code": cand.code, "name": cand.display_name},
            "forms": [{"form_id": f.id, "slot": f.slot.name, "slot_starts_at": f.slot.starts_at, "drive": f.slot.drive,
                       "duration_minutes": f.duration_minutes, "n_items": len(f.items),
                       "attempt": None if f.id not in attempts else {"id": attempts[f.id].id, "status": attempts[f.id].status,
                                                                      "score": attempts[f.id].score,
                                                                      "max_score": attempts[f.id].max_score}}
                      for f in forms]}


@router.get("/forms/{form_id}")
def form(form_id: int, user: User = Depends(require("assessment.take")), db: Session = Depends(get_db)):
    f = db.get(TestForm, form_id)
    if not f or f.status != "published":
        raise NotFound("Assessment not available")
    get_candidate(db, user.id)
    return candidate_safe_form(db, f)


@router.post("/forms/{form_id}/attempts", status_code=201)
def start(form_id: int, user: User = Depends(require("assessment.take")), db: Session = Depends(get_db)):
    f = db.get(TestForm, form_id)
    if not f:
        raise NotFound("Assessment not available")
    out = start_attempt(db, get_candidate(db, user.id), f)
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
    except Exception:
        db.commit()  # persist auto-submission on timeout before propagating
        raise
    db.commit()
    return out


@router.post("/attempts/{attempt_id}/submit")
def do_submit(attempt_id: int, user: User = Depends(require("assessment.take")), db: Session = Depends(get_db)):
    out = submit(db, attempt_id, get_candidate(db, user.id))
    db.commit()
    return out
