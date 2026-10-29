from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.v1.serializers import user_label
from app.api.v1.uploads import read_upload
from app.core.deps import require
from app.core.errors import NotFound
from app.db.session import get_db
from app.models import CalibrationRun, ItemCalibration, Question, Section, User
from app.services.assessment import finalize_expired
from app.services.calibration.service import STATUS_LABELS, run_calibration
from app.services.importers import import_response_log, read_table, validate_response_frame

router = APIRouter(prefix="/calibration", tags=["calibration"])


class RunIn(BaseModel):
    min_responses: int | None = Field(default=None, ge=10, le=10000)
    tolerance_logits: float | None = Field(default=None, gt=0, le=3)


def _run_dict(db: Session, r: CalibrationRun) -> dict:
    return {"id": r.id, "created_at": r.created_at, "method": r.method, "data_source": r.data_source, "params": r.params,
            "n_responses": r.n_responses, "n_items": r.n_items, "n_persons": r.n_persons, "rasch_fitted": r.rasch_fitted,
            "status": r.status, "summary": r.summary, "warnings": r.warnings, "created_by": user_label(db, r.created_by)}


def _latest(db: Session, org_id: int, run_id: int | None = None) -> CalibrationRun:
    stmt = select(CalibrationRun).where(CalibrationRun.org_id == org_id)
    r = db.scalar(stmt.where(CalibrationRun.id == run_id)) if run_id else db.scalar(stmt.order_by(CalibrationRun.id.desc()))
    if not r:
        raise NotFound("No calibration run yet")
    return r


@router.post("/runs", status_code=201)
def create_run(body: RunIn, user: User = Depends(require("calibration.run")), db: Session = Depends(get_db)):
    overrides = {k: v for k, v in body.model_dump().items() if v is not None}
    finalize_expired(db)  # analyses only see scored attempts: score expired ones first
    r = run_calibration(db, user.org_id, user, overrides)
    db.commit()
    return _run_dict(db, r)


@router.get("/runs")
def list_runs(user: User = Depends(require("calibration.read")), db: Session = Depends(get_db)):
    rows = db.scalars(select(CalibrationRun).where(CalibrationRun.org_id == user.org_id).order_by(CalibrationRun.id.desc()).limit(20)).all()
    return [_run_dict(db, r) for r in rows]


@router.get("/runs/latest")
def latest(run_id: int | None = None, user: User = Depends(require("calibration.read")), db: Session = Depends(get_db)):
    r = _latest(db, user.org_id, run_id)
    counts = dict(db.execute(select(ItemCalibration.status, func.count()).where(ItemCalibration.run_id == r.id)
                             .group_by(ItemCalibration.status)).all())
    total_q = db.scalar(select(func.count()).select_from(Question).where(Question.org_id == user.org_id,
                                                                         Question.status.in_(("approved", "pending_review"))))
    counts["pending_calibration"] = max(0, (total_q or 0) - sum(counts.values()))
    return {**_run_dict(db, r), "status_counts": counts, "status_labels": STATUS_LABELS}


