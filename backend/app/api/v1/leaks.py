from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.v1.serializers import alert_summary, question_summary, user_label
from app.api.v1.uploads import read_upload
from app.core.deps import require
from app.core.errors import NotFound
from app.db.session import get_db
from app.models import Investigation, LeakAlert, LeakDataset, LeakDetectionRun, LeakRecord, Question, Section, User
from app.services.leakage.importer import import_dataset, preview
from app.services.leakage.service import EVIDENCE_LABELS, run_detection, transition_alert

router = APIRouter(prefix="/leaks", tags=["leak detection"])


class ActionIn(BaseModel):
    action: Literal["acknowledge", "investigate", "confirm", "dismiss", "reopen", "comment"]
    note: str | None = Field(default=None, max_length=1000)


class DetectIn(BaseModel):
    replay: bool = True


@router.get("/datasets")
def datasets(user: User = Depends(require("leaks.read")), db: Session = Depends(get_db)):
    rows = db.scalars(select(LeakDataset).where(LeakDataset.org_id == user.org_id).order_by(LeakDataset.id.desc())).all()
    return [{"id": d.id, "name": d.name, "source_type": d.source_type, "description": d.description, "file_name": d.file_name,
             "sha256": d.file_sha256, "imported_at": d.imported_at, "imported_by": user_label(db, d.imported_by),
             "n_records": d.n_records, "n_rejected": d.n_rejected, "n_duplicates": d.n_duplicates,
             "column_mapping": d.column_mapping, "is_synthetic": d.is_synthetic} for d in rows]


@router.post("/datasets/preview")
async def preview_dataset(file: UploadFile = File(...), user: User = Depends(require("leaks.import"))):
    raw, name = await read_upload(file)
    return preview(raw, name)


@router.post("/datasets", status_code=201)
async def upload_dataset(file: UploadFile = File(...), name: str = Form(..., min_length=3, max_length=160),
                         description: str = Form("", max_length=500),
                         source_type: Literal["authorized_export", "synthetic_demo"] = Form("authorized_export"),
                         user: User = Depends(require("leaks.import")), db: Session = Depends(get_db)):
    raw, fname = await read_upload(file)
    ds = import_dataset(db, user.org_id, user, raw, fname, name, source_type, description,
                        is_synthetic=source_type == "synthetic_demo")
    db.commit()
    return {"id": ds.id, "n_records": ds.n_records, "n_rejected": ds.n_rejected, "n_duplicates": ds.n_duplicates}


@router.get("/datasets/{ds_id}/records")
def records(ds_id: int, q: str | None = None, page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100),
            user: User = Depends(require("leaks.read")), db: Session = Depends(get_db)):
    ds = db.get(LeakDataset, ds_id)
    if not ds or ds.org_id != user.org_id:
        raise NotFound("Dataset not found")
    stmt = select(LeakRecord).where(LeakRecord.dataset_id == ds_id)
    if q:
        stmt = stmt.where(LeakRecord.text.ilike(f"%{q}%"))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(LeakRecord.posted_at).offset((page - 1) * page_size).limit(page_size)).all()
    return {"total": total, "items": [{"id": r.id, "external_id": r.external_id, "channel": r.channel, "channel_type": r.channel_type,
                                       "posted_at": r.posted_at, "text": r.text} for r in rows]}


@router.post("/detect")
def detect(body: DetectIn, user: User = Depends(require("leaks.manage")), db: Session = Depends(get_db)):
    run = run_detection(db, user.org_id, user, replay=body.replay)
    db.commit()
    return {"run_id": run.id, "duration_ms": run.duration_ms, "summary": run.summary, "params": run.params}


@router.get("/runs")
def runs(user: User = Depends(require("leaks.read")), db: Session = Depends(get_db)):
    rows = db.scalars(select(LeakDetectionRun).where(LeakDetectionRun.org_id == user.org_id)
                      .order_by(LeakDetectionRun.id.desc()).limit(20)).all()
    return [{"id": r.id, "created_at": r.created_at, "duration_ms": r.duration_ms, "summary": r.summary,
             "created_by": user_label(db, r.created_by)} for r in rows]


@router.get("/alerts")
def alerts(severity: str | None = None, status: str | None = None, evidence_class: str | None = None,
           section: str | None = None, q: str | None = None, user: User = Depends(require("leaks.read")),
           db: Session = Depends(get_db)):
    stmt = select(LeakAlert, Question).join(Question, Question.id == LeakAlert.question_id).where(LeakAlert.org_id == user.org_id)
    if severity:
        stmt = stmt.where(LeakAlert.severity.in_(severity.split(",")))
    if status:
        stmt = stmt.where(LeakAlert.status.in_(status.split(",")))
    if evidence_class:
        stmt = stmt.where(LeakAlert.evidence_class.in_(evidence_class.split(",")))
    if section:
        stmt = stmt.join(Section, Section.id == Question.section_id).where(Section.code == section)
    if q:
        stmt = stmt.where(Question.code.ilike(f"%{q}%") | LeakAlert.code.ilike(f"%{q}%"))
    rows = db.execute(stmt).all()
    rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    rows.sort(key=lambda t: (rank[t[0].severity], -t[0].score))
    all_rows = db.execute(select(LeakAlert.severity, LeakAlert.status, func.count()).where(LeakAlert.org_id == user.org_id)
                          .group_by(LeakAlert.severity, LeakAlert.status)).all()
    return {"items": [alert_summary(a, qq) for a, qq in rows], "total": len(rows),
            "counts": [{"severity": s, "status": st, "n": n} for s, st, n in all_rows], "evidence_labels": EVIDENCE_LABELS}


@router.get("/alerts/{alert_id}")
def alert_detail(alert_id: int, user: User = Depends(require("leaks.read")), db: Session = Depends(get_db)):
    a = db.get(LeakAlert, alert_id)
    if not a or a.org_id != user.org_id:
        raise NotFound("Alert not found")
    q = db.get(Question, a.question_id)
    inv = db.scalar(select(Investigation).where(Investigation.alert_id == a.id))
    fam = db.scalars(select(Question).where(Question.family_id == a.family_id).order_by(Question.code)).all()
    d = alert_summary(a, q)
    d.update({"explanation": a.explanation, "baseline": a.baseline, "observed": a.observed, "evidence": a.evidence,
              "reviewer": user_label(db, a.reviewer_id), "reviewer_decision": a.reviewer_decision, "decided_at": a.decided_at,
              "question": question_summary(q), "family": [question_summary(m) for m in fam],
              "evidence_label": EVIDENCE_LABELS.get(a.evidence_class),
              "investigation": None if not inv else {
                  "status": inv.status, "opened_at": inv.opened_at, "closed_at": inv.closed_at, "resolution": inv.resolution,
                  "assignee": user_label(db, inv.assignee_id),
                  "events": [{"action": e.action, "from": e.from_status, "to": e.to_status, "note": e.note, "by": e.actor_label,
                              "at": e.created_at} for e in inv.events]}})
    return d


@router.post("/alerts/{alert_id}/actions")
def alert_action(alert_id: int, body: ActionIn, user: User = Depends(require("leaks.manage")), db: Session = Depends(get_db)):
    a = db.get(LeakAlert, alert_id)
    if not a or a.org_id != user.org_id:
        raise NotFound("Alert not found")
    transition_alert(db, a, body.action, user, body.note)
    db.commit()
    return alert_detail(alert_id, user, db)
