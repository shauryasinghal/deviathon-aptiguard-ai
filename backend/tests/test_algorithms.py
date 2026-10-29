"""Unit tests: text similarity, calibration statistics, exposure risk, assembly, leak statistics, reports."""
import math

import numpy as np
import pandas as pd
import pytest

from app.services.assembly.algorithm import AssemblyConfig, PoolItem, assemble, overlap_stats, quotas, verify_plan
from app.services.calibration.ctt import item_statistics, wilson_ci
from app.services.calibration.rasch import RaschNotIdentified, fit_rasch
from app.services.calibration.service import equivalence_decision
from app.services.exposure.service import ExposureStats, risk_score
from app.services.leakage.stats import bh_adjust, mantel_haenszel, purified_drift
from app.services.leakage.text_match import ItemText, RecordText, match_items
from app.services.policies import DEFAULT_POLICIES
from app.services.reporting.reports import Report, safe_cell, to_csv, to_pdf
from app.services.textsim import containment, mask_numbers, normalize, text_hash


# ---------------------------------------------------------------- text
def test_normalization():
    assert normalize("  The PRICE,  rises!!\n") == "the price rises"
    assert normalize("Rs. 500") == normalize("₹ 500")
    assert text_hash("Hello   World") == text_hash("hello world!")
    assert mask_numbers("from 400 to 12.5") == "from # to #"


def test_containment_robust_to_surrounding_text():
    item = normalize("A train covers 240 km in 3 hours at a constant speed")
    post = normalize("🔥 slot 2 question: A train covers 240 km in 3 hours at a constant speed. ans B pls share")
    assert containment(item, post) == 1.0
    assert containment(item, normalize("totally unrelated chatter about results")) == 0.0


def test_text_match_levels():
    th = DEFAULT_POLICIES["leak"]
    items = [ItemText(1, "Q1", 10, "The price of a laptop rises from ₹400 to ₹500. What is the percentage increase?",
                      ["25%", "20%", "40%", "30%"]),
             ItemText(2, "Q2", 10, "The price of a backpack rises from ₹800 to ₹1000. What is the percentage increase?",
                      ["25%", "20%", "80%", "30%"])]
    recs = [RecordText(1, "P1", "t.me/x", None, "today: The price of a laptop rises from ₹400 to ₹500. What is the percentage increase? A 25%"),
            RecordText(2, "P2", "t.me/x", None, "a laptop was ₹400 now ₹500 by what percent did price change? options 25% 20% 40% 30%"),
            RecordText(3, "P3", "forum", None, "The price of a bicycle rises from ₹200 to ₹300. What is the percentage increase?")]
    m = {(x.item_id, x.record_id): x.level for x in match_items(items, recs, th)}
    assert m[(1, 1)] == "item_exact"
    assert m[(1, 2)] == "item_similar"           # paraphrase with identical numeric signature
    assert m.get((2, 1)) in (None, "family")     # sibling with different numbers is not an item-level match
    assert m.get((1, 3)) == "family"


# ---------------------------------------------------------------- calibration
def test_wilson_ci():
    lo, hi = wilson_ci(50, 100)
    assert lo < 0.5 < hi and abs((lo + hi) / 2 - 0.5) < 1e-9
    assert wilson_ci(0, 0) == (None, None)
    lo, hi = wilson_ci(0, 20)
    assert lo == 0.0 and 0 < hi < 0.2


def test_item_statistics_missing_and_discrimination():
    rng = np.random.default_rng(0)
    rows = []
    for p in range(300):
        th = rng.normal()
        for i in range(10):
            sc = float(rng.random() < 1 / (1 + math.exp(-(th - (i - 5) / 3))))
            if i == 0 and p % 10 == 0:
                sc = np.nan
            rows.append((p, i, sc, 1000.0))
    st = item_statistics(pd.DataFrame(rows, columns=["person", "item", "score", "rt_ms"])).set_index("item")
    assert st.loc[0, "missing_rate"] == pytest.approx(0.1)
    assert st.loc[0, "n_valid"] == 270
    assert (st["item_rest_r"] > 0.15).all()


