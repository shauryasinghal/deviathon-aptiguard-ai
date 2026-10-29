from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.v1.serializers import question_detail, question_summary, revisions
from app.core.deps import require
from app.core.errors import Conflict, NotFound, Unprocessable
from app.db.session import get_db
from app.models import AnswerOption, Question, Section, User, VariantFamily
from app.services import audit
from app.services.exposure.service import exposure_stats, leaked_families, risk_score
from app.services.generation.base import KEYS
from app.services.generation.registry import DIFFICULTY_B
from app.services.policies import get_policy
from app.services.questions import SECTION_PREFIX, add_revision, revalidate
from app.services.textsim import item_fulltext, text_hash

router = APIRouter(prefix="/questions", tags=["questions"])

SORTS = {"code": Question.code, "updated": Question.updated_at.desc(), "created": Question.created_at.desc(),
         "status": Question.status}


class OptionIn(BaseModel):
    key: Literal["A", "B", "C", "D"]
    text: str = Field(min_length=1, max_length=500)
    is_correct: bool = False


class QuestionCreate(BaseModel):
    section: Literal["QUANT", "LOGICAL", "VERBAL"]
    skill: str = Field(min_length=2, max_length=80)
    concept: str = Field(min_length=2, max_length=200)
    stem: str = Field(min_length=15, max_length=4000)
    explanation: str = Field(min_length=5, max_length=4000)
    difficulty_target: Literal["easy", "medium", "hard"]
    options: list[OptionIn]
    tags: list[str] = []

    @field_validator("options")
    @classmethod
    def _four(cls, v):
        if len(v) != 4 or sorted(o.key for o in v) != KEYS:
            raise ValueError("exactly four options keyed A–D are required")
        if sum(o.is_correct for o in v) != 1:
            raise ValueError("exactly one option must be correct")
        return v


class QuestionUpdate(BaseModel):
    stem: str | None = Field(default=None, min_length=15, max_length=4000)
    explanation: str | None = Field(default=None, min_length=5, max_length=4000)
    difficulty_target: Literal["easy", "medium", "hard"] | None = None
    options: list[OptionIn] | None = None
    note: str | None = Field(default=None, max_length=500)

    @field_validator("options")
    @classmethod
    def _four(cls, v):
        if v is None:
            return v
        return QuestionCreate._four(v)


class BulkIn(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=200)
    action: Literal["archive", "submit_for_review"]
    reason: str = Field(min_length=5, max_length=300)


@router.get("")
def list_questions(
    q: str | None = Query(default=None, max_length=200), section: str | None = None, status: str | None = None,
    difficulty: str | None = None, leak_status: str | None = None, source_only: bool = False,
    family_id: int | None = None, sort: str = "code", page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=200),
    user: User = Depends(require("questions.read")), db: Session = Depends(get_db),
):
    stmt = select(Question).where(Question.org_id == user.org_id)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Question.code.ilike(like), Question.stem.ilike(like), Question.skill.ilike(like)))
    if section:
        stmt = stmt.join(Section, Section.id == Question.section_id).where(Section.code == section)
    if status:
        stmt = stmt.where(Question.status.in_(status.split(",")))
    else:
        stmt = stmt.where(Question.status != "archived")
    if difficulty:
        stmt = stmt.where(Question.difficulty_target == difficulty)
    if leak_status:
        stmt = stmt.where(Question.leak_status.in_(leak_status.split(",")))
    if source_only:
        stmt = stmt.where(Question.is_source.is_(True))
    if family_id:
        stmt = stmt.where(Question.family_id == family_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(SORTS.get(sort, Question.code)).offset((page - 1) * page_size).limit(page_size)).all()
    stats = exposure_stats(db, user.org_id, [r.id for r in rows])
    pol = get_policy(db, user.org_id, "exposure")
    fams = leaked_families(db, user.org_id)
    items = [question_summary(r, stats.get(r.id), risk_score(stats.get(r.id), r, pol, r.family_id in fams)) for r in rows]
    counts = dict(db.execute(select(Question.status, func.count()).where(Question.org_id == user.org_id)
                             .group_by(Question.status)).all())
    return {"items": items, "total": total, "page": page, "page_size": page_size, "status_counts": counts}


