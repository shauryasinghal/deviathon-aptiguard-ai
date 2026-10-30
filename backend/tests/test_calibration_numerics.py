"""Numerical verification of the calibration stack: Rasch recovery, invariance, an independently coded likelihood,
the equivalence rule at its boundaries, degenerate inputs, and the end-to-end pipeline on simulated data with a known
answer. Everything is seeded and deterministic; no production code is exercised through the network or a live database
(the pipeline test uses the session's throw-away test database and rolls back)."""
import math

import numpy as np
import pandas as pd
import pytest
from scipy.optimize import minimize
from scipy.special import expit, logsumexp

from app.services.assembly.comparability import Z90, compare_forms, form_difficulty
from app.services.calibration.ctt import item_statistics, newcombe_diff_ci, wilson_ci
from app.services.calibration.rasch import fit_rasch
from app.services.calibration.service import equivalence_decision


def simulate(n_persons: int, b: np.ndarray, seed: int, theta_mean: float = 0.0):
    """Complete design: every person answers every item. Returns long-format (person, item, x) arrays."""
    rng = np.random.default_rng(seed)
    theta = rng.normal(theta_mean, 1.0, n_persons)
    prob = expit(theta[:, None] - b[None, :])
    x = (rng.random(prob.shape) < prob).astype(float)
    person = np.repeat(np.arange(n_persons), len(b))
    item = np.tile(np.arange(len(b)), n_persons)
    return person, item, x.ravel(), x


# ------------------------------------------------------------------ recovery
def test_rasch_recovers_known_difficulties_within_their_own_standard_errors():
    b = np.linspace(-1.5, 1.5, 30)
    person, item, x, _ = simulate(1500, b, seed=11)
    r = fit_rasch(person, item, x)
    err = r.b - b[r.items]
    assert r.converged
    assert np.sqrt(np.mean(err ** 2)) < 0.12  # about 0.07 expected from the sampling error of 1,500 persons
    assert abs(err.mean()) < 0.1
    assert np.all(np.abs(err) < 3.5 * r.se)  # reported uncertainty is of the right size
    assert 0.04 < r.se.min() and r.se.max() < 0.12


def test_rasch_interval_coverage_over_several_seeds():
    b = np.linspace(-1.5, 1.5, 20)
    hits = total = 0
    for seed in (101, 102, 103, 104, 105):
        person, item, x, _ = simulate(800, b, seed)
        r = fit_rasch(person, item, x)
        assert r.converged
        hits += int(np.sum(np.abs(r.b - b[r.items]) < 1.96 * r.se))
        total += len(r.b)
    assert total == 100 and hits / total >= 0.88  # nominal 95%; a 100-interval sample can dip a few points


def test_rasch_difficulty_order_follows_the_observed_proportions_correct():
    b = np.linspace(-2, 2, 12)
    person, item, x, mat = simulate(1000, b, seed=7)
    r = fit_rasch(person, item, x)
    p = mat.mean(0)
    assert list(np.argsort(r.b)) == list(np.argsort(-p))  # harder (higher b) <=> lower p


# ------------------------------------------------------------------ invariance
def test_rasch_is_invariant_to_row_order():
    b = np.linspace(-1.0, 1.0, 10)
    person, item, x, _ = simulate(600, b, seed=21)
    base = fit_rasch(person, item, x)
    perm = np.random.default_rng(0).permutation(len(x))
    shuffled = fit_rasch(person[perm], item[perm], x[perm])
    assert np.array_equal(base.items, shuffled.items)
    assert np.allclose(base.b, shuffled.b, atol=1e-8)
    assert np.allclose(base.se, shuffled.se, atol=1e-8)
    assert base.iterations == shuffled.iterations


def test_rasch_is_invariant_to_item_and_person_labels():
    b = np.linspace(-1.0, 1.0, 10)
    person, item, x, _ = simulate(600, b, seed=22)
    base = fit_rasch(person, item, x)
    relabel_item = {i: 5000 + 37 * (9 - i) for i in range(10)}  # non-contiguous, order-reversing labels
    relabel_person = {p: 90000 - 3 * p for p in range(600)}
    new = fit_rasch([relabel_person[p] for p in person], [relabel_item[i] for i in item], x)
    by_new = dict(zip(new.items.tolist(), new.b))
    for i, b_i in zip(base.items.tolist(), base.b):
        assert by_new[relabel_item[i]] == pytest.approx(b_i, abs=1e-8)


