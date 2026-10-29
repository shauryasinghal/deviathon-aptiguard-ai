"""Report builders. Every report carries provenance, generation timestamp and evidence warnings."""
from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import APP_VERSION
from app.models import (
    AssemblyRun,
    CalibrationRun,
    Investigation,
    ItemCalibration,
    LeakAlert,
    LeakDataset,
    Question,
    ReviewDecision,
    Section,
    User,
    ValidationResult,
)
from app.services.exposure.service import exposure_stats, leaked_families, risk_score
from app.services.policies import get_policy


@dataclass
class Report:
    id: str
    title: str
    columns: list[str]
    rows: list[list]
    warnings: list[str] = field(default_factory=list)
    provenance: list[str] = field(default_factory=list)
    filters: dict = field(default_factory=dict)
    generated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))


TEMPLATES = {
    "question_bank": ("Question-bank inventory", "Every item with section, family, status, validation and leak status."),
    "review_status": ("Variant review status", "Generated variants, reviewer decisions, approver and timestamps."),
    "calibration": ("Item calibration", "CTT and Rasch statistics, CIs, differences from source and calibration decisions."),
    "slot_comparison": ("Slot comparisons", "Per-slot candidate counts, mean scores and ability estimates."),
    "exposure": ("Exposure history", "Exposure counts, audience, recency and explained risk score per item."),
    "form_overlap": ("Test-form overlap", "Pairwise shared items, smaller-form % and Jaccard for the latest assembly."),
    "leak_investigations": ("Leak investigations", "Alerts, evidence class, signals, investigation status and decisions."),
    "validation_results": ("Validation results", "Automated quality-gate results for every item."),
}


def _sec_filter(stmt, section):
    return stmt.join(Section, Section.id == Question.section_id).where(Section.code == section) if section else stmt


def _provenance(db: Session, org_id: int) -> list[str]:
    p = []
    syn = db.scalar(select(func.count()).select_from(Question).where(Question.org_id == org_id, Question.is_synthetic.is_(True)))
    if syn:
        p.append(f"{syn} question(s) are SYNTHETIC demo items (deterministic seed 107); results are not real-world evidence.")
    cal = db.scalar(select(CalibrationRun).where(CalibrationRun.org_id == org_id).order_by(CalibrationRun.id.desc()))
    if cal:
        p.append(f"Latest calibration run #{cal.id} ({cal.method}) on: {cal.data_source}")
    for d in db.scalars(select(LeakDataset).where(LeakDataset.org_id == org_id)).all():
        p.append(f"Leak dataset '{d.name}' ({d.source_type}, sha256 {d.file_sha256[:12]}…, {d.n_records} records)")
    p.append(f"AptiGuard AI v{APP_VERSION}")
    return p


