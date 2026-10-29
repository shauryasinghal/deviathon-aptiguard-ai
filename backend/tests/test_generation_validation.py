"""Unit tests: templates, deterministic answer verification, duplicate detection, quality gates."""
import random

import pytest

from app.services.generation.base import GeneratedItem
from app.services.generation.logical import _solutions, follows
from app.services.generation.registry import TEMPLATES, generate
from app.services.textsim import item_fulltext, normalize, text_hash
from app.services.validation.validator import (
    BankEntry,
    answer_checks,
    duplicate_checks,
    overall,
    safe_eval,
    structural_checks,
    validate,
)


@pytest.mark.parametrize("tid", sorted(TEMPLATES))
@pytest.mark.parametrize("band", ["easy", "medium", "hard"])
def test_every_template_generates_valid_items(tid, band):
    for seed in range(25):
        item = generate(tid, band, seed)
        checks = structural_checks(item) + answer_checks(item, "template")
        fails = [c.message for c in checks if c.status == "fail"]
        assert not fails, f"{tid}/{band}/{seed}: {fails}"
        assert item.section in ("QUANT", "LOGICAL", "VERBAL")
        assert sum(o["is_correct"] for o in item.options) == 1
        assert item.explanation and item.skill


def test_generation_is_deterministic():
    a, b = generate("QT-PCT", "medium", 7), generate("QT-PCT", "medium", 7)
    assert a.stem == b.stem and a.options == b.options


@pytest.mark.parametrize("tid", ["QT-SDT", "QT-INT", "LG-CODE", "LG-ORDER", "VB-SVA"])
def test_corrupted_answer_key_is_rejected(tid):
    item = generate(tid, "medium", 3)
    wrong = next(o for o in item.options if not o["is_correct"])
    for o in item.options:
        o["is_correct"] = o["key"] == wrong["key"]
    checks = answer_checks(item, "template")
    assert any(c.check == "answer_recomputed" and c.status == "fail" for c in checks)
    assert overall(checks) == "failed"


def test_two_correct_options_fail_structure():
    item = generate("QT-WORK", "easy", 1)
    item.options[0]["is_correct"] = item.options[1]["is_correct"] = True
    assert any(c.check == "single_correct" and c.status == "fail" for c in structural_checks(item))


def test_numerically_equivalent_options_fail():
    item = GeneratedItem("QUANT", "", "c", "s", "easy", "What is half of ten apples here?",
                         [{"key": "A", "text": "5", "is_correct": True}, {"key": "B", "text": "5.0", "is_correct": False},
                          {"key": "C", "text": "6", "is_correct": False}, {"key": "D", "text": "7", "is_correct": False}],
                         "Half of ten is five.", {})
    assert any(c.check == "options_distinct" and c.status == "fail" for c in structural_checks(item))


def test_three_options_fail():
    item = generate("QT-WORK", "easy", 2)
    item.options = item.options[:3]
    assert any(c.check == "option_count" and c.status == "fail" for c in structural_checks(item))


def test_syllogism_model_checker():
    # All S are M, All M are P  =>  All S are P ; but not All P are S
    prem = [("all", 0, 1), ("all", 1, 2)]
    assert follows(prem, ("all", 0, 2))
    assert not follows(prem, ("all", 2, 0))
    assert follows(prem, ("some", 2, 0))  # existential import: some P are S
    # No S are M, All M are P  =>  nothing definite about S and P being disjoint
    assert not follows([("no", 0, 1), ("all", 1, 2)], ("no", 0, 2))


def test_ordering_ambiguity_detected():
    names = ["A", "B", "C", "D"]
    assert len(_solutions(names, [("A", "B"), ("B", "C"), ("C", "D")])) == 1
    assert len(_solutions(names, [("A", "B"), ("C", "D")])) > 1  # ambiguous


def test_ambiguous_ordering_item_fails_verification():
    item = generate("LG-ORDER", "medium", 11)
    p = dict(item.params)
    p["clues"] = p["clues"][:1]  # drop clues -> ambiguous
    checks = TEMPLATES["LG-ORDER"].verify(p, item)
    assert any(c.check == "unique_answer" and c.status == "fail" for c in checks)


def test_safe_eval():
    assert float(safe_eval("2*(3+4)/7")) == 2.0
    for bad in ["__import__('os')", "a+1", "2**100", "open('x')"]:
        with pytest.raises((ValueError, SyntaxError)):
            safe_eval(bad)


def _entry(item, id_, code):
    full = item_fulltext(item.stem, [o["text"] for o in item.options])
    return BankEntry(id_, code, normalize(full), text_hash(full), item.template_id, item.params)


def test_exact_duplicate_rejected():
    item = generate("QT-RATIO", "easy", 5)
    checks = duplicate_checks(item, [_entry(item, 1, "X-1")])
    assert checks[0].status == "fail"


def test_answer_equivalent_clone_rejected():
    """Same numbers, different names → same answer → must be treated as a duplicate."""
    a = generate("QT-WORK", "easy", 1)
    rng = random.Random(0)
    for s in range(2, 4000):
        b = generate("QT-WORK", "easy", s)
        if b.params["days"] == a.params["days"] and b.params["names"] != a.params["names"]:
            break
    else:
        pytest.skip("no clone pair found")
    _ = rng
    checks = duplicate_checks(b, [_entry(a, 1, "X-1")])
    assert checks[0].status == "fail" and "clone" in checks[0].message


def test_near_duplicate_rejected():
    a = generate("VB-INFER", "medium", 3)
    b = GeneratedItem(**{**a.__dict__})
    b.stem = a.stem.replace("Last quarter", "In the last quarter")
    b.params = {**a.params, "manual": True}
    checks = duplicate_checks(b, [_entry(a, 1, "X-1")])
    assert checks[0].status == "fail" and checks[0].check == "duplicate_near"


def test_distinct_variant_passes_duplicate_check():
    a, b = generate("QT-SDT", "easy", 1), generate("QT-SDT", "easy", 99)
    assert duplicate_checks(b, [_entry(a, 1, "X-1")])[0].status in ("pass", "warn")


def test_verbal_items_always_flagged_for_human_review():
    status, checks = validate(generate("VB-SYN", "medium", 4), [], "template")
    assert status == "warning"
    assert any(c.check == "linguistic_review" for c in checks)


def test_difficulty_mismatch_warns_not_parallel():
    _, checks = validate(generate("QT-INT", "hard", 4), [], "template", source_difficulty="easy")
    assert any(c.check == "parallel_difficulty" and c.status == "warn" for c in checks)
