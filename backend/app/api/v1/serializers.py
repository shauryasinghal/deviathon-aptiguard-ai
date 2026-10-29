"""Response shaping. Staff views may include answer keys; candidate views are built separately in services.assessment."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    LeakAlert,
    Question,
    QuestionRevision,
    ReviewDecision,
    User,
    ValidationResult,
)


def user_label(db: Session, user_id: int | None) -> dict | None:
    if not user_id:
        return None
    u = db.get(User, user_id)
    return {"id": u.id, "name": u.full_name, "role": u.role.label} if u else None


def question_summary(q: Question, exposure=None, risk: dict | None = None) -> dict:
    return {
        "id": q.id, "code": q.code, "section": q.section.code, "section_name": q.section.name, "skill": q.skill,
        "family_id": q.family_id, "family_code": q.family.code, "concept": q.family.concept, "is_source": q.is_source,
        "parent_id": q.parent_id, "stem": q.stem, "difficulty_target": q.difficulty_target, "status": q.status,
        "status_reason": q.status_reason, "leak_status": q.leak_status, "validation_status": q.validation_status,
        "generation_method": q.generation_method, "template_id": q.template_id, "version": q.version,
        "is_synthetic": q.is_synthetic, "data_source": q.data_source, "created_at": q.created_at, "updated_at": q.updated_at,
        "approved_at": q.approved_at,
        "exposure_slots": exposure.slot_count if exposure else 0,
        "candidate_exposures": exposure.candidate_exposures if exposure else 0,
        "last_used_at": exposure.last_used_at if exposure else None,
        "risk": risk,
    }


def validation_rows(db: Session, qid: int) -> list[dict]:
    rows = db.scalars(select(ValidationResult).where(ValidationResult.question_id == qid).order_by(ValidationResult.id)).all()
    return [{"check": r.check, "status": r.status, "severity": r.severity, "message": r.message, "details": r.details,
             "run_at": r.run_at} for r in rows]


def question_detail(db: Session, q: Question, include_key: bool = True) -> dict:
    d = question_summary(q)
    d.update({
        "explanation": q.explanation if include_key else None,
        "tags": q.tags, "params": q.params if include_key else None, "template_version": q.template_version,
        "review_requirement": q.review_requirement, "generation_run_id": q.generation_run_id,
        "options": [{"key": o.key, "text": o.text, "is_correct": o.is_correct if include_key else None,
                     "rationale": o.rationale if include_key else None} for o in q.options],
        "validation": validation_rows(db, q.id),
        "created_by": user_label(db, q.created_by), "approved_by": user_label(db, q.approved_by),
    })
    return d


def revisions(db: Session, qid: int) -> list[dict]:
    revs = db.scalars(select(QuestionRevision).where(QuestionRevision.question_id == qid).order_by(QuestionRevision.version,
                                                                                                    QuestionRevision.id)).all()
    decisions = db.scalars(select(ReviewDecision).where(ReviewDecision.question_id == qid).order_by(ReviewDecision.id)).all()
    return {
        "revisions": [{"version": r.version, "change_type": r.change_type, "by": user_label(db, r.changed_by), "at": r.created_at,
                       "note": r.note, "snapshot": r.snapshot} for r in revs],
        "decisions": [{"decision": d.decision, "by": user_label(db, d.reviewer_id), "at": d.created_at, "comment": d.comment,
                       "version": d.question_version} for d in decisions],
    }


def alert_summary(a: LeakAlert, q: Question | None = None) -> dict:
    return {
        "id": a.id, "code": a.code, "question_id": a.question_id, "question_code": q.code if q else None,
        "section": q.section.code if q else None, "family_id": a.family_id, "alert_type": a.alert_type,
        "evidence_class": a.evidence_class, "severity": a.severity, "score": a.score, "title": a.title, "status": a.status,
        "detected_at": a.detected_at, "first_detectable_slot": a.first_detectable_slot,
        "signals": a.signals, "recommended_action": a.recommended_action,
    }