@router.get("/{qid}")
def get_question(qid: int, user: User = Depends(require("questions.read")), db: Session = Depends(get_db)):
    q = _get(db, qid, user)
    d = question_detail(db, q)
    stats = exposure_stats(db, user.org_id, [q.id]).get(q.id)
    d["exposure"] = {"slots": stats.slots if stats else [], "slot_count": stats.slot_count if stats else 0,
                     "candidate_exposures": stats.candidate_exposures if stats else 0,
                     "response_count": stats.response_count if stats else 0,
                     "last_used_at": stats.last_used_at if stats else None,
                     "risk": risk_score(stats, q, get_policy(db, user.org_id, "exposure"),
                                        q.family_id in leaked_families(db, user.org_id))}
    d["family"] = [question_summary(m) for m in db.scalars(select(Question).where(Question.family_id == q.family_id)
                                                           .order_by(Question.is_source.desc(), Question.code)).all()]
    d["history"] = revisions(db, q.id)
    from app.models import ItemCalibration, CalibrationRun
    cal = db.execute(select(ItemCalibration, CalibrationRun.created_at).join(CalibrationRun, CalibrationRun.id == ItemCalibration.run_id)
                     .where(ItemCalibration.question_id == q.id).order_by(ItemCalibration.id.desc())).first()
    if cal:
        ic, when = cal
        d["calibration"] = {"run_at": when, "status": ic.status, "n": ic.n_valid, "p": ic.p_value, "p_ci": [ic.p_ci_low, ic.p_ci_high],
                            "rasch_b": ic.rasch_b, "rasch_se": ic.rasch_se, "item_rest_r": ic.item_rest_r,
                            "diff_from_reference": ic.diff_from_reference, "diff_ci": [ic.diff_ci_low, ic.diff_ci_high],
                            "recommended_action": ic.recommended_action, "warnings": ic.warnings}
    from app.models import LeakAlert
    d["alerts"] = [{"id": a.id, "code": a.code, "severity": a.severity, "status": a.status, "title": a.title}
                   for a in db.scalars(select(LeakAlert).where(LeakAlert.question_id == q.id)).all()]
    return d


@router.post("", status_code=201)
def create_question(body: QuestionCreate, user: User = Depends(require("questions.write")), db: Session = Depends(get_db)):
    sec = db.scalar(select(Section).where(Section.code == body.section))
    n = (db.scalar(select(func.count()).select_from(VariantFamily).where(VariantFamily.section_id == sec.id)) or 0) + 1
    prefix = SECTION_PREFIX[body.section]
    code = f"{prefix}-USR-{n:03d}"
    while db.scalar(select(VariantFamily.id).where(VariantFamily.code == f"FAM-{code}")):
        n += 1
        code = f"{prefix}-USR-{n:03d}"
    fam = VariantFamily(code=f"FAM-{code}", org_id=user.org_id, section_id=sec.id, concept=body.concept, skill=body.skill)
    db.add(fam)
    db.flush()
    q = Question(code=f"{code}-S", org_id=user.org_id, section_id=sec.id, family_id=fam.id, is_source=True, skill=body.skill,
                 tags=body.tags, stem=body.stem.strip(), explanation=body.explanation.strip(),
                 difficulty_target=body.difficulty_target, difficulty_target_b=DIFFICULTY_B[body.difficulty_target],
                 status="pending_review", generation_method="human_authored", data_source="user", is_synthetic=False,
                 normalized_hash=text_hash(item_fulltext(body.stem, [o.text for o in body.options])), created_by=user.id)
    q.options = [AnswerOption(key=o.key, text=o.text.strip(), is_correct=o.is_correct, position=i)
                 for i, o in enumerate(sorted(body.options, key=lambda o: o.key))]
    db.add(q)
    db.flush()
    fam.source_question_id = q.id
    status, _ = revalidate(db, q)
    add_revision(db, q, "created", user, "Authored manually")
    audit.record(db, user, "questions.created", "question", q.code, f"Created source question {q.code} (validation: {status})")
    db.commit()
    return question_detail(db, q)


