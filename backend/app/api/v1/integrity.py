"""Staff workflow for attempts affected by withdrawn questions (reviewer/admin: `review.decide`)."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import require
from app.db.session import get_db
from app.models import Attempt, Candidate, Slot, TestForm, User
from app.services.assessment import resolve_flagged_attempt

router = APIRouter(prefix="/integrity", tags=["integrity review"])


class ResolutionIn(BaseModel):
    decision: Literal["retain_original", "use_alternative", "reassessment"]
    reason: str = Field(min_length=10, max_length=1000)


def _view(a: Attempt, cand_code: str, form: TestForm) -> dict:
    f = a.review_flags or {}
    return {"attempt_id": a.id, "candidate": cand_code, "form": form.code, "slot": form.slot.name, "status": a.status,
            "submitted_at": a.submitted_at, "official_score": a.score, "official_max": a.max_score,
            "alternative_score": f.get("score_excluding_flagged"), "alternative_max": f.get("max_excluding_flagged"),
            "decision": f.get("decision", "pending"), "items": f.get("items", []), "resolutions": f.get("resolutions", []),
            "reopened_at": f.get("reopened_at")}


@router.get("/flagged-attempts")
def flagged(state: Literal["pending", "resolved", "all"] = "pending", user: User = Depends(require("review.decide")),
            db: Session = Depends(get_db)):
    rows = db.execute(select(Attempt, Candidate.code, TestForm).join(Candidate, Candidate.id == Attempt.candidate_id)
                      .join(TestForm, TestForm.id == Attempt.form_id).join(Slot, Slot.id == TestForm.slot_id)
                      .where(Slot.org_id == user.org_id, Attempt.review_flags.is_not(None)).order_by(Attempt.id)).all()
    out = [_view(a, code, f) for a, code, f in rows]
    if state != "all":
        out = [x for x in out if (x["decision"] == "pending") == (state == "pending")]
    return {"items": out, "total": len(out)}


@router.post("/attempts/{attempt_id}/resolution")
def resolve(attempt_id: int, body: ResolutionIn, user: User = Depends(require("review.decide")), db: Session = Depends(get_db)):
    a = resolve_flagged_attempt(db, attempt_id, body.decision, body.reason, user)
    db.commit()
    cand = db.get(Candidate, a.candidate_id)
    return _view(a, cand.code, db.get(TestForm, a.form_id))
