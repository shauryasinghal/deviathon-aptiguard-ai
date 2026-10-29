"""Statistical functions checked against independently published or independently computed reference values."""
import math

import numpy as np
import pandas as pd
import pytest
from scipy.stats import chi2_contingency

from app.services.calibration.ctt import item_statistics, newcombe_diff_ci, wilson_ci
from app.services.calibration.rasch import fit_rasch
from app.services.calibration.service import equivalence_decision
from app.services.leakage.stats import bh_adjust, mantel_haenszel


def test_wilson_matches_newcombe_1998_table_i():
    # Newcombe RG (1998) Stat Med 17:857-872, Table I: 81/263 -> 0.2553 to 0.3662 (method 3, Wilson score)
    lo, hi = wilson_ci(81, 263)
    assert lo == pytest.approx(0.2553, abs=5e-4) and hi == pytest.approx(0.3662, abs=5e-4)
    # 0/10 -> 0 to 0.2775
    lo, hi = wilson_ci(0, 10)
    assert lo == 0.0 and hi == pytest.approx(0.2775, abs=5e-4)


def test_newcombe_difference_matches_newcombe_1998_table_ii():
    # Newcombe RG (1998) Stat Med 17:873-890, Table II example (a): 56/70 vs 48/80 -> 0.0524 to 0.3339 (method 10)
    lo, hi = newcombe_diff_ci(56, 70, 48, 80, z=1.96)
    assert lo == pytest.approx(0.0524, abs=5e-4) and hi == pytest.approx(0.3339, abs=5e-4)
    # example (h): 10/10 vs 0/10 -> 0.6075 to 1.0000 — a Wald interval would collapse to [1, 1]
    lo, hi = newcombe_diff_ci(10, 10, 0, 10, z=1.96)
    assert lo == pytest.approx(0.6075, abs=5e-4) and hi == pytest.approx(1.0, abs=5e-4)


def test_ceiling_items_are_not_declared_equivalent():
    lo, hi = newcombe_diff_ci(60, 60, 59, 60)  # both near-ceiling with n=60: CI must not be degenerate
    assert hi - lo > 0.04
    assert equivalence_decision(lo, hi, 0.02) == "requires_review"


def test_bh_matches_r_p_adjust():
    # R: p.adjust(c(0.01, 0.04, 0.03, 0.005), "BH") -> 0.02 0.04 0.04 0.02
    assert bh_adjust([0.01, 0.04, 0.03, 0.005]) == pytest.approx([0.02, 0.04, 0.04, 0.02])
    assert bh_adjust([0.5]) == [0.5]
    assert bh_adjust([]) == []


def _two_by_two(a, b, c, d):
    ref = pd.DataFrame({"score": [1] * a + [0] * b, "rest": 0.5})
    foc = pd.DataFrame({"score": [1] * c + [0] * d, "rest": 0.5})
    return ref, foc


def test_mantel_haenszel_single_stratum_reduces_to_odds_ratio_and_corrected_chi2():
    a, b, c, d = 30, 20, 45, 10
    res = mantel_haenszel(*_two_by_two(a, b, c, d))
    assert res["alpha_mh"] == pytest.approx((a * d) / (b * c), rel=1e-3)
    assert res["delta"] == pytest.approx(-2.35 * math.log((a * d) / (b * c)), abs=2e-3)
    n = a + b + c + d
    pearson_cc = chi2_contingency(np.array([[a, b], [c, d]]), correction=True)[0]
    assert res["chi2"] == pytest.approx(pearson_cc * (n - 1) / n, rel=1e-3)


def test_mantel_haenszel_zero_cell_stays_finite():
    res = mantel_haenszel(*_two_by_two(20, 20, 40, 0))
    assert math.isfinite(res["alpha_mh"]) and res["delta"] > 0


def test_item_rest_correlation_matches_manual_computation():
    X = np.array([[1, 1, 0, 1], [0, 1, 0, 0], [1, 1, 1, 1], [0, 0, 0, 1], [1, 0, 1, 1], [1, 1, 1, 0]] * 5, dtype=float)
    rows = [(p, i, X[p, i], 1000.0) for p in range(X.shape[0]) for i in range(X.shape[1])]
    st = item_statistics(pd.DataFrame(rows, columns=["person", "item", "score", "rt_ms"])).set_index("item")
    for i in range(4):
        rest = (X.sum(1) - X[:, i]) / 3
        assert st.loc[i, "item_rest_r"] == pytest.approx(np.corrcoef(X[:, i], rest)[0, 1], abs=1e-9)
        assert st.loc[i, "p"] == pytest.approx(X[:, i].mean())


def test_rasch_standard_errors_are_calibrated():
    """Across items, |b_hat - b| < 1.96 SE should hold for roughly 95% (well-calibrated uncertainty)."""
    rng = np.random.default_rng(7)
    b = np.linspace(-2, 2, 40)
    P, I, X = [], [], []
    for p in range(1500):
        th = rng.normal()
        for i in range(40):
            P.append(p); I.append(i); X.append(float(rng.random() < 1 / (1 + math.exp(-(th - b[i])))))
    r = fit_rasch(P, I, X)
    cover = np.mean(np.abs(r.b - b[r.items]) < 1.96 * r.se)
    assert 0.85 <= cover <= 1.0
    assert abs(r.theta.mean()) < 0.1  # identification: ability prior N(0,1)
