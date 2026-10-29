"""Question persistence helpers: creation from generated items, revisions, validation persistence."""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AnswerOption, Question, QuestionRevision, Section, User, ValidationResult, VariantFamily
from app.services.generation.base import Check, GeneratedItem
from app.services.generation.registry import DIFFICULTY_B
from app.services.textsim import item_fulltext, normalize, text_hash
from app.services.validation.validator import BankEntry, validate

SECTION_PREFIX = {"QUANT": "QNT", "LOGICAL": "LOG", "VERBAL": "VRB"}


def bank_entries(db: Session, org_id: int, exclude_statuses=("rejected", "archived")) -> list[BankEntry]:
    rows = db.scalars(select(Question).where(Question.org_id == org_id, Question.status.notin_(exclude_statuses))).all()
    return [
        BankEntry(q.id, q.code, normalize(item_fulltext(q.stem, [o.text for o in q.options])), q.normalized_hash,
                  q.template_id, q.params)
        for q in rows
    ]


def item_from_question(q: Question) -> GeneratedItem:
    return GeneratedItem(
        section=q.section.code, template_id=q.template_id or "", concept=q.family.concept, skill=q.skill,
        difficulty=q.difficulty_target, stem=q.stem,
        options=[{"key": o.key, "text": o.text, "is_correct": o.is_correct, "rationale": o.rationale} for o in q.options],
        explanation=q.explanation, params=q.params or {}, tags=list(q.tags or []), review_requirement=q.review_requirement,
    )


def snapshot(q: Question) -> dict:
    return {
        "code": q.code, "stem": q.stem, "explanation": q.explanation, "difficulty_target": q.difficulty_target,
        "status": q.status, "skill": q.skill,
        "options": [{"key": o.key, "text": o.text, "is_correct": o.is_correct} for o in q.options],
    }


def add_revision(db: Session, q: Question, change_type: str, user: User | None, note: str | None = None) -> None:
    db.flush()
    db.add(QuestionRevision(question_id=q.id, version=q.version, change_type=change_type,
                            changed_by=user.id if user else None, snapshot=snapshot(q), note=note))


def persist_checks(db: Session, q: Question, checks: list[Check]) -> None:
    for old in db.scalars(select(ValidationResult).where(ValidationResult.question_id == q.id)).all():
        db.delete(old)
    for c in checks:
        db.add(ValidationResult(question_id=q.id, check=c.check, status=c.status, severity=c.severity,
                                message=c.message[:500], details=c.details))


def revalidate(db: Session, q: Question, method: str | None = None) -> tuple[str, list[Check]]:
    source_diff = None
    if q.parent_id:
        parent = db.get(Question, q.parent_id)
        source_diff = parent.difficulty_target if parent else None
    status, checks = validate(item_from_question(q), bank_entries(db, q.org_id), method or q.generation_method,
                              exclude_ids={q.id}, source_difficulty=source_diff)
    q.validation_status = status
    persist_checks(db, q, checks)
    return status, checks


def next_variant_code(db: Session, family: VariantFamily) -> str:
    n = db.scalar(select(func.count()).select_from(Question).where(Question.family_id == family.id)) or 0
    base = family.code.replace("FAM-", "")
    while True:
        code = f"{base}-V{n:02d}"
        if not db.scalar(select(Question.id).where(Question.code == code)):
            return code
        n += 1


def create_from_item(
    db: Session, item: GeneratedItem, *, org_id: int, family: VariantFamily, code: str, parent: Question | None,
    method: str, status: str, user: User | None, generation_run_id: int | None = None, is_source: bool = False,
    data_source: str = "synthetic_demo", is_synthetic: bool = True,
) -> Question:
    section = db.scalar(select(Section).where(Section.code == item.section))
    q = Question(
        code=code, org_id=org_id, section_id=section.id, family_id=family.id, parent_id=parent.id if parent else None,
        is_source=is_source, skill=item.skill, tags=item.tags, stem=item.stem, explanation=item.explanation,
        difficulty_target=item.difficulty, difficulty_target_b=DIFFICULTY_B[item.difficulty], status=status,
        generation_method=method, generation_run_id=generation_run_id, template_id=item.template_id or None,
        template_version=item.template_version, params=item.params, review_requirement=item.review_requirement,
        normalized_hash=text_hash(item_fulltext(item.stem, [o["text"] for o in item.options])),
        data_source=data_source, is_synthetic=is_synthetic, created_by=user.id if user else None,
    )
    q.options = [AnswerOption(key=o["key"], text=o["text"], is_correct=o["is_correct"], position=i,
                              rationale=o.get("rationale")) for i, o in enumerate(item.options)]
    db.add(q)
    db.flush()
    return q