@router.get("/items")
def items(run_id: int | None = None, section: str | None = None, status: str | None = None, q: str | None = None,
          variants_only: bool = False, sort: str = "code", page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=500),
          user: User = Depends(require("calibration.read")), db: Session = Depends(get_db)):
    r = _latest(db, user.org_id, run_id)
    stmt = (select(ItemCalibration, Question).join(Question, Question.id == ItemCalibration.question_id)
            .where(ItemCalibration.run_id == r.id))
    if section:
        stmt = stmt.join(Section, Section.id == Question.section_id).where(Section.code == section)
    if status:
        stmt = stmt.where(ItemCalibration.status.in_(status.split(",")))
    if q:
        stmt = stmt.where(Question.code.ilike(f"%{q}%"))
    if variants_only:
        stmt = stmt.where(ItemCalibration.reference_question_id.is_not(None))
    order = {"code": Question.code, "n": ItemCalibration.n_valid.desc(), "p": ItemCalibration.p_value,
             "b": ItemCalibration.rasch_b, "diff": func.abs(ItemCalibration.diff_from_reference).desc()}.get(sort, Question.code)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.execute(stmt.order_by(order).offset((page - 1) * page_size).limit(page_size)).all()
    out = []
    for ic, qq in rows:
        ref = db.get(Question, ic.reference_question_id) if ic.reference_question_id else None
        out.append({"question_id": qq.id, "code": qq.code, "section": qq.section.code, "family_code": qq.family.code,
                    "is_source": qq.is_source, "difficulty_target": qq.difficulty_target, "leak_status": qq.leak_status,
                    "reference_code": ref.code if ref else None, "n_presented": ic.n_presented, "n_valid": ic.n_valid,
                    "n_correct": ic.n_correct, "p": ic.p_value, "p_ci": [ic.p_ci_low, ic.p_ci_high], "missing_rate": ic.missing_rate,
                    "item_rest_r": ic.item_rest_r, "median_rt_ms": ic.median_rt_ms, "rasch_b": ic.rasch_b, "rasch_se": ic.rasch_se,
                    "outfit": ic.outfit_msq, "diff": ic.diff_from_reference, "diff_ci": [ic.diff_ci_low, ic.diff_ci_high],
                    "diff_basis": ic.diff_basis, "status": ic.status, "recommended_action": ic.recommended_action,
                    "warnings": ic.warnings})
    return {"run_id": r.id, "items": out, "total": total, "page": page, "page_size": page_size}


@router.get("/families")
def families(run_id: int | None = None, section: str | None = None, user: User = Depends(require("calibration.read")),
             db: Session = Depends(get_db)):
    """Per source item: variant family, target, observed estimates, differences and decisions."""
    r = _latest(db, user.org_id, run_id)
    cal = {ic.question_id: ic for ic in db.scalars(select(ItemCalibration).where(ItemCalibration.run_id == r.id)).all()}
    srcs = db.scalars(select(Question).where(Question.org_id == user.org_id, Question.is_source.is_(True))).all()
    out = []
    for s in srcs:
        if section and s.section.code != section:
            continue
        members = db.scalars(select(Question).where(Question.family_id == s.family_id, Question.id != s.id,
                                                    Question.status.in_(("approved", "pending_review", "quarantined")))).all()
        sc = cal.get(s.id)
        if not sc and not any(m.id in cal for m in members):
            continue
        out.append({"family_code": s.family.code, "concept": s.family.concept, "section": s.section.code,
                    "source": {"id": s.id, "code": s.code, "target": s.difficulty_target, "n": sc.n_valid if sc else 0,
                               "p": sc.p_value if sc else None, "b": sc.rasch_b if sc else None, "se": sc.rasch_se if sc else None},
                    "variants": [{"id": m.id, "code": m.code, "status": m.status, "n": cal[m.id].n_valid if m.id in cal else 0,
                                  "p": cal[m.id].p_value if m.id in cal else None, "b": cal[m.id].rasch_b if m.id in cal else None,
                                  "diff": cal[m.id].diff_from_reference if m.id in cal else None,
                                  "diff_ci": [cal[m.id].diff_ci_low, cal[m.id].diff_ci_high] if m.id in cal else None,
                                  "basis": cal[m.id].diff_basis if m.id in cal else None,
                                  "calibration_status": cal[m.id].status if m.id in cal else "pending_calibration",
                                  "recommended_action": cal[m.id].recommended_action if m.id in cal else
                                  "No response data yet: pilot this variant before operational use."} for m in members]})
    out.sort(key=lambda f: f["family_code"])
    return {"run_id": r.id, "tolerance_logits": (r.params or {}).get("tolerance_logits"), "families": out}


@router.post("/import")
async def import_responses(file: UploadFile = File(...), preview: bool = Form(True), label: str = Form("uploaded response log"),
                           user: User = Depends(require("calibration.run")), db: Session = Depends(get_db)):
    raw, name = await read_upload(file)
    df = read_table(raw, name)
    codes = set(db.scalars(select(Question.code).where(Question.org_id == user.org_id)).all())
    report = validate_response_frame(df, codes)
    if preview or report["errors"]:
        return {"preview": True, "file_name": name, "report": report,
                "sample": df.head(5).to_dict("records") if not df.empty else []}
    out = import_response_log(db, user.org_id, user, df, label[:120], is_synthetic=False)
    db.commit()
    return {"preview": False, "file_name": name, "report": out}
