from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.serializers import question_detail, revisions, user_label
from app.core.config import get_settings
from app.core.deps import require
from app.core.errors import Conflict, NotFound
from app.db.base import utcnow
from app.db.session import get_db
from app.models import GenerationRun, Question, ReviewDecision, User
from app.services import audit
from app.services.generation.engine import generate_variants
from app.services.generation.registry import TEMPLATES, catalog
from app.services.policies import get_policy
from app.services.questions import add_revision, revalidate

router = APIRouter(tags=["variants & review"])


class GenerateIn(BaseModel):
    n: int = Field(default=3, ge=1, le=10)
    difficulty: Literal["easy", "medium", "hard"] | None = None
    seed: int | None = Field(default=None, ge=0, le=2**31)
    method: Literal["auto", "template", "llm"] = "auto"


class DecisionIn(BaseModel):
    decision: Literal["approve", "reject", "request_regeneration"]
    comment: str | None = Field(default=None, max_length=1000)


@router.get("/variants/templates")
def templates(user: User = Depends(require("questions.read"))):
    s = get_settings()
    return {"templates": catalog(), "llm": {"provider": s.llm_provider, "configured": s.llm_configured,
                                             "model": s.llm_model if s.llm_configured else None}}


@router.post("/questions/{qid}/variants:generate", status_code=201)
def generate(qid: int, body: GenerateIn, user: User = Depends(require("variants.generate")), db: Session = Depends(get_db)):
    src = db.get(Question, qid)
    if not src or src.org_id != user.org_id:
        raise NotFound("Source question not found")
    if src.status in ("archived", "retired") or src.leak_status == "confirmed":
        raise Conflict(f"Cannot generate from an item that is {src.status if src.status in ('archived', 'retired') else 'confirmed leaked'}")
    run, created, rejections = generate_variants(db, src, body.n, body.difficulty, user, body.seed, body.method)
    db.commit()
    return {"run": _run(db, run), "created": [question_detail(db, q) for q in created], "rejections": rejections}


@router.get("/generation-runs")
def runs(source_id: int | None = None, limit: int = 20, user: User = Depends(require("questions.read")),
         db: Session = Depends(get_db)):
    stmt = (select(GenerationRun).join(Question, Question.id == GenerationRun.source_question_id)
            .where(Question.org_id == user.org_id).order_by(GenerationRun.id.desc()).limit(max(1, min(limit, 100))))
    if source_id:
        stmt = stmt.where(GenerationRun.source_question_id == source_id)
    return [_run(db, r) for r in db.scalars(stmt).all()]


def _run(db: Session, r: GenerationRun) -> dict:
    src = db.get(Question, r.source_question_id)
    return {"id": r.id, "source_code": src.code if src else None, "method": r.method, "provider": r.provider, "model": r.model,
            "prompt_version": r.prompt_version, "seed": r.seed, "target_difficulty": r.target_difficulty,
            "n_requested": r.n_requested, "n_generated": r.n_generated, "n_rejected": r.n_rejected, "status": r.status,
            "message": r.message, "created_at": r.created_at, "requested_by": user_label(db, r.requested_by)}


@router.get("/questions/{qid}/compare")
def compare(qid: int, user: User = Depends(require("questions.read")), db: Session = Depends(get_db)):
    q = db.get(Question, qid)
    if not q or q.org_id != user.org_id:
        raise NotFound("Question not found")
    src = db.get(Question, q.parent_id) if q.parent_id else q
    members = db.scalars(select(Question).where(Question.family_id == src.family_id).order_by(Question.is_source.desc(), Question.code)).all()
    return {"source": question_detail(db, src), "variants": [question_detail(db, m) for m in members if m.id != src.id]}


@router.post("/questions/{qid}/validate")
def validate_item(qid: int, user: User = Depends(require("questions.read")), db: Session = Depends(get_db)):
    q = db.get(Question, qid)
    if not q or q.org_id != user.org_id:
        raise NotFound("Question not found")
    status, _ = revalidate(db, q)
    audit.record(db, user, "questions.validated", "question", q.code, f"Re-validated {q.code}: {status}")
    db.commit()
    return question_detail(db, q)


@router.get("/review/queue")
def queue(section: str | None = None, validation: str | None = None, user: User = Depends(require("questions.read")),
          db: Session = Depends(get_db)):
    stmt = select(Question).where(Question.org_id == user.org_id, Question.status == "pending_review").order_by(Question.created_at.desc())
    items = db.scalars(stmt).all()
    if section:
        items = [i for i in items if i.section.code == section]
    if validation:
        items = [i for i in items if i.validation_status == validation]
    out = []
    for q in items:
        src = db.get(Question, q.parent_id) if q.parent_id else None
        out.append({"item": question_detail(db, q), "source": question_detail(db, src) if src else None,
                    "history": revisions(db, q.id)})
    recent = db.scalars(select(ReviewDecision).order_by(ReviewDecision.id.desc()).limit(15)).all()
    return {"items": out, "total": len(out), "recent_decisions": [
        {"question_code": db.get(Question, d.question_id).code, "decision": d.decision, "by": user_label(db, d.reviewer_id),
         "at": d.created_at, "comment": d.comment} for d in recent]}


@router.post("/review/{qid}/decision")
def decide(qid: int, body: DecisionIn, user: User = Depends(require("review.decide")), db: Session = Depends(get_db)):
    q = db.get(Question, qid)
    if not q or q.org_id != user.org_id:
        raise NotFound("Question not found")
    if q.status != "pending_review":
        raise Conflict(f"Only items pending review can be decided (current status '{q.status}')")
    result: dict = {}
    if body.decision == "approve":
        status, checks = revalidate(db, q)  # gates are evaluated on fresh validation, never on stale results
        crit = [c.message for c in checks if c.status == "fail" and c.severity == "critical"]
        if status == "failed" or crit:
            db.commit()
            raise Conflict("Quality gate failed: unresolved critical validation issues", {"issues": crit})
        pol = get_policy(db, user.org_id, "review")
        if pol["require_independent_reviewer"] and q.created_by == user.id:
            raise Conflict("Independent review required: the author/generator of an item cannot approve it")
        q.status, q.approved_by, q.approved_at, q.status_reason = "approved", user.id, utcnow(), None
        add_revision(db, q, "status_change", user, f"Approved: {body.comment or 'no comment'}")
    elif body.decision == "reject":
        if not body.comment or len(body.comment.strip()) < 5:
            raise Conflict("A rejection reason (≥5 characters) is required")
        q.status, q.status_reason = "rejected", body.comment
        add_revision(db, q, "status_change", user, f"Rejected: {body.comment}")
    else:
        q.status, q.status_reason = "rejected", f"Regeneration requested: {body.comment or 'no comment'}"
        add_revision(db, q, "status_change", user, q.status_reason)
        src = db.get(Question, q.parent_id) if q.parent_id else None
        if src and src.template_id in TEMPLATES:
            run, created, _ = generate_variants(db, src, 1, q.difficulty_target, user, method="template")
            result["regenerated"] = [question_detail(db, c) for c in created]
            result["generation_run_id"] = run.id
    db.add(ReviewDecision(question_id=q.id, reviewer_id=user.id, decision=body.decision, comment=body.comment,
                          question_version=q.version))
    audit.record(db, user, f"review.{body.decision}", "question", q.code, f"{body.decision.replace('_', ' ')}: {q.code}",
                 {"comment": body.comment})
    db.commit()
    return {"item": question_detail(db, q), **result}
