"""Shared types for deterministic, verifiable item templates.

A template turns (difficulty, rng) into a fully specified item *and* the parameters needed to
re-derive the answer independently. `verify()` never trusts the stored answer key: it recomputes.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Callable

KEYS = ["A", "B", "C", "D"]
TEMPLATE_VERSION = "1.2"


@dataclass
class Check:
    check: str
    status: str  # pass | warn | fail
    message: str
    severity: str = "info"  # info | warning | critical
    details: dict | None = None


@dataclass
class GeneratedItem:
    section: str
    template_id: str
    concept: str
    skill: str
    difficulty: str
    stem: str
    options: list[dict]  # {key, text, is_correct, rationale}
    explanation: str
    params: dict
    tags: list[str] = field(default_factory=list)
    review_requirement: str | None = None
    template_version: str = TEMPLATE_VERSION

    @property
    def correct_key(self) -> str | None:
        keys = [o["key"] for o in self.options if o["is_correct"]]
        return keys[0] if len(keys) == 1 else None

    @property
    def correct_text(self) -> str | None:
        for o in self.options:
            if o["is_correct"]:
                return o["text"]
        return None


@dataclass
class Template:
    id: str
    section: str
    concept: str
    skill: str
    generate: Callable[[random.Random, str], GeneratedItem]
    verify: Callable[[dict, "GeneratedItem"], list[Check]]


def fmt_num(x: float | Fraction | int, unit: str = "", decimals: int = 2) -> str:
    if isinstance(x, Fraction):
        if x.denominator == 1:
            s = str(x.numerator)
        else:
            f = float(x)
            s = f"{f:.{decimals}f}".rstrip("0").rstrip(".")
    elif isinstance(x, int) or float(x).is_integer():
        s = str(int(round(float(x))))
    else:
        s = f"{float(x):.{decimals}f}".rstrip("0").rstrip(".")
    if s.startswith("-") and float(s) == 0:
        s = s[1:]
    return f"{s}{unit}" if unit in ("%",) else (f"{s} {unit}".strip() if unit else s)


def build_options(
    rng: random.Random, correct: str, distractors: list[tuple[str, str]], fallback: Callable[[int], str] | None = None
) -> list[dict]:
    """Shuffle one correct answer with three *distinct* distractors (text, rationale)."""
    seen = {correct.strip().lower()}
    picked: list[tuple[str, str]] = []
    for text, why in distractors:
        k = text.strip().lower()
        if k not in seen:
            seen.add(k)
            picked.append((text, why))
        if len(picked) == 3:
            break
    i = 1
    while len(picked) < 3 and fallback is not None and i < 50:
        cand = fallback(i)
        if cand.strip().lower() not in seen:
            seen.add(cand.strip().lower())
            picked.append((cand, "Plausible magnitude distractor"))
        i += 1
    entries = [(correct, True, "Correct")] + [(t, False, w) for t, w in picked]
    rng.shuffle(entries)
    return [
        {"key": KEYS[i], "text": t, "is_correct": c, "rationale": w}
        for i, (t, c, w) in enumerate(entries)
    ]


def expect_correct(item: GeneratedItem, expected_text: str, label: str) -> list[Check]:
    checks: list[Check] = []
    actual = item.correct_text
    if actual is None:
        return [Check("answer_recomputed", "fail", "No single correct option to verify", "critical")]
    if actual.strip().lower() == expected_text.strip().lower():
        checks.append(Check("answer_recomputed", "pass", f"Recomputed {label} = {expected_text}; matches key",
                            details={"expected": expected_text}))
    else:
        checks.append(Check("answer_recomputed", "fail",
                            f"Key says '{actual}' but recomputation gives '{expected_text}'", "critical",
                            {"expected": expected_text, "key": actual}))
    for o in item.options:
        if not o["is_correct"] and o["text"].strip().lower() == expected_text.strip().lower():
            checks.append(Check("distractor_not_correct", "fail",
                                f"Distractor {o['key']} equals the correct value", "critical"))
    return checks


def pick(rng: random.Random, seq):
    return seq[rng.randrange(len(seq))]