def test_rasch_difficulty_scale_is_set_by_the_ability_prior_not_by_a_constant_offset():
    """Shifting every true difficulty by +0.5 must shift every estimate by about +0.5 (the ability prior is fixed)."""
    b = np.linspace(-1.0, 1.0, 15)
    p0, i0, x0, _ = simulate(2000, b, seed=31)
    p1, i1, x1, _ = simulate(2000, b + 0.5, seed=31)
    r0, r1 = fit_rasch(p0, i0, x0), fit_rasch(p1, i1, x1)
    assert np.mean(r1.b - r0.b) == pytest.approx(0.5, abs=0.1)


# ------------------------------------------------------------------ independent likelihood
def _marginal_loglik(b: np.ndarray, x: np.ndarray) -> float:
    """Marginal log-likelihood with theta ~ N(0,1) by 61-point Gauss-Hermite quadrature (a different rule and different
    code from the 31-node grid in rasch.py). x is the persons x items 0/1 matrix of a complete design."""
    nodes, weights = np.polynomial.hermite_e.hermegauss(61)
    logw = np.log(weights / math.sqrt(2 * math.pi))
    logit = nodes[None, :] - b[:, None]                       # items x nodes
    logp, logq = -np.logaddexp(0, -logit), -np.logaddexp(0, logit)
    joint = x @ logp + (1 - x) @ logq + logw[None, :]         # persons x nodes
    return float(logsumexp(joint, axis=1).sum())


def test_fitted_difficulties_maximise_an_independently_coded_likelihood():
    b = np.linspace(-1.2, 1.2, 12)
    person, item, x, mat = simulate(700, b, seed=41)
    r = fit_rasch(person, item, x)
    assert r.converged
    # an independent optimiser starting from zeros must reach the same maximum
    res = minimize(lambda v: -_marginal_loglik(v, mat), np.zeros(12), method="L-BFGS-B")
    assert res.success
    assert np.allclose(r.b, res.x, atol=0.02)
    # the EM solution is a stationary point of the independent likelihood (central-difference gradient ~ 0)
    grad = np.array([(_marginal_loglik(r.b + h, mat) - _marginal_loglik(r.b - h, mat)) / 2e-4
                     for h in 1e-4 * np.eye(12)])
    assert np.max(np.abs(grad)) < 0.5  # log-likelihood changes by < 0.5 per logit at a maximum worth ~ -4,700
    # the reported log-likelihood agrees with the independent value at the same parameters
    assert r.loglik == pytest.approx(_marginal_loglik(r.b, mat), rel=2e-3)


# ------------------------------------------------------------------ degenerate input (existing contract, characterised)
@pytest.mark.parametrize("forced,sign", [(1.0, -1), (0.0, 1)])
def test_all_correct_or_all_wrong_item_is_flagged_not_silently_estimated(forced, sign):
    b = np.linspace(-1, 1, 10)
    person, item, x, _ = simulate(800, b, seed=5)
    x = x.copy()
    x[item == 3] = forced
    r = fit_rasch(person, item, x)
    k = list(r.items).index(3)
    assert not r.converged  # the degenerate item prevents convergence ...
    assert r.iterations == 300
    assert np.isfinite(r.b).all() and np.isfinite(r.se).all()  # ... but nothing is NaN or infinite
    assert sign * r.b[k] > 5  # all correct -> very easy (negative b); all wrong -> very hard (positive b)
    assert r.se[k] > 100  # and its uncertainty is reported as enormous


def test_max_iterations_reports_non_convergence_instead_of_raising():
    b = np.linspace(-1, 1, 10)
    person, item, x, _ = simulate(500, b, seed=5)
    r = fit_rasch(person, item, x, max_iter=2)
    assert r.converged is False and r.iterations == 2 and np.isfinite(r.b).all()


def test_minimal_complete_design_is_identified_and_symmetric():
    r = fit_rasch([0, 0, 1, 1], [0, 1, 0, 1], [1, 0, 0, 1])
    assert r.converged and abs(r.b[0] - r.b[1]) < 1e-6  # identical item totals -> identical difficulty


def test_ctt_handles_all_correct_all_wrong_and_tiny_items():
    rows = []
    for p in range(40):
        rows += [{"person": p, "item": 1, "score": 1.0, "rt_ms": 1000.0}, {"person": p, "item": 2, "score": 0.0, "rt_ms": 1000.0},
                 {"person": p, "item": 3, "score": float(p % 2), "rt_ms": 1000.0}]
    rows += [{"person": 100 + p, "item": 4, "score": 1.0, "rt_ms": 900.0} for p in range(5)]
    s = item_statistics(pd.DataFrame(rows)).set_index("item")
    assert s.loc[1, "p"] == 1.0 and s.loc[1, "p_hi"] == 1.0 and s.loc[1, "p_lo"] < 1.0  # Wilson never collapses to a point
    assert s.loc[2, "p"] == 0.0 and s.loc[2, "p_lo"] == 0.0 and s.loc[2, "p_hi"] > 0.0
    assert pd.isna(s.loc[1, "item_rest_r"]) and pd.isna(s.loc[2, "item_rest_r"])  # no variance -> no correlation
    assert pd.isna(s.loc[4, "item_rest_r"]) and s.loc[4, "n_valid"] == 5  # fewer than 20 presentations -> no correlation
    assert wilson_ci(0, 0) == (None, None)