def test_rasch_recovers_difficulties_and_refuses_disconnected_design():
    rng = np.random.default_rng(1)
    b = np.linspace(-2, 2, 30)
    P, I, X = [], [], []
    for p in range(800):
        th = rng.normal()
        form = p % 2
        items = list(range(0, 6)) + list(range(6 + form * 12, 18 + form * 12))
        for i in items:
            P.append(p); I.append(i); X.append(float(rng.random() < 1 / (1 + math.exp(-(th - b[i])))))
    r = fit_rasch(P, I, X)
    assert r.converged
    assert np.corrcoef(r.b, b[r.items])[0, 1] > 0.97
    with pytest.raises(RaschNotIdentified):
        fit_rasch([0, 0, 1, 1], [0, 1, 2, 3], [1, 0, 1, 0])


@pytest.mark.parametrize("lo,hi,expected", [(-0.2, 0.3, "within_tolerance"), (0.6, 1.2, "outside_tolerance"),
                                            (-1.0, -0.6, "outside_tolerance"), (-0.1, 0.7, "requires_review")])
def test_equivalence_decision(lo, hi, expected):
    assert equivalence_decision(lo, hi, 0.5) == expected


# ---------------------------------------------------------------- exposure
class _Q:
    def __init__(self, leak="none"):
        self.id, self.leak_status = 1, leak


def test_risk_score_components_and_levels():
    pol = DEFAULT_POLICIES["exposure"]
    low = risk_score(ExposureStats(1, 0, 0), _Q(), pol)
    assert low["score"] == 0 and low["level"] == "low"
    over = risk_score(ExposureStats(1, 3, 450), _Q(), pol)
    assert over["over_limit"] and over["level"] == "high"
    leaked = risk_score(ExposureStats(1, 1, 150), _Q("confirmed"), pol)
    assert leaked["level"] == "high" and any(c["factor"] == "leak_status" for c in leaked["components"])
    fam = risk_score(ExposureStats(1, 0, 0), _Q(), pol, family_leak=True)
    assert any(c["factor"] == "family_leak" for c in fam["components"])


# ---------------------------------------------------------------- assembly
def _pool(n_fam=45, prior=0):
    pool, i = [], 0
    for sec in ("QUANT", "LOGICAL", "VERBAL"):
        for f in range(n_fam):
            for _ in range(3):
                i += 1
                pool.append(PoolItem(i, f"I{i}", sec, ("easy", "medium", "hard")[f % 3], hash((sec, f)), prior))
    return pool


MIX = {s: {"easy": 0.3, "medium": 0.4, "hard": 0.3} for s in ("QUANT", "LOGICAL", "VERBAL")}
PER = {"QUANT": 10, "LOGICAL": 10, "VERBAL": 10}


def test_quotas_and_overlap_formulas():
    assert quotas(10, {"easy": 0.3, "medium": 0.4, "hard": 0.3}) == {"easy": 3, "medium": 4, "hard": 3}
    assert sum(quotas(7, {"easy": 1, "medium": 1, "hard": 1}).values()) == 7
    st = overlap_stats({1, 2, 3, 4}, {3, 4, 5, 6, 7, 8})
    assert st["shared"] == 2 and st["jaccard"] == pytest.approx(2 / 8) and st["smaller_form_pct"] == 50.0


def test_assembly_satisfies_constraints_and_is_reproducible():
    cfg = AssemblyConfig(10, PER, MIX, max_adjacent_overlap_pct=10, seed=5)
    r1, r2 = assemble(_pool(), cfg), assemble(_pool(), cfg)
    assert r1.ok and r1.diagnostics["violations"] == []
    assert [f["item_ids"] for f in r1.forms] == [f["item_ids"] for f in r2.forms]
    assert all(o["constraint_ok"] for o in r1.overlap if o["adjacent"])
    assert max(o["smaller_form_pct"] for o in r1.overlap if o["adjacent"]) <= 10


def test_assembly_with_reuse_respects_overlap_budget():
    # small pool + spacing 0 forces reuse; adjacent overlap must still stay within 20% (6 items)
    cfg = AssemblyConfig(6, PER, MIX, max_adjacent_overlap_pct=20, max_slot_exposures=6, min_slot_spacing=0,
                         separate_families_adjacent=False, seed=3)
    r = assemble(_pool(n_fam=12), cfg)
    assert r.ok, r.diagnostics
    assert max(o["shared"] for o in r.overlap if o["adjacent"]) <= 6


