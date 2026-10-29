"""Command-center aggregates. Every number is computed from the database at request time."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.deps import require
from app.db.session import get_db
from app.models import (
    AssemblyRun,
    Attempt,
    AuditEvent,
    CalibrationRun,
    ItemCalibration,
    LeakAlert,
    Question,
    Section,
    Slot,
    User,
)
from app.services.exposure.service import exposure_stats, leaked_families, risk_score
from app.services.policies import get_policy

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary")
def summary(section: str | None = None, drive: str | None = None, slot_id: int | None = None,
            date_from: datetime | None = None, date_to: datetime | None = None,
            user: User = Depends(require("dashboard.read")), db: Session = Depends(get_db)):
    org = user.org_id
    qstmt = select(Question).where(Question.org_id == org, Question.status != "archived")
    if section:
        qstmt = qstmt.join(Section, Section.id == Question.section_id).where(Section.code == section)
    qs = db.scalars(qstmt).all()
    qids = {q.id for q in qs}
    by_status: dict[str, int] = {}
    for q in qs:
        by_status[q.status] = by_status.get(q.status, 0) + 1
    pol = get_policy(db, org, "exposure")
    stats = exposure_stats(db, org)
    fams = leaked_families(db, org)
    risks = {q.id: risk_score(stats.get(q.id), q, pol, q.family_id in fams) for q in qs if q.status in ("approved", "quarantined")}
    warnings = sorted([(q, risks[q.id]) for q in qs if q.id in risks and risks[q.id]["warning"]], key=lambda t: -t[1]["score"])

    astmt = select(LeakAlert).where(LeakAlert.org_id == org)
    if date_from:
        astmt = astmt.where(LeakAlert.detected_at >= date_from)
    if date_to:
        astmt = astmt.where(LeakAlert.detected_at <= date_to)
    alerts = [a for a in db.scalars(astmt).all() if a.question_id in qids]
    active = [a for a in alerts if a.status in ("open", "acknowledged", "investigating")]
    rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    top = sorted(active, key=lambda a: (rank[a.severity], -a.score))[:6]
    qmap = {q.id: q for q in qs}

    # slot statistics from submitted attempts
    sstmt = (select(Slot.id, Slot.drive, Slot.sequence, Slot.name, Slot.starts_at, func.count(Attempt.id),
                    func.avg(Attempt.score / Attempt.max_score))
             .join(Attempt, Attempt.slot_id == Slot.id).where(Slot.org_id == org, Attempt.status == "submitted")
             .group_by(Slot.id).order_by(Slot.starts_at))
    if drive:
        sstmt = sstmt.where(Slot.drive == drive)
    if slot_id:
        sstmt = sstmt.where(Slot.id == slot_id)
    if date_from:
        sstmt = sstmt.where(Slot.starts_at >= date_from)
    if date_to:
        sstmt = sstmt.where(Slot.starts_at <= date_to)
    cal = db.scalar(select(CalibrationRun).where(CalibrationRun.org_id == org).order_by(CalibrationRun.id.desc()))
    theta = {(s["drive"], s["slot_sequence"]): s for s in ((cal.summary or {}).get("slots", []) if cal else [])}
    slots = [{"slot_id": sid, "drive": d, "sequence": seq, "name": name, "starts_at": st, "candidates": n,
              "mean_pct": round(float(m) * 100, 1) if m is not None else None,
              "mean_theta": theta.get((d, seq), {}).get("mean_theta"), "theta_se": theta.get((d, seq), {}).get("theta_se")}
             for sid, d, seq, name, st, n, m in db.execute(sstmt).all()]

    diff_dist = {}
    for q in qs:
        if q.status in ("approved", "pending_review"):
            k = (q.section.code, q.difficulty_target)
            diff_dist[k] = diff_dist.get(k, 0) + 1
    observed = {}
    if cal:
        cut = (cal.params or {}).get("band_cutoffs_b", [-0.5, 0.5])
        for b, in db.execute(select(ItemCalibration.rasch_b).where(ItemCalibration.run_id == cal.id,
                                                                    ItemCalibration.rasch_b.is_not(None),
                                                                    ItemCalibration.question_id.in_(qids))).all():
            band = "easy" if b < cut[0] else "hard" if b > cut[1] else "medium"
            observed[band] = observed.get(band, 0) + 1
    cal_counts = {}
    if cal:
        cal_counts = dict(db.execute(select(ItemCalibration.status, func.count()).where(
            ItemCalibration.run_id == cal.id, ItemCalibration.question_id.in_(qids)).group_by(ItemCalibration.status)).all())

    asm = db.scalar(select(AssemblyRun).where(AssemblyRun.org_id == org, AssemblyRun.status == "succeeded")
                    .order_by(AssemblyRun.id.desc()))
    overlap = None
    if asm:
        adj = [o for o in asm.overlap if o["adjacent"]]
        overlap = {"run_id": asm.id, "drive": asm.drive, "forms": len({o["form_a"] for o in asm.overlap} | {o["form_b"] for o in asm.overlap}),
                   "limit_pct": asm.config.get("max_adjacent_overlap_pct"),
                   "max_adjacent_pct": max((o["smaller_form_pct"] for o in adj), default=0),
                   "mean_jaccard": round(sum(o["jaccard"] for o in asm.overlap) / len(asm.overlap), 4) if asm.overlap else 0,
                   "all_ok": all(o["constraint_ok"] for o in adj), "pairs": adj}
    activity = db.scalars(select(AuditEvent).where(AuditEvent.org_id == org).order_by(AuditEvent.id.desc()).limit(12)).all()
    synthetic = sum(1 for q in qs if q.is_synthetic)
    return {
        "filters": {"section": section, "drive": drive, "slot_id": slot_id},
        "data_label": "Synthetic demo data (seed 107)" if synthetic else "Live data",
        "kpis": {
            "total_questions": len(qs), "approved": by_status.get("approved", 0),
            "approved_variants": sum(1 for q in qs if q.status == "approved" and not q.is_source),
            "pending_reviews": by_status.get("pending_review", 0), "quarantined": by_status.get("quarantined", 0),
            "retired": by_status.get("retired", 0), "rejected": by_status.get("rejected", 0),
            "exposure_warnings": len(warnings), "over_limit": sum(1 for _, r in warnings if r["over_limit"]),
            "active_leak_alerts": len(active), "critical_alerts": sum(1 for a in active if a.severity == "critical"),
            "candidates_assessed": sum(s["candidates"] for s in slots),
        },
        "status_breakdown": by_status,
        "exposure": {"levels": {lvl: sum(1 for r in risks.values() if r["level"] == lvl) for lvl in ("low", "elevated", "high")},
                     "top": [{"id": q.id, "code": q.code, "score": r["score"], "level": r["level"],
                              "slots": stats[q.id].slot_count if q.id in stats else 0, "leak_status": q.leak_status}
                             for q, r in warnings[:6]], "policy": pol},
        "alerts": [{"id": a.id, "code": a.code, "severity": a.severity, "status": a.status, "title": a.title,
                    "question_code": qmap[a.question_id].code, "evidence_class": a.evidence_class,
                    "detected_at": a.detected_at, "first_detectable_slot": a.first_detectable_slot} for a in top],
        "alert_counts": {s: sum(1 for a in active if a.severity == s) for s in ("critical", "high", "medium", "low")},
        "slots": slots,
        "difficulty": {"target": [{"section": k[0], "band": k[1], "n": v} for k, v in sorted(diff_dist.items())],
                       "observed_rasch": observed},
        "calibration": {"run_id": cal.id if cal else None, "method": cal.method if cal else None,
                        "created_at": cal.created_at if cal else None, "status_counts": cal_counts},
        "overlap": overlap,
        "activity": [{"id": e.id, "action": e.action, "summary": e.summary, "actor": e.actor_label, "at": e.created_at,
                      "entity_type": e.entity_type, "entity_id": e.entity_id} for e in activity],
        "drives": sorted({s.drive for s in db.scalars(select(Slot).where(Slot.org_id == org)).all()}),
    }