# ------------------------------------------------------------------ equivalence rule at the tolerance boundary
M = 0.5


@pytest.mark.parametrize("lo,hi,expected", [
    (-M, M, "within_tolerance"),                   # interval exactly on the margins is inside (inclusive)
    (-M - 1e-9, M, "requires_review"),
    (-M, M + 1e-9, "requires_review"),
    (0.0, 0.0, "within_tolerance"),
    (M, M + 0.2, "requires_review"),               # lower limit exactly at the margin is not "entirely outside"
    (M + 1e-9, M + 0.2, "outside_tolerance"),
    (-M - 0.2, -M, "requires_review"),
    (-M - 0.2, -M - 1e-9, "outside_tolerance"),
    (-2.0, 2.0, "requires_review"),                # wide interval straddling both margins is inconclusive
])
def test_equivalence_decision_at_the_boundary(lo, hi, expected):
    assert equivalence_decision(lo, hi, M) == expected


def test_equivalence_decision_is_mirror_symmetric_and_scale_invariant():
    grid = np.linspace(-1.5, 1.5, 13)
    for lo in grid:
        for hi in grid[grid >= lo]:
            d = equivalence_decision(float(lo), float(hi), M)
            assert equivalence_decision(float(-hi), float(-lo), M) == d  # sign of the difference is arbitrary
            assert equivalence_decision(float(lo) * 4, float(hi) * 4, M * 4) == d  # units of the scale do not matter


def test_ctt_fallback_margin_needs_enough_data_to_call_two_items_equivalent():
    """Same observed proportion (0.5) in both items: only a large enough sample can show equivalence at the 0.08 margin."""
    lo_big, hi_big = newcombe_diff_ci(250, 500, 250, 500, 1.6449)
    lo_small, hi_small = newcombe_diff_ci(50, 100, 50, 100, 1.6449)
    assert equivalence_decision(lo_big, hi_big, 0.08) == "within_tolerance"   # half-width about 0.05
    assert equivalence_decision(lo_small, hi_small, 0.08) == "requires_review"  # half-width about 0.12: not enough data
    assert lo_small == pytest.approx(-hi_small, abs=1e-9)  # equal proportions give a symmetric interval


# ------------------------------------------------------------------ comparability arithmetic
def _form(mean, se, cov=1.0):
    return {"n_items": 30, "n_calibrated": int(30 * cov), "coverage": cov, "mean_b": mean, "se_mean_b": se}


def test_form_difficulty_standard_error_of_the_mean():
    d = form_difficulty([(0.2, 0.1), (0.4, 0.2), (-0.6, 0.2), (1.0, 0.1)])
    assert d["mean_b"] == pytest.approx(0.25, abs=1e-3)
    assert d["se_mean_b"] == pytest.approx(math.sqrt(0.01 + 0.04 + 0.04 + 0.01) / 4, abs=1e-3)


def test_compare_forms_interval_is_the_exact_normal_interval_and_ignores_input_order():
    out = compare_forms({"A": _form(0.0, 0.05), "B": _form(0.3, 0.05)}, M, equivalence_decision)
    w = out["largest_pairwise_difference"]
    se = math.sqrt(0.05 ** 2 + 0.05 ** 2)
    assert w["diff"] == pytest.approx(-0.3, abs=1e-3) and w["se"] == pytest.approx(se, abs=1e-3)
    assert w["ci90"] == pytest.approx([-0.3 - Z90 * se, -0.3 + Z90 * se], abs=1e-3)
    reversed_in = compare_forms({"B": _form(0.3, 0.05), "A": _form(0.0, 0.05)}, M, equivalence_decision)
    assert reversed_in["largest_pairwise_difference"] == w and reversed_in["status"] == out["status"]