def test_impossible_constraints_fail_explicitly():
    cfg = AssemblyConfig(10, PER, MIX, max_slot_exposures=1, seed=1)
    r = assemble(_pool(n_fam=6), cfg)
    assert not r.ok
    assert r.diagnostics["stage"] == "preflight" and r.diagnostics["infeasible_cells"]
    assert "infeasible" in r.diagnostics["explanation"].lower()


def test_verify_plan_catches_violations():
    pool = {p.id: p for p in _pool()}
    cfg = AssemblyConfig(2, {"QUANT": 2}, {"QUANT": {"easy": 0.5, "hard": 0.5, "medium": 0}}, max_adjacent_overlap_pct=0)
    q = [p for p in pool.values() if p.section == "QUANT"]
    easy = [p.id for p in q if p.band == "easy"]
    hard = [p.id for p in q if p.band == "hard"]
    plan = [[{easy[0], hard[0]}], [{easy[0], hard[3]}]]  # shares one item with an adjacent form
    v = verify_plan(plan, pool, cfg)
    assert any(x["constraint"] == "adjacent_overlap" for x in v)


# ---------------------------------------------------------------- leak statistics
def _sim(leak_items=(), leak_from=3, slots=8, n=150, shift=None, seed=0):
    rng = np.random.default_rng(seed)
    shift = shift or {}
    rows = []
    pid = 0
    b = np.linspace(-1.5, 1.5, 20)
    for s in range(1, slots + 1):
        for _ in range(n):
            pid += 1
            th = rng.normal(shift.get(s, 0.0), 1)
            saw = s >= leak_from and rng.random() < 0.6
            for i in range(20):
                p = 1 / (1 + math.exp(-(th - b[i])))
                if saw and i in leak_items:
                    p = 0.97
                sc = float(rng.random() < p)
                rt = 50000 * math.exp(rng.normal(0, 0.3)) * (0.35 if saw and i in leak_items else 1)
                rows.append((pid, i, sc, sc, rt, s, "D"))
    return pd.DataFrame(rows, columns=["person", "item", "score", "scored", "rt_ms", "slot_seq", "drive"])


POL = {**DEFAULT_POLICIES["leak"]}


def test_ability_shift_alone_is_not_flagged():
    df = _sim(shift={5: 0.5, 6: 0.5, 7: 0.5, 8: 0.5})
    out = purified_drift(df, POL)
    flagged = out[(out.q_mh < POL["fdr_alpha"]) & (out.delta >= POL["min_effect_delta"])]
    assert flagged.empty, flagged[["item", "delta", "q_mh"]]


def test_injected_leak_is_flagged_with_speedup():
    df = _sim(leak_items=(4, 12))
    out = purified_drift(df, POL).set_index("item")
    for i in (4, 12):
        assert out.loc[i, "q_mh"] < 0.05 and out.loc[i, "delta"] >= 1.0
        assert out.loc[i, "rt_rel_ratio"] < 0.75
    clean = out.drop(index=[4, 12])
    assert ((clean.q_mh < 0.05) & (clean.delta >= 1.0)).sum() == 0


def test_mh_and_bh():
    ref = pd.DataFrame({"score": [1, 0] * 100, "rest": np.linspace(0, 1, 200)})
    foc = pd.DataFrame({"score": [1, 0] * 100, "rest": np.linspace(0, 1, 200)})
    assert mantel_haenszel(ref, foc)["p"] > 0.2
    q = bh_adjust([0.01, 0.04, 0.03, 0.5])
    assert q[0] == pytest.approx(0.04) and q[3] == pytest.approx(0.5) and all(0 <= x <= 1 for x in q)


# ---------------------------------------------------------------- reports
def test_csv_injection_neutralized():
    assert safe_cell("=HYPERLINK(\"x\")") == "'=HYPERLINK(\"x\")"
    assert safe_cell("+1+1") == "'+1+1"
    assert safe_cell("@SUM(A1)") == "'@SUM(A1)"
    assert safe_cell("-0.25") == "-0.25"  # plain negative numbers stay numeric
    assert safe_cell(None) == ""


def test_report_rendering_includes_provenance():
    rep = Report("x", "Test report", ["a", "b"], [["=cmd", 1.5]], warnings=["small sample"], provenance=["synthetic"])
    csv_text = to_csv(rep)
    assert "# provenance: synthetic" in csv_text and "# warning: small sample" in csv_text and "'=cmd" in csv_text
    assert "generated_at" in csv_text
    assert to_pdf(rep)[:4] == b"%PDF"
