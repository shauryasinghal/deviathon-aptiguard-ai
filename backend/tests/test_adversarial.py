"""Adversarial and edge cases: LLM output handling (mocked, no network), leak matching robustness, detection lifecycle,
assembly boundaries."""
import time

import pytest

from app.services.assembly.algorithm import AssemblyConfig, PoolItem, assemble
from app.services.generation.base import GeneratedItem
from app.services.generation.registry import TEMPLATES, generate
from app.services.leakage.text_match import ItemText, RecordText, match_items
from app.services.policies import DEFAULT_POLICIES
from app.services.validation.validator import validate

V1 = "/api/v1"
TH = DEFAULT_POLICIES["leak"]


# ------------------------------------------------------------------ distractor safety across many seeds
@pytest.mark.parametrize("tid", sorted(TEMPLATES))
def test_no_distractor_equals_the_key_over_many_seeds(tid):
    for band in ("easy", "medium", "hard"):
        for seed in range(200, 260):
            it = generate(tid, band, seed)
            key = [o["text"].strip().lower() for o in it.options if o["is_correct"]]
            others = [o["text"].strip().lower() for o in it.options if not o["is_correct"]]
            assert len(key) == 1 and key[0] not in others and len(set(others)) == 3


# ------------------------------------------------------------------ LLM path (adapter mocked)
def _llm_item(options, expr=None, section="QUANT"):
    return GeneratedItem(section, "LLM", "c", "s", "medium", "A shop sells 12 pens for ₹60. What is the price of one pen?",
                         options, "60 / 12 = 5", {"verification_expression": expr})


def test_llm_item_with_two_keys_is_rejected():
    status, _ = validate(_llm_item([{"key": "A", "text": "5", "is_correct": True}, {"key": "B", "text": "6", "is_correct": True},
                                    {"key": "C", "text": "7", "is_correct": False}, {"key": "D", "text": "8", "is_correct": False}], "60/12"), [], "llm")
    assert status == "failed"


def test_llm_item_with_wrong_key_is_rejected_by_expression():
    status, checks = validate(_llm_item([{"key": "A", "text": "₹6", "is_correct": True}, {"key": "B", "text": "₹5", "is_correct": False},
                                         {"key": "C", "text": "₹7", "is_correct": False}, {"key": "D", "text": "₹8", "is_correct": False}], "60/12"), [], "llm")
    assert status == "failed" and any(c.check == "answer_recomputed" and c.status == "fail" for c in checks)


def test_llm_item_without_verification_is_not_marked_passed():
    status, checks = validate(_llm_item([{"key": "A", "text": "₹5", "is_correct": True}, {"key": "B", "text": "₹6", "is_correct": False},
                                         {"key": "C", "text": "₹7", "is_correct": False}, {"key": "D", "text": "₹8", "is_correct": False}]), [], "llm")
    assert status == "warning" and any(c.check == "answer_unverified" for c in checks)


def test_llm_generation_route_persists_only_valid_items_as_pending(client, auth, monkeypatch):
    from app.core.config import Settings
    from app.services.generation import engine

    good = _llm_item([{"key": "A", "text": "₹5", "is_correct": True}, {"key": "B", "text": "₹6", "is_correct": False},
                      {"key": "C", "text": "₹7", "is_correct": False}, {"key": "D", "text": "₹4", "is_correct": False}], "60/12")
    bad = _llm_item([{"key": "A", "text": "₹9", "is_correct": True}, {"key": "B", "text": "₹6", "is_correct": False},
                     {"key": "C", "text": "₹7", "is_correct": False}, {"key": "D", "text": "₹4", "is_correct": False}], "60/12")
    bad.stem = "A vendor sells 12 notebooks for ₹60 in total. What does each notebook cost?"
    monkeypatch.setattr(engine, "get_settings", lambda: Settings(llm_provider="anthropic", llm_api_key="test-not-real"))
    monkeypatch.setattr(engine, "generate_llm_variants", lambda src, n, d: [good, bad])
    src = client.get(f"{V1}/questions?q=QNT-PCT-M3-S", headers=auth("designer")).json()["items"][0]
    r = client.post(f"{V1}/questions/{src['id']}/variants:generate", json={"n": 2, "method": "llm"}, headers=auth("designer"))
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["run"]["method"] == "llm" and len(out["created"]) == 1 and out["created"][0]["status"] == "pending_review"
    assert out["created"][0]["generation_method"] == "llm" and len(out["rejections"]) == 1


