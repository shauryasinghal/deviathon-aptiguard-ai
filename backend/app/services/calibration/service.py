"""Calibration pipeline: CTT for every item with data, Rasch MML when the design and sample allow it,
variant-vs-source equivalence decisions with explicit uncertainty, and slot comparisons."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Attempt, CalibrationRun, ItemCalibration, Question, Response, Slot, User
from app.services import audit
from app.services.calibration.ctt import item_statistics, newcombe_diff_ci, person_scores
from app.services.calibration.rasch import RaschNotIdentified, fit_rasch
from app.services.policies import get_policy

Z90 = 1.6449
STATUS_LABELS = {
    "insufficient_data": "Insufficient data",
    "pending_calibration": "Pending calibration",
    "within_tolerance": "Within configured tolerance",
    "outside_tolerance": "Outside configured tolerance",
    "requires_review": "Requires human review",
    "calibrated_reference": "Calibrated (reference item)",
}


def load_response_frame(db: Session, org_id: int) -> pd.DataFrame:
    q = (
        select(Response.attempt_id, Response.question_id, Response.is_correct, Response.selected_key,
               Response.response_time_ms, Attempt.slot_id, Attempt.form_id, Slot.sequence, Slot.drive)
        .join(Attempt, Attempt.id == Response.attempt_id)
        .join(Slot, Slot.id == Attempt.slot_id)
        .where(Attempt.status == "submitted", Slot.org_id == org_id)
    )
    rows = db.execute(q).all()
    df = pd.DataFrame(rows, columns=["person", "item", "is_correct", "selected", "rt_ms", "slot_id", "form_id",
                                     "slot_seq", "drive"])
    if df.empty:
        return df.assign(score=pd.Series(dtype=float))
    df["score"] = np.where(df["selected"].isna(), np.nan, df["is_correct"].astype(float))
    return df


def equivalence_decision(lo: float, hi: float, margin: float) -> str:
    """Two one-sided tests via the 90% CI: equivalent only if the whole CI lies inside ±margin;
    non-equivalent only if the whole CI lies outside; otherwise inconclusive (human review)."""
    if -margin <= lo and hi <= margin:
        return "within_tolerance"
    if lo > margin or hi < -margin:
        return "outside_tolerance"
    return "requires_review"


def _band(b: float, cutoffs: list[float]) -> str:
    return "easy" if b < cutoffs[0] else ("hard" if b > cutoffs[1] else "medium")


def run_calibration(db: Session, org_id: int, user: User | None, overrides: dict | None = None,
                    data_source: str = "response logs (database)") -> CalibrationRun:
    pol = {**get_policy(db, org_id, "calibration"), **(overrides or {})}
    df = load_response_frame(db, org_id)
    warnings: list[str] = []
    run = CalibrationRun(org_id=org_id, created_by=user.id if user else None, method="CTT", data_source=data_source,
                         params=pol, n_responses=len(df), n_items=int(df["item"].nunique()) if len(df) else 0,
                         n_persons=int(df["person"].nunique()) if len(df) else 0, status="completed")
    db.add(run)
    db.flush()
    if df.empty:
        run.status = "no_data"
        run.warnings = ["No submitted responses available; nothing to calibrate."]
        return run

    stats = item_statistics(df).set_index("item")
    questions = {q.id: q for q in db.scalars(select(Question).where(Question.id.in_(stats.index.tolist()))).all()}

    # ---------------- Rasch, only on items meeting the sample-size floor, only if linked
    rasch_b: dict[int, tuple[float, float, float]] = {}
    theta_by_person: dict[int, float] = {}
    eligible = stats.index[stats["n_valid"] >= pol["min_responses_rasch"]].tolist()
    leaked = [i for i in eligible if questions.get(int(i)) is not None and questions[int(i)].leak_status in ("suspected", "confirmed")]
    if leaked and pol.get("exclude_leaked_from_rasch", True):
        eligible = [i for i in eligible if i not in set(leaked)]
        warnings.append(f"{len(leaked)} item(s) with suspected/confirmed leaks excluded from the Rasch fit so that "
                        "contaminated responses do not distort the linking (they are reported with CTT only).")
    sub = df[df["item"].isin(eligible) & df["score"].notna()]
    if len(eligible) >= 10 and sub["person"].nunique() >= 200:
        try:
            res = fit_rasch(sub["person"].values, sub["item"].values, sub["score"].values)
            rasch_b = {int(i): (float(b), float(se), float(o)) for i, b, se, o in zip(res.items, res.b, res.se, res.outfit)}
            theta_by_person = {int(p): float(t) for p, t in zip(res.persons, res.theta)}
            run.method = "CTT + Rasch (MML-EM, N(0,1) ability prior)"
            run.rasch_fitted = True
            if not res.converged:
                warnings.append(f"Rasch EM did not converge in {res.iterations} iterations; treat b as provisional.")
            run.summary = {"rasch": {"iterations": res.iterations, "converged": res.converged, "loglik": round(res.loglik, 2),
                                     "n_items": len(res.items), "n_persons": len(res.persons)}}
        except RaschNotIdentified as e:
            warnings.append(f"Rasch not fitted: {e}. Only CTT statistics are reported.")
    else:
        warnings.append(f"Rasch not fitted: needs ≥10 items with ≥{pol['min_responses_rasch']} responses and ≥200 persons.")
    excluded = len(stats) - len(rasch_b)
    if rasch_b and excluded:
        warnings.append(f"{excluded} item(s) below the Rasch sample floor are reported with CTT only.")

    # ---------------- per-item decisions
    tol, tol_p = pol["tolerance_logits"], pol["tolerance_p"]
    status_counts: dict[str, int] = {}
    for item_id, s in stats.iterrows():
        q = questions.get(int(item_id))
        if q is None:
            continue
        w: list[str] = []
        b, se, outfit = rasch_b.get(int(item_id), (None, None, None))
        ref = questions.get(q.parent_id) if q.parent_id else None
        if q.parent_id and ref is None:
            ref = db.get(Question, q.parent_id)
        diff = lo = hi = None
        basis = None
        if s.n_valid < pol["min_responses"]:
            status, action = "insufficient_data", f"Collect at least {pol['min_responses']} responses (pilot) before relying on this item."
            w.append(f"Only {int(s.n_valid)} valid responses; CI is wide.")
        else:
            status, action = "calibrated_reference", "Usable; monitor in live administration."
            if ref is not None and ref.id in stats.index:
                rs = stats.loc[ref.id]
                rb = rasch_b.get(ref.id)
                if b is not None and rb is not None:
                    diff = b - rb[0]
                    dse = math.sqrt(se ** 2 + rb[1] ** 2)
                    lo, hi, basis, margin = diff - Z90 * dse, diff + Z90 * dse, "rasch_logit", tol
                elif rs.n_valid >= pol["min_responses"]:
                    diff = (s.p or 0) - (rs.p or 0)
                    lo, hi = newcombe_diff_ci(int(s.n_correct), int(s.n_valid), int(rs.n_correct), int(rs.n_valid), Z90)
                    basis, margin = "ctt_p_preliminary", tol_p
                    w.append("Preliminary: raw p-value difference is confounded by differences in group ability.")
                if basis:
                    status = equivalence_decision(lo, hi, margin)
                    action = {
                        "within_tolerance": "Equivalent to the source within tolerance (90% CI inside margin, TOST).",
                        "outside_tolerance": "Not parallel: retire as a variant or re-target difficulty; do not mix with source.",
                        "requires_review": "Inconclusive: CI straddles the tolerance margin; collect more data or review.",
                    }[status]
                else:
                    status, action = "insufficient_data", "Reference item lacks data; cannot assess equivalence yet."
            elif q.parent_id:
                status, action = "insufficient_data", "Source item has no response data in this run; equivalence not assessable."
            if s.item_rest_r is not None and s.item_rest_r < pol["min_item_rest_r"]:
                w.append(f"Low discrimination (item–rest r = {s.item_rest_r:.2f}).")
                if status in ("calibrated_reference", "within_tolerance"):
                    status, action = "requires_review", "Low discrimination: check key, ambiguity and distractors."
            if outfit is not None and (outfit > 1.5 or outfit < 0.5):
                w.append(f"Rasch outfit MSQ {outfit:.2f} outside 0.5–1.5 (misfit).")
            if b is not None:
                band = _band(b, pol["band_cutoffs_b"])
                if band != q.difficulty_target:
                    w.append(f"Observed difficulty band '{band}' differs from target '{q.difficulty_target}'.")
        if s.missing_rate and s.missing_rate > 0.1:
            w.append(f"High omission rate ({s.missing_rate:.0%}).")
        if q.leak_status in ("suspected", "confirmed"):
            w.append(f"Leak status '{q.leak_status}': later-slot statistics may be inflated by prior exposure.")
        status_counts[status] = status_counts.get(status, 0) + 1
        db.add(ItemCalibration(
            run_id=run.id, question_id=q.id, n_presented=int(s.n_presented), n_valid=int(s.n_valid),
            n_correct=int(s.n_correct), p_value=_f(s.p), p_ci_low=_f(s.p_lo), p_ci_high=_f(s.p_hi),
            missing_rate=_f(s.missing_rate), item_rest_r=_f(s.item_rest_r), median_rt_ms=_f(s.median_rt_ms),
            rasch_b=b, rasch_se=se, outfit_msq=outfit, reference_question_id=ref.id if ref else None,
            diff_from_reference=diff, diff_ci_low=lo, diff_ci_high=hi, diff_basis=basis,
            status=status, recommended_action=action, warnings=w,
        ))

    run.summary = {**(run.summary or {}), "status_counts": status_counts,
                   "slots": slot_comparison(df, theta_by_person)}
    run.warnings = warnings
    audit.record(db, user, "calibration.run", "calibration_run", run.id,
                 f"Calibrated {len(stats)} items from {run.n_responses} responses ({run.method})")
    return run


def _f(v):
    if v is None:
        return None
    try:
        return None if (isinstance(v, float) and math.isnan(v)) else float(v)
    except (TypeError, ValueError):
        return None


def slot_comparison(df: pd.DataFrame, theta: dict[int, float]) -> list[dict]:
    ps = person_scores(df)
    meta = df.groupby("person")[["slot_seq", "drive", "slot_id"]].first()
    ps = ps.join(meta)
    if theta:
        ps["theta"] = ps.index.map(theta)
    out = []
    for (drive, seq), g in ps.groupby(["drive", "slot_seq"]):
        row = {"drive": drive, "slot_sequence": int(seq), "slot_id": int(g["slot_id"].iloc[0]), "n_candidates": len(g),
               "mean_pct": round(float(g["pct"].mean()) * 100, 2),
               "sd_pct": round(float(g["pct"].std(ddof=1)) * 100, 2) if len(g) > 1 else None}
        if theta and g["theta"].notna().any():
            t = g["theta"].dropna()
            row["mean_theta"] = round(float(t.mean()), 3)
            row["theta_se"] = round(float(t.std(ddof=1) / math.sqrt(len(t))), 3) if len(t) > 1 else None
        out.append(row)
    return out