@router.patch("/{qid}")
def update_question(qid: int, body: QuestionUpdate, user: User = Depends(require("questions.read")),
                    db: Session = Depends(get_db)):
    from app.core.deps import user_permissions

    perms = user_permissions(user)
    if not ({"questions.write", "review.decide"} & perms):
        raise Conflict("Editing requires questions.write or review.decide")
    q = _get(db, qid, user)
    if q.status in ("archived", "retired"):
        raise Conflict(f"Cannot edit an item in status '{q.status}'")
    changed = []
    if body.stem is not None and body.stem.strip() != q.stem:
        q.stem = body.stem.strip(); changed.append("stem")
    if body.explanation is not None and body.explanation.strip() != q.explanation:
        q.explanation = body.explanation.strip(); changed.append("explanation")
    if body.difficulty_target and body.difficulty_target != q.difficulty_target:
        q.difficulty_target = body.difficulty_target
        q.difficulty_target_b = DIFFICULTY_B[body.difficulty_target]; changed.append("difficulty")
    if body.options is not None:
        new = {o.key: o for o in body.options}
        for o in q.options:
            if o.text != new[o.key].text.strip() or o.is_correct != new[o.key].is_correct:
                changed.append(f"option {o.key}")
            o.text, o.is_correct = new[o.key].text.strip(), new[o.key].is_correct
    if not changed:
        raise Unprocessable("No changes")
    q.normalized_hash = text_hash(item_fulltext(q.stem, [o.text for o in q.options]))
    q.version += 1
    prev_status = q.status
    if q.status == "approved":
        q.status, q.approved_by, q.approved_at = "pending_review", None, None  # edits require fresh approval
    if q.generation_method in ("template", "llm") and "edited" not in (q.tags or []):
        q.tags = list(q.tags or []) + ["edited"]
    status, _ = revalidate(db, q)
    add_revision(db, q, "edited", user, body.note or f"Edited: {', '.join(changed)}")
    audit.record(db, user, "questions.edited", "question", q.code,
                 f"Edited {q.code} ({', '.join(changed)}); validation {status}; status {prev_status} → {q.status}")
    db.commit()
    return question_detail(db, q)


@router.post("/{qid}/archive")
def archive_question(qid: int, user: User = Depends(require("questions.write")), db: Session = Depends(get_db)):
    q = _get(db, qid, user)
    if q.status == "archived":
        raise Conflict("Already archived")
    prev = q.status
    q.status, q.status_reason = "archived", f"Archived by {user.full_name}"
    q.version += 1
    add_revision(db, q, "status_change", user, f"{prev} → archived")
    audit.record(db, user, "questions.archived", "question", q.code, f"Archived {q.code}")
    db.commit()
    return question_summary(q)


@router.post("/bulk")
def bulk(body: BulkIn, user: User = Depends(require("questions.write")), db: Session = Depends(get_db)):
    done, skipped = [], []
    for qid in body.ids:
        q = db.get(Question, qid)
        if not q or q.org_id != user.org_id:
            skipped.append({"id": qid, "reason": "not found"}); continue
        if body.action == "archive" and q.status not in ("archived",):
            prev = q.status
            q.status, q.status_reason = "archived", body.reason
            q.version += 1
            add_revision(db, q, "status_change", user, f"{prev} → archived (bulk): {body.reason}")
            done.append(q.code)
        elif body.action == "submit_for_review" and q.status in ("draft", "rejected"):
            q.status, q.status_reason = "pending_review", body.reason
            q.version += 1
            add_revision(db, q, "status_change", user, f"→ pending_review (bulk): {body.reason}")
            done.append(q.code)
        else:
            skipped.append({"id": qid, "code": q.code, "reason": f"not applicable to status '{q.status}'"})
    audit.record(db, user, f"questions.bulk_{body.action}", "question", None, f"Bulk {body.action}: {len(done)} item(s)",
                 {"codes": done})
    db.commit()
    return {"updated": done, "skipped": skipped}


@router.get("/{qid}/history")
def history(qid: int, user: User = Depends(require("questions.read")), db: Session = Depends(get_db)):
    _get(db, qid, user)
    return revisions(db, qid)


def _get(db: Session, qid: int, user: User) -> Question:
    q = db.get(Question, qid)
    if not q or q.org_id != user.org_id:
        raise NotFound("Question not found")
    return q