def build(db: Session, org_id: int, kind: str, section: str | None = None, slot: int | None = None,
          severity: str | None = None, status: str | None = None, date_from: datetime | None = None,
          date_to: datetime | None = None) -> Report:
    if kind not in TEMPLATES:
        raise KeyError(kind)
    title = TEMPLATES[kind][0]
    filters = {k: v for k, v in dict(section=section, slot=slot, severity=severity, status=status,
                                     date_from=date_from.isoformat() if date_from else None,
                                     date_to=date_to.isoformat() if date_to else None).items() if v}
    rep = Report(kind, title, [], [], filters=filters, provenance=_provenance(db, org_id))

    if kind == "question_bank":
        stmt = _sec_filter(select(Question).where(Question.org_id == org_id), section)
        if status:
            stmt = stmt.where(Question.status.in_(status.split(",")))
        if date_from:
            stmt = stmt.where(Question.created_at >= date_from)
        if date_to:
            stmt = stmt.where(Question.created_at <= date_to)
        rep.columns = ["code", "section", "family", "is_source", "skill", "difficulty_target", "status", "validation",
                       "leak_status", "generation_method", "version", "synthetic", "created_at", "approved_at"]
        for q in db.scalars(stmt.order_by(Question.code)).all():
            rep.rows.append([q.code, q.section.code, q.family.code, q.is_source, q.skill, q.difficulty_target, q.status,
                             q.validation_status, q.leak_status, q.generation_method, q.version, q.is_synthetic,
                             q.created_at, q.approved_at])

    elif kind == "review_status":
        stmt = _sec_filter(select(Question).where(Question.org_id == org_id, Question.is_source.is_(False)), section)
        if status:
            stmt = stmt.where(Question.status.in_(status.split(",")))
        rep.columns = ["code", "section", "source", "generation_method", "status", "validation", "status_reason",
                       "last_decision", "decided_by", "decided_at", "approved_at"]
        for q in db.scalars(stmt.order_by(Question.code)).all():
            d = db.scalar(select(ReviewDecision).where(ReviewDecision.question_id == q.id).order_by(ReviewDecision.id.desc()))
            who = db.get(User, d.reviewer_id).full_name if d else None
            src = db.get(Question, q.parent_id).code if q.parent_id else None
            rep.rows.append([q.code, q.section.code, src, q.generation_method, q.status, q.validation_status, q.status_reason,
                             d.decision if d else None, who, d.created_at if d else None, q.approved_at])

    elif kind == "calibration":
        run = db.scalar(select(CalibrationRun).where(CalibrationRun.org_id == org_id).order_by(CalibrationRun.id.desc()))
        if not run:
            rep.warnings.append("No calibration run available.")
        else:
            rep.warnings += list(run.warnings or [])
            rep.warnings.append("Raw p-value differences between slots/variants are confounded by group ability; "
                                "use Rasch-based differences where available.")
            stmt = _sec_filter(select(ItemCalibration, Question).join(Question, Question.id == ItemCalibration.question_id)
                               .where(ItemCalibration.run_id == run.id), section)
            if status:
                stmt = stmt.where(ItemCalibration.status.in_(status.split(",")))
            rep.columns = ["code", "section", "reference", "target", "n_valid", "p", "p_ci_low", "p_ci_high", "missing_rate",
                           "item_rest_r", "rasch_b", "rasch_se", "outfit", "diff_from_reference", "diff_ci_low", "diff_ci_high",
                           "basis", "status", "recommended_action", "warnings"]
            for ic, q in db.execute(stmt.order_by(Question.code)).all():
                ref = db.get(Question, ic.reference_question_id).code if ic.reference_question_id else None
                rep.rows.append([q.code, q.section.code, ref, q.difficulty_target, ic.n_valid, ic.p_value, ic.p_ci_low,
                                 ic.p_ci_high, ic.missing_rate, ic.item_rest_r, ic.rasch_b, ic.rasch_se, ic.outfit_msq,
                                 ic.diff_from_reference, ic.diff_ci_low, ic.diff_ci_high, ic.diff_basis, ic.status,
                                 ic.recommended_action, "; ".join(ic.warnings or [])])
            small = sum(1 for r in rep.rows if r[4] is not None and r[4] < (run.params or {}).get("min_responses", 60))
            if small:
                rep.warnings.append(f"{small} item(s) below the minimum sample size; their estimates are unreliable.")

    elif kind == "slot_comparison":
        run = db.scalar(select(CalibrationRun).where(CalibrationRun.org_id == org_id).order_by(CalibrationRun.id.desc()))
        rep.columns = ["drive", "slot", "n_candidates", "mean_pct", "sd_pct", "mean_theta", "theta_se"]
        for s in (run.summary or {}).get("slots", []) if run else []:
            if slot and s["slot_sequence"] != slot:
                continue
            rep.rows.append([s["drive"], s["slot_sequence"], s["n_candidates"], s["mean_pct"], s.get("sd_pct"),
                             s.get("mean_theta"), s.get("theta_se")])
        rep.warnings.append("Mean raw scores differ between slots partly because cohorts differ in ability; leaked items "
                            "also inflate later-slot scores. Compare ability estimates, not raw percentages.")

    elif kind == "exposure":
        pol = get_policy(db, org_id, "exposure")
        stats = exposure_stats(db, org_id)
        fams = leaked_families(db, org_id)
        stmt = _sec_filter(select(Question).where(Question.org_id == org_id, Question.status != "archived"), section)
        rep.columns = ["code", "section", "status", "leak_status", "slots_used", "candidate_exposures", "responses",
                       "last_used_at", "risk_score", "risk_level", "over_limit", "risk_explanation", "slots"]
        for q in db.scalars(stmt.order_by(Question.code)).all():
            s = stats.get(q.id)
            r = risk_score(s, q, pol, q.family_id in fams)
            if severity and r["level"] not in severity.split(","):
                continue
            rep.rows.append([q.code, q.section.code, q.status, q.leak_status, s.slot_count if s else 0,
                             s.candidate_exposures if s else 0, s.response_count if s else 0, s.last_used_at if s else None,
                             r["score"], r["level"], r["over_limit"],
                             "; ".join(f"{c['factor']} +{c['points']} ({c['detail']})" for c in r["components"]),
                             " ".join(s.slots) if s else ""])
        rep.filters["policy"] = pol

    elif kind == "form_overlap":
        run = db.scalar(select(AssemblyRun).where(AssemblyRun.org_id == org_id, AssemblyRun.status == "succeeded")
                        .order_by(AssemblyRun.id.desc()))
        if not run:
            rep.warnings.append("No successful assembly run.")
        else:
            rep.filters["assembly_run"] = run.id
            rep.filters["max_adjacent_overlap_pct"] = run.config.get("max_adjacent_overlap_pct")
            rep.columns = ["form_a", "form_b", "slot_a", "slot_b", "adjacent", "shared_items", "smaller_form_pct", "jaccard",
                           "constraint_ok"]
            for o in run.overlap:
                rep.rows.append([o["form_a"], o["form_b"], o["slot_a"], o["slot_b"], o["adjacent"], o["shared"],
                                 o["smaller_form_pct"], o["jaccard"], o["constraint_ok"]])

    elif kind == "leak_investigations":
        stmt = select(LeakAlert, Question).join(Question, Question.id == LeakAlert.question_id).where(LeakAlert.org_id == org_id)
        stmt = _sec_filter(stmt, section)
        if severity:
            stmt = stmt.where(LeakAlert.severity.in_(severity.split(",")))
        if status:
            stmt = stmt.where(LeakAlert.status.in_(status.split(",")))
        rep.columns = ["alert", "item", "section", "severity", "score", "evidence_class", "alert_type", "status",
                       "first_detectable_slot", "signals", "recommended_action", "reviewer_decision", "decided_at",
                       "investigation_resolution"]
        for a, q in db.execute(stmt.order_by(LeakAlert.code)).all():
            inv = db.scalar(select(Investigation).where(Investigation.alert_id == a.id))
            rep.rows.append([a.code, q.code, q.section.code, a.severity, a.score, a.evidence_class, a.alert_type, a.status,
                             a.first_detectable_slot, " | ".join(s["summary"] for s in a.signals), a.recommended_action,
                             a.reviewer_decision, a.decided_at, inv.resolution if inv else None])
        rep.warnings.append("Text similarity and statistical signals are evidence, not proof of misconduct. Only the "
                            "supplied datasets were searched; no live internet or messaging platform was monitored.")

    elif kind == "validation_results":
        stmt = select(ValidationResult, Question).join(Question, Question.id == ValidationResult.question_id).where(Question.org_id == org_id)
        stmt = _sec_filter(stmt, section)
        if status:
            stmt = stmt.where(ValidationResult.status.in_(status.split(",")))
        rep.columns = ["code", "section", "item_status", "check", "result", "severity", "message", "run_at"]
        for v, q in db.execute(stmt.order_by(Question.code, ValidationResult.id)).all():
            rep.rows.append([q.code, q.section.code, q.status, v.check, v.status, v.severity, v.message, v.run_at])
        rep.warnings.append("Verbal items cannot be machine-proven correct; 'warn' results there indicate mandatory human review.")
    return rep


