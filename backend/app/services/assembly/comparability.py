"""Advisory form-comparability summary (never a publishing gate, never a claim of equivalence).

Matching easy/medium/hard *counts* does not make two forms psychometrically equivalent: bands are coarse and may be a
priori labels. When calibrated Rasch difficulties exist, this module reports, per form, the mean difficulty of the
calibrated items with its standard error, how much of the form is calibrated, and the worst pairwise difference between
forms with a 90% interval judged against the configured equivalence margin (the same TOST-style rule used for variants).

What it does NOT establish: equal test information or reliability across the ability range, content equivalence,
differential item functioning, or anything about uncalibrated items. Standard errors assume independent item estimation
errors (items share calibration persons, so true uncertainty may be somewhat larger). Pure functions; deterministic.
"""
from __future__ import annotations

import math

Z90 = 1.6449
MIN_COVERAGE = 0.8  # share of a form's items that must carry a calibrated difficulty before forms are compared


def form_difficulty(items: list[tuple[float, float | None] | None]) -> dict:
    """items: one (rasch_b, rasch_se) per form item, or None when the item has no usable calibration."""
    cal = [it for it in items if it is not None and it[1] is not None and it[1] > 0]
    n, k = len(items), len(cal)
    out = {"n_items": n, "n_calibrated": k, "coverage": round(k / n, 3) if n else 0.0}
    if k == 0:
        return {**out, "mean_b": None, "se_mean_b": None}
    mean = sum(b for b, _ in cal) / k
    se = math.sqrt(sum(s * s for _, s in cal)) / k
    return {**out, "mean_b": round(mean, 3), "se_mean_b": round(se, 3)}


def compare_forms(forms: dict[str, dict], margin: float, decide) -> dict:
    """forms: code -> form_difficulty(...). `decide(lo, hi, margin)` is the shared equivalence rule."""
    low = sorted(c for c, f in forms.items() if f["mean_b"] is None or f["coverage"] < MIN_COVERAGE)
    base = {"margin_logits": margin, "min_coverage": MIN_COVERAGE, "forms": forms,
            "caveat": "Mean calibrated difficulty only. This does not establish equal information, reliability, content "
                      "balance or fairness, and says nothing about uncalibrated items."}
    if len(forms) < 2:
        return {**base, "status": "not_applicable", "message": "Fewer than two forms to compare."}
    if low:
        return {**base, "status": "insufficient_calibration", "uncalibrated_forms": low,
                "message": f"{len(low)} form(s) have under {int(MIN_COVERAGE * 100)}% calibrated items; no comparison is made. "
                           "Run calibration on response data before relying on form comparability."}
    codes = sorted(forms)
    worst = None
    for i, a in enumerate(codes):
        for b in codes[i + 1:]:
            d = forms[a]["mean_b"] - forms[b]["mean_b"]
            se = math.sqrt(forms[a]["se_mean_b"] ** 2 + forms[b]["se_mean_b"] ** 2)
            if worst is None or abs(d) > abs(worst["diff"]):
                worst = {"forms": [a, b], "diff": round(d, 3), "se": round(se, 3),
                         "ci90": [round(d - Z90 * se, 3), round(d + Z90 * se, 3)]}
    decision = decide(worst["ci90"][0], worst["ci90"][1], margin)
    msg = {"within_tolerance": "The largest pairwise difference in mean difficulty is within the configured margin "
                               "(90% interval). This is evidence about mean difficulty only, not equivalence of the forms.",
           "outside_tolerance": "The largest pairwise difference in mean difficulty exceeds the configured margin.",
           "requires_review": "The interval for the largest pairwise difference overlaps the margin: inconclusive."}[decision]
    status = {"within_tolerance": "within_configured_margin", "outside_tolerance": "exceeds_configured_margin",
              "requires_review": "inconclusive"}[decision]
    return {**base, "status": status, "largest_pairwise_difference": worst, "message": msg}
