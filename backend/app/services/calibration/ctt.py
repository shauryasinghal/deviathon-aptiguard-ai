"""Classical Test Theory statistics for dichotomously scored items.

Input frame columns: person (attempt id), item (question id), score (1/0, NaN = omitted), rt_ms.
Observed statistics only — no model assumptions.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd


def wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float | None, float | None]:
    if n <= 0:
        return None, None
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def item_statistics(df: pd.DataFrame) -> pd.DataFrame:
    """Per-item n, p-value with Wilson CI, missing rate, corrected item–rest correlation, median RT."""
    if df.empty:
        return pd.DataFrame(columns=["item", "n_presented", "n_valid", "n_correct", "p", "p_lo", "p_hi",
                                     "missing_rate", "item_rest_r", "median_rt_ms"])
    d = df.copy()
    d["scored"] = d["score"].fillna(0.0)  # omitted counts as incorrect for total score
    person_total = d.groupby("person")["scored"].agg(["sum", "count"])
    d = d.join(person_total, on="person")
    # rest score as proportion so persons on forms of different length are comparable
    d["rest"] = (d["sum"] - d["scored"]) / (d["count"] - 1).clip(lower=1)
    rows = []
    for item, g in d.groupby("item", sort=True):
        valid = g["score"].notna()
        n_pres, n_valid = len(g), int(valid.sum())
        k = int(g.loc[valid, "score"].sum())
        lo, hi = wilson_ci(k, n_valid)
        r = None
        if n_pres >= 20 and g["scored"].std() > 0 and g["rest"].std() > 0:
            r = float(np.corrcoef(g["scored"], g["rest"])[0, 1])
        rt = g.loc[valid, "rt_ms"].dropna()
        rows.append({
            "item": item, "n_presented": n_pres, "n_valid": n_valid, "n_correct": k,
            "p": k / n_valid if n_valid else None, "p_lo": lo, "p_hi": hi,
            "missing_rate": 1 - n_valid / n_pres if n_pres else None, "item_rest_r": r,
            "median_rt_ms": float(rt.median()) if len(rt) else None,
        })
    return pd.DataFrame(rows)


def person_scores(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d["scored"] = d["score"].fillna(0.0)
    return d.groupby("person")["scored"].agg(raw="sum", n="count").assign(pct=lambda x: x.raw / x.n)