def test_llm_unavailable_fails_explicitly(client, auth, monkeypatch):
    src = client.get(f"{V1}/questions?q=QNT-PCT-M3-S", headers=auth("designer")).json()["items"][0]
    r = client.post(f"{V1}/questions/{src['id']}/variants:generate", json={"n": 1, "method": "llm"}, headers=auth("designer"))
    assert r.status_code == 422 and "not configured" in r.json()["error"]["message"]


# ------------------------------------------------------------------ leak text matching robustness
STEM = "The price of a laptop rises from ₹400 to ₹500. What is the percentage increase?"
OPTS = ["25%", "20%", "40%", "30%"]


def _levels(text, stem=STEM, opts=OPTS):
    return {m.level for m in match_items([ItemText(1, "Q", 1, stem, opts)], [RecordText(1, "P", "c", None, text)], TH)}


@pytest.mark.parametrize("variant", [
    STEM.upper(),
    "   ".join(STEM.split()),
    STEM.replace("₹", "Rs. "),
    "Q7)\n" + STEM + "\n(a) 25% (b) 20% (c) 40% (d) 30%  ans a",
])
def test_formatting_changes_still_match_item(variant):
    assert _levels(variant) & {"item_exact", "item_similar"}


def test_partial_copy_is_not_overclaimed():
    assert not (_levels("The price of a laptop rises") & {"item_exact"})


def test_unrelated_text_does_not_match():
    assert _levels("When is the result for slot 4 announced? Any idea about the cutoff?") == set()


def test_sibling_with_different_numbers_is_not_item_level():
    assert not (_levels("The price of a laptop rises from ₹800 to ₹1100. What is the percentage increase?") & {"item_exact", "item_similar"})


def test_rerunning_detection_does_not_duplicate_alerts(client, auth):
    h = auth("analyst")
    before = client.get(f"{V1}/leaks/alerts", headers=h).json()["total"]
    r = client.post(f"{V1}/leaks/detect", json={"replay": False}, headers=h).json()
    assert r["summary"]["alerts_created"] == 0
    assert client.get(f"{V1}/leaks/alerts", headers=h).json()["total"] == before


def test_small_groups_are_not_drift_tested():
    import numpy as np
    import pandas as pd

    from app.services.leakage.stats import purified_drift

    rng = np.random.default_rng(0)
    rows = [(p, i, float(rng.random() < 0.5), 0.0, 1000.0, s, "D") for s in range(1, 6) for p in range(s * 100, s * 100 + 10) for i in range(5)]
    df = pd.DataFrame(rows, columns=["person", "item", "score", "scored", "rt_ms", "slot_seq", "drive"])
    df["scored"] = df["score"]
    assert purified_drift(df, TH).empty  # 10 per slot < min_group_n: no claims either way


# ------------------------------------------------------------------ assembly boundaries
def test_empty_pool_fails_with_reason():
    r = assemble([], AssemblyConfig(2, {"QUANT": 2}, {"QUANT": {"easy": 1, "medium": 0, "hard": 0}}))
    assert not r.ok and r.diagnostics["infeasible_cells"][0]["eligible_items"] == 0


def test_large_pool_assembles_quickly_and_verifies():
    pool = [PoolItem(i, f"I{i}", ("QUANT", "LOGICAL", "VERBAL")[i % 3], ("easy", "medium", "hard")[(i // 3) % 3], i // 2) for i in range(6000)]
    cfg = AssemblyConfig(30, {"QUANT": 15, "LOGICAL": 15, "VERBAL": 15},
                         {s: {"easy": 0.3, "medium": 0.4, "hard": 0.3} for s in ("QUANT", "LOGICAL", "VERBAL")}, seed=3)
    t = time.perf_counter()
    r = assemble(pool, cfg)
    assert r.ok and r.diagnostics["violations"] == [] and time.perf_counter() - t < 20


def test_zero_percent_overlap_with_tiny_pool_is_infeasible_not_relaxed():
    pool = [PoolItem(i, f"I{i}", "QUANT", "medium", i) for i in range(4)]
    cfg = AssemblyConfig(3, {"QUANT": 3}, {"QUANT": {"easy": 0, "medium": 1, "hard": 0}}, max_adjacent_overlap_pct=0,
                         max_slot_exposures=5, min_slot_spacing=0, separate_families_adjacent=False)
    r = assemble(pool, cfg)
    assert not r.ok  # 3 items/form, 4 items total, no sharing allowed between adjacent forms