# ------------------------------------------------------------------ renderers
_DANGEROUS = ("=", "+", "-", "@", "\t", "\r")


def safe_cell(v) -> str:
    """Neutralize spreadsheet formula injection (CSV injection)."""
    if v is None:
        return ""
    if isinstance(v, datetime):
        return v.isoformat(timespec="seconds")
    if isinstance(v, float):
        return f"{v:.4f}".rstrip("0").rstrip(".") if v == v else ""
    s = str(v)
    if s and s[0] in _DANGEROUS and not _is_number(s):
        return "'" + s
    return s


def _is_number(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False


def to_csv(rep: Report) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([f"# {rep.title}"])
    w.writerow([f"# generated_at {rep.generated_at}"])
    for k, v in rep.filters.items():
        w.writerow([safe_cell(f"# filter {k}: {v}")])
    for p in rep.provenance:
        w.writerow([safe_cell(f"# provenance: {p}")])
    for wn in rep.warnings:
        w.writerow([safe_cell(f"# warning: {wn}")])
    w.writerow(rep.columns)
    for r in rep.rows:
        w.writerow([safe_cell(c) for c in r])
    return buf.getvalue()


def to_json(rep: Report) -> str:
    return json.dumps({"report": rep.id, "title": rep.title, "generated_at": rep.generated_at, "filters": rep.filters,
                       "provenance": rep.provenance, "warnings": rep.warnings, "columns": rep.columns,
                       "rows": [dict(zip(rep.columns, r)) for r in rep.rows]}, default=str, indent=1)


def to_pdf(rep: Report, max_rows: int = 400) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=12 * mm, rightMargin=12 * mm, topMargin=12 * mm,
                            bottomMargin=12 * mm, title=rep.title, author="AptiGuard AI")
    ss = getSampleStyleSheet()
    small = ss["BodyText"].clone("small", fontSize=7, leading=9)
    story = [Paragraph(f"AptiGuard AI — {rep.title}", ss["Title"]),
             Paragraph(f"Generated {rep.generated_at} UTC · {len(rep.rows)} row(s)", ss["Normal"]), Spacer(1, 4)]
    for p in rep.provenance:
        story.append(Paragraph(f"<b>Provenance:</b> {_esc(p)}", small))
    for wn in rep.warnings:
        story.append(Paragraph(f"<font color='#B45309'><b>Warning:</b> {_esc(wn)}</font>", small))
    if rep.filters:
        story.append(Paragraph("<b>Filters:</b> " + _esc(", ".join(f"{k}={v}" for k, v in rep.filters.items() if k != "policy")), small))
    story.append(Spacer(1, 6))
    cols = rep.columns[:12]
    data = [[Paragraph(f"<b>{_esc(c)}</b>", small) for c in cols]]
    for r in rep.rows[:max_rows]:
        data.append([Paragraph(_esc(safe_cell(c))[:160], small) for c in r[:12]])
    if data and cols:
        t = Table(data, repeatRows=1)
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1E1B4B")),
                               ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                               ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#CBD5E1")),
                               ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F1F5F9")]),
                               ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        story.append(t)
    if len(rep.rows) > max_rows or len(rep.columns) > 12:
        story.append(Spacer(1, 4))
        story.append(Paragraph(f"PDF shows the first {min(max_rows, len(rep.rows))} rows and 12 columns; download CSV/JSON "
                               "for the complete report.", small))
    doc.build(story)
    return buf.getvalue()


def _esc(s: str) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