def test_compare_forms_boundary_follows_the_shared_rule():
    # difference 0.4 with SE 0.1 -> 90% CI [0.236, 0.564] straddles the 0.5 margin: inconclusive
    inconclusive = compare_forms({"A": _form(0.0, 0.1 / math.sqrt(2)), "B": _form(0.4, 0.1 / math.sqrt(2))}, M, equivalence_decision)
    assert inconclusive["status"] == "inconclusive"
    # tiny uncertainty and a difference past the margin -> exceeds
    exceeds = compare_forms({"A": _form(0.0, 0.01), "B": _form(0.6, 0.01)}, M, equivalence_decision)
    assert exceeds["status"] == "exceeds_configured_margin"


# ------------------------------------------------------------------ pipeline on simulated responses with a known answer
def _frame(question_ids, b, n_persons, seed, short_item=None):
    person, item, x, _ = simulate(n_persons, np.asarray(b, dtype=float), seed)
    ids = np.asarray(question_ids)[item]
    df = pd.DataFrame({"person": person, "item": ids, "is_correct": x.astype(bool), "selected": "A", "rt_ms": 5000.0,
                       "slot_id": 1, "form_id": 1, "slot_seq": 1, "drive": "sim"})
    if short_item is not None:  # leave this item with only 30 responses
        df = df[(df["item"] != short_item) | (df["person"] < 30)]
    df["score"] = df["is_correct"].astype(float)
    return df


@pytest.fixture()
def pair_and_pool(db):
    from sqlalchemy import select

    from app.models import Question

    variant = db.scalars(select(Question).where(Question.parent_id.is_not(None), Question.leak_status == "none",
                                                Question.status != "archived").order_by(Question.id)).first()
    source = db.get(Question, variant.parent_id)
    pool = db.scalars(select(Question).where(Question.org_id == variant.org_id, Question.leak_status == "none",
                                             Question.id.not_in([variant.id, source.id])).order_by(Question.id).limit(10)).all()
    assert source.leak_status == "none" and len(pool) == 10
    return variant, source, pool


def _run(db, monkeypatch, frame, org_id):
    from app.services.calibration import service

    monkeypatch.setattr(service, "load_response_frame", lambda _db, _org: frame.copy())
    run = service.run_calibration(db, org_id, None)
    db.flush()
    return run, {c.question_id: c for c in db.query(service.ItemCalibration).filter_by(run_id=run.id)}


@pytest.mark.parametrize("delta,allowed", [(0.0, {"within_tolerance"}), (1.5, {"outside_tolerance"}),
                                           (-1.5, {"outside_tolerance"})])
def test_pipeline_classifies_a_variant_with_a_known_difficulty_gap(db, monkeypatch, pair_and_pool, delta, allowed):
    variant, source, pool = pair_and_pool
    b_pool = np.linspace(-1.0, 1.0, 10)
    ids = [source.id, variant.id] + [q.id for q in pool]
    frame = _frame(ids, [0.0, delta] + list(b_pool), n_persons=700, seed=61)
    try:
        run, cal = _run(db, monkeypatch, frame, variant.org_id)
        assert run.rasch_fitted and run.status == "completed"
        c = cal[variant.id]
        assert c.diff_basis == "rasch_logit" and c.reference_question_id == source.id
        assert c.diff_from_reference == pytest.approx(delta, abs=0.35)  # sampling error of two items, 700 persons
        assert c.diff_ci_low < c.diff_from_reference < c.diff_ci_high
        assert c.status in allowed
    finally:
        db.rollback()


def test_pipeline_does_not_call_a_variant_equivalent_when_data_are_insufficient(db, monkeypatch, pair_and_pool):
    variant, source, pool = pair_and_pool
    ids = [source.id, variant.id] + [q.id for q in pool]
    frame = _frame(ids, [0.0, 0.0] + list(np.linspace(-1, 1, 10)), n_persons=700, seed=62, short_item=variant.id)
    try:
        run, cal = _run(db, monkeypatch, frame, variant.org_id)
        c = cal[variant.id]
        assert c.n_valid == 30 and c.status == "insufficient_data"  # below min_responses (60)
        assert c.diff_basis is None and c.diff_from_reference is None
    finally:
        db.rollback()


def test_pipeline_with_no_responses_is_reported_as_no_data(db, monkeypatch):
    from sqlalchemy import select

    from app.models import Organization
    from app.services.calibration import service

    org = db.scalars(select(Organization)).first()
    empty = pd.DataFrame(columns=["person", "item", "is_correct", "selected", "rt_ms", "slot_id", "form_id", "slot_seq",
                                  "drive", "score"])
    monkeypatch.setattr(service, "load_response_frame", lambda _db, _org: empty)
    try:
        run = service.run_calibration(db, org.id, None)
        assert run.status == "no_data" and run.n_responses == 0 and not run.rasch_fitted
    finally:
        db.rollback()
