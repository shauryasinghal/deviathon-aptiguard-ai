"""Statistical leak signals.

1. Mantel–Haenszel DIF across time: reference group = candidates in the item's first `baseline_slots`
   administrations, focal group = later administrations. Stratifying by rest score controls for differences in
   slot ability, so a stronger cohort does not by itself look like a leak. Two-stage purification removes
   flagged items from the matching criterion. Effect size reported on the ETS delta scale (positive = easier later).
2. Response-time speed-up: later/baseline median RT ratio, normalized by the same ratio for all other items
   in those slots; one-sided Mann–Whitney U on log RT.
3. Benjamini–Hochberg FDR control across all tested items.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
from scipy import stats as sps


def bh_adjust(p: list[float]) -> list[float]:
    n = len(p)
    if n == 0:
        return []
    order = np.argsort(p)
    ranked = np.array(p)[order] * n / (np.arange(n) + 1)
    q = np.minimum.accumulate(ranked[::-1])[::-1]
    out = np.empty(n)
    out[order] = np.minimum(q, 1.0)
    return out.tolist()


def mantel_haenszel(ref: pd.DataFrame, foc: pd.DataFrame, n_strata: int = 5) -> dict | None:
    """ref/foc frames with columns score (0/1) and rest (proportion). Returns MH statistics or None."""
    both = pd.concat([ref.assign(g="R"), foc.assign(g="F")])
    if both["rest"].nunique() < 2:
        both["stratum"] = 0
    else:
        both["stratum"] = pd.qcut(both["rest"].rank(method="first"), q=min(n_strata, len(both) // 20 or 1),
                                  labels=False, duplicates="drop")
    num = den = sum_a = sum_ea = sum_var = 0.0
    used = 0
    for _, s in both.groupby("stratum"):
        r, f = s[s.g == "R"], s[s.g == "F"]
        nr, nf = len(r), len(f)
        n = nr + nf
        if nr == 0 or nf == 0 or n < 2:
            continue
        a, b = r.score.sum(), nr - r.score.sum()       # reference correct / incorrect
        c, d = f.score.sum(), nf - f.score.sum()       # focal correct / incorrect
        m1, m0 = a + c, b + d
        num += a * d / n
        den += b * c / n
        sum_a += a
        sum_ea += nr * m1 / n
        sum_var += nr * nf * m1 * m0 / (n * n * (n - 1)) if n > 1 else 0
        used += 1
    if used == 0 or sum_var <= 0:
        return None
    alpha = (num + 0.5) / (den + 0.5)  # small continuity guard against zero cells
    delta = -2.35 * math.log(alpha)    # ETS scale; positive => easier for focal (later) group
    chi2 = (abs(sum_a - sum_ea) - 0.5) ** 2 / sum_var
    p = float(sps.chi2.sf(chi2, 1))
    return {"alpha_mh": round(alpha, 4), "delta": round(delta, 3), "chi2": round(chi2, 3), "p": p, "strata": used}


def ets_class(delta_easier: float, q: float, alpha: float) -> str:
    a = abs(delta_easier)
    if a >= 1.5 and q < alpha:
        return "C"
    if a >= 1.0 and q < alpha:
        return "B"
    return "A"


def rest_scores(df: pd.DataFrame, exclude_items: set[int]) -> pd.Series:
    """Per (person,item) rest proportion, excluding the item itself and purified items."""
    d = df[~df["item"].isin(exclude_items)]
    tot = d.groupby("person")["scored"].agg(["sum", "count"])
    return tot


def drift_tests(df: pd.DataFrame, baseline_slots: int, min_group_n: int, purified: set[int] | None = None,
                max_seq: int | None = None) -> pd.DataFrame:
    """Per-item MH drift + RT tests within each drive. df columns: person,item,scored,score,rt_ms,slot_seq,drive."""
    purified = purified or set()
    if max_seq is not None:
        df = df[df["slot_seq"] <= max_seq]
    rows = []
    for drive, d in df.groupby("drive"):
        tot = rest_scores(d, purified)
        d = d.join(tot, on="person", rsuffix="_t")
        own = (~d["item"].isin(purified)).astype(float) * d["scored"]
        d["rest"] = (d["sum"] - own) / (d["count"] - (~d["item"].isin(purified)).astype(int)).clip(lower=1)
        # slot-level median RT per slot for normalization
        slot_rt = d.groupby("slot_seq")["rt_ms"].median()
        for item, g in d.groupby("item"):
            seqs = sorted(g["slot_seq"].unique())
            if len(seqs) <= baseline_slots:
                continue
            base_seqs = seqs[:baseline_slots]
            ref = g[g["slot_seq"].isin(base_seqs) & g["score"].notna()]
            foc = g[~g["slot_seq"].isin(base_seqs) & g["score"].notna()]
            if len(ref) < min_group_n or len(foc) < min_group_n:
                continue
            mh = mantel_haenszel(ref[["score", "rest"]], foc[["score", "rest"]])
            if mh is None:
                continue
            per_slot = (g[g["score"].notna()].groupby("slot_seq")["score"].agg(["mean", "count"])
                        .reset_index().rename(columns={"mean": "p", "count": "n"}))
            r_rt, f_rt = ref["rt_ms"].dropna(), foc["rt_ms"].dropna()
            rt_ratio = rel_ratio = rt_p = None
            if len(r_rt) >= 20 and len(f_rt) >= 20:
                rt_ratio = float(f_rt.median() / r_rt.median())
                expected = float(slot_rt.loc[[s for s in seqs if s not in base_seqs]].median() /
                                 slot_rt.loc[base_seqs].median())
                rel_ratio = rt_ratio / expected if expected > 0 else rt_ratio
                rt_p = float(sps.mannwhitneyu(np.log(f_rt), np.log(r_rt), alternative="less").pvalue)
            rows.append({
                "drive": drive, "item": int(item), "baseline_slots": [int(s) for s in base_seqs],
                "later_slots": [int(s) for s in seqs if s not in base_seqs],
                "n_ref": len(ref), "n_foc": len(foc), "p_ref": float(ref["score"].mean()), "p_foc": float(foc["score"].mean()),
                "rest_ref": float(ref["rest"].mean()), "rest_foc": float(foc["rest"].mean()),
                "delta": mh["delta"], "alpha_mh": mh["alpha_mh"], "chi2": mh["chi2"], "p_mh": mh["p"],
                "rt_ratio": rt_ratio, "rt_rel_ratio": rel_ratio, "p_rt": rt_p,
                "per_slot": per_slot.to_dict("records"),
                "median_rt_ref": float(r_rt.median()) if len(r_rt) else None,
                "median_rt_foc": float(f_rt.median()) if len(f_rt) else None,
            })
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    # MH test is two-sided; only "easier later" direction is a leak signal
    out["p_mh_dir"] = np.where(out["delta"] > 0, out["p_mh"] / 2, 1 - out["p_mh"] / 2)
    out["q_mh"] = bh_adjust(out["p_mh_dir"].tolist())
    rtp = out["p_rt"].fillna(1.0).tolist()
    out["q_rt"] = bh_adjust(rtp)
    return out


def purified_drift(df: pd.DataFrame, pol: dict, max_seq: int | None = None) -> pd.DataFrame:
    stage1 = drift_tests(df, pol["baseline_slots"], pol["min_group_n"], max_seq=max_seq)
    if stage1.empty:
        return stage1
    flagged = set(stage1.loc[(stage1.q_mh < pol["fdr_alpha"]) & (stage1.delta >= pol["min_effect_delta"]), "item"])
    if not flagged:
        return stage1
    return drift_tests(df, pol["baseline_slots"], pol["min_group_n"], purified=flagged, max_seq=max_seq)
