"""Advisory form-comparability: deterministic maths, honest statuses, and the API surface."""
import pytest

from app.services.assembly.comparability import MIN_COVERAGE, compare_forms, form_difficulty
from app.services.calibration.service import equivalence_decision

V1 = "/api/v1"


def test_form_difficulty_mean_se_and_coverage():
    d = form_difficulty([(0.0, 0.2), (1.0, 0.2), (-1.0, 0.2), None])
    assert d["n_items"] == 4 and d["n_calibrated"] == 3 and d["coverage"] == 0.75
    assert d["mean_b"] == 0.0
    assert d["se_mean_b"] == pytest.approx((3 * 0.04) ** 0.5 / 3, abs=1e-3)
    empty = form_difficulty([None, None])
    assert empty["mean_b"] is None and empty["coverage"] == 0.0
    assert form_difficulty([(1.0, 0.0), (1.0, None)])["n_calibrated"] == 0  # unusable SE is not "calibrated"


def _f(mean, se, cov=1.0):
    return {"n_items": 30, "n_calibrated": int(30 * cov), "coverage": cov, "mean_b": mean, "se_mean_b": se}


def test_status_is_insufficient_calibration_when_coverage_is_low():
    out = compare_forms({"A": _f(0.0, 0.05), "B": _f(0.0, 0.05, cov=MIN_COVERAGE - 0.1)}, 0.5, equivalence_decision)
    assert out["status"] == "insufficient_calibration" and out["uncalibrated_forms"] == ["B"]
    assert "largest_pairwise_difference" not in out  # no comparison is invented from partial data
    nocal = compare_forms({"A": {"n_items": 30, "n_calibrated": 0, "coverage": 0.0, "mean_b": None, "se_mean_b": None},
                           "B": _f(0.0, 0.05)}, 0.5, equivalence_decision)
    assert nocal["status"] == "insufficient_calibration"


def test_within_exceeds_and_inconclusive_use_the_shared_equivalence_rule():
    close = compare_forms({"A": _f(0.00, 0.05), "B": _f(0.05, 0.05)}, 0.5, equivalence_decision)
    assert close["status"] == "within_configured_margin"
    assert "not equivalence" in close["message"]  # never presented as proof of equivalence
    far = compare_forms({"A": _f(0.0, 0.05), "B": _f(1.2, 0.05)}, 0.5, equivalence_decision)
    assert far["status"] == "exceeds_configured_margin"
    noisy = compare_forms({"A": _f(0.0, 0.4), "B": _f(0.3, 0.4)}, 0.5, equivalence_decision)
    assert noisy["status"] == "inconclusive"  # wide interval straddles the margin


def test_worst_pair_is_reported_and_single_form_is_not_applicable():
    out = compare_forms({"A": _f(0.0, 0.05), "B": _f(0.1, 0.05), "C": _f(-0.3, 0.05)}, 0.5, equivalence_decision)
    w = out["largest_pairwise_difference"]
    assert sorted(w["forms"]) == ["B", "C"] and abs(w["diff"]) == pytest.approx(0.4)
    lo, hi = w["ci90"]
    assert lo < w["diff"] < hi
    assert compare_forms({"A": _f(0.0, 0.05)}, 0.5, equivalence_decision)["status"] == "not_applicable"


def test_assembly_run_reports_comparability_without_gating(client, auth):
    cfg = {"drive": "Comparability drive", "n_slots": 2, "per_section": {"QUANT": 3, "LOGICAL": 3, "VERBAL": 3},
           "max_adjacent_overlap_pct": 0, "max_slot_exposures": 5, "min_slot_spacing": 0, "seed": 777}
    run = client.post(f"{V1}/assembly/runs", json=cfg, headers=auth("designer")).json()
    assert run["status"] == "succeeded", run["diagnostics"]
    got = client.get(f"{V1}/assembly/runs/{run['id']}", headers=auth("designer")).json()
    c = got["comparability"]
    assert c["status"] in {"insufficient_calibration", "within_configured_margin", "exceeds_configured_margin", "inconclusive"}
    assert set(c["forms"]) == {f["code"] for f in got["forms"]} and "caveat" in c
    # advisory only: publishing is not blocked by the comparability outcome
    assert client.post(f"{V1}/assembly/runs/{run['id']}/publish", headers=auth("designer")).status_code == 200
