"""Match bank items against records from an authorized leak dataset.

Match levels
* item_exact    – ≥ `text_exact_threshold` of the item's stem word-3-shingles appear in the record, numbers agree
* item_similar  – paraphrase / OCR noise of *this* item: windowed char-n-gram cosine (stem + options) above
                  `text_similar_threshold` with agreeing numbers, OR an identical numeric signature (all stem numbers
                  and ≥3 of 4 option values present) with moderate textual overlap
* family        – the wording template matches once numbers are masked, but the specific item is not reproduced:
                  the *concept/template* is exposed, not this exact item (typical for sibling variants)
Similarity is evidence of textual overlap, not proof of malicious leakage.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import numpy as np

from app.services.textsim import char_cosine_matrix, containment, mask_numbers, normalize

_NUM = re.compile(r"\d+(?:\.\d+)?")
WINDOWS = (10, 20, 40, 70)  # token window sizes for windowed similarity


@dataclass
class ItemText:
    id: int
    code: str
    family_id: int
    stem: str
    options: list[str] = field(default_factory=list)


@dataclass
class RecordText:
    id: int
    external_id: str
    channel: str
    posted_at: object
    text: str


@dataclass
class TextMatch:
    item_id: int
    record_id: int
    level: str
    score: float
    containment: float
    char_cosine: float
    masked_score: float
    number_agreement: float | None
    matched_excerpt: str
    details: dict = field(default_factory=dict)


BOILERPLATE = (
    "which of the following conclusions definitely follows from the statements",
    "which of the following can most reasonably be inferred from the passage",
    "choose the option that correctly completes the sentence",
    "choose the word most nearly the same in meaning to",
    "choose the word most nearly opposite in meaning to",
    "what number comes next in the series",
)


def _stem_core(stem: str) -> str:
    s = normalize(stem)
    for boiler in BOILERPLATE:
        s = s.replace(boiler, " ")
    return " ".join(s.split())


_STOP = {"the", "and", "for", "that", "what", "which", "with", "from", "this", "how", "who", "are", "was", "its", "his", "her"}


def token_recall(stem_core: str, record_tokens: set[str]) -> float:
    """Share of the stem's content words present in the record (fuzzy, tolerant to OCR character errors)."""
    from difflib import SequenceMatcher

    words = [w for w in stem_core.split() if len(w) >= 3 and w not in _STOP and not _NUM.fullmatch(w)]
    if not words:
        return 0.0
    hit = 0
    for w in words:
        if w in record_tokens or any(abs(len(t) - len(w)) <= 1 and SequenceMatcher(None, w, t).ratio() >= 0.75
                                     for t in record_tokens):
            hit += 1
    return hit / len(words)


def _windows(tokens: list[str]) -> list[str]:
    out = []
    for w in WINDOWS:
        if len(tokens) <= w:
            out.append(" ".join(tokens))
            continue
        step = max(1, w // 4)
        out.extend(" ".join(tokens[i : i + w]) for i in range(0, len(tokens) - w + 1, step))
    return list(dict.fromkeys(out))


def _excerpt(record_text: str, item_norm: str, width: int = 240) -> str:
    words = [w for w in item_norm.split() if len(w) > 3][:3]
    low = record_text.lower()
    idx = min([low.find(w) for w in words if low.find(w) >= 0], default=0)
    start = max(0, idx - 30)
    return record_text[start : start + width].strip()


def match_items(items: list[ItemText], records: list[RecordText], thresholds: dict) -> list[TextMatch]:
    if not items or not records:
        return []
    stem_core = [_stem_core(i.stem) for i in items]
    full = [(_stem_core(i.stem) + " " + " ".join(normalize(o) for o in i.options)).strip() for i in items]
    rnorm = [normalize(r.text) for r in records]
    # windowed cosine: items × windows, reduced to items × records by max
    win_texts, win_owner = [], []
    for j, t in enumerate(rnorm):
        for w in _windows(t.split()):
            win_texts.append(w)
            win_owner.append(j)
    win_owner = np.array(win_owner)
    cos_w = char_cosine_matrix(full, win_texts)
    cos = np.zeros((len(items), len(records)))
    for j in range(len(records)):
        cos[:, j] = cos_w[:, win_owner == j].max(axis=1)
    # template-level similarity compares the *stem wording* only (posts often omit options)
    masked_w = char_cosine_matrix([mask_numbers(t) for t in stem_core], [mask_numbers(w) for w in win_texts])
    cos_masked = np.zeros_like(cos)
    for j in range(len(records)):
        cos_masked[:, j] = masked_w[:, win_owner == j].max(axis=1)

    out: list[TextMatch] = []
    for i, it in enumerate(items):
        stem_nums = set(_NUM.findall(stem_core[i]))
        opt_nums = [set(_NUM.findall(normalize(o))) for o in it.options]
        opt_texts = [normalize(o) for o in it.options if len(normalize(o)) >= 3 and not _NUM.fullmatch(normalize(o))]
        for j, rec in enumerate(records):
            if cos_masked[i, j] < 0.45 and cos[i, j] < 0.45:
                continue  # cheap prefilter
            cont = containment(stem_core[i], rnorm[j])
            rnums = set(_NUM.findall(rnorm[j]))
            agree = (len(stem_nums & rnums) / len(stem_nums)) if stem_nums else None
            numbers_ok = agree is None or agree >= 0.75
            opt_hit = sum(1 for s in opt_nums if s and s <= rnums)
            numeric_signature = len(stem_nums) >= 2 and agree == 1.0 and opt_hit >= 3
            opt_text_hit = sum(1 for o in opt_texts if re.search(r"\b" + re.escape(o) + r"\b", rnorm[j]))
            level, why = None, ""
            if cont >= thresholds["text_exact_threshold"] and numbers_ok:
                level, why = "item_exact", "stem reproduced verbatim"
            elif cos[i, j] >= thresholds["text_similar_threshold"] and numbers_ok:
                level, why = "item_similar", "near-verbatim (paraphrase, typos or OCR noise)"
            elif numeric_signature and cos[i, j] >= 0.35:
                level, why = "item_similar", "paraphrase with identical numeric signature (stem numbers and answer options)"
            elif (len(opt_texts) == 4 and opt_text_hit >= 3 and cos[i, j] >= 0.5 and numbers_ok
                  and token_recall(stem_core[i], set(rnorm[j].split())) >= 0.8):
                level, why = "item_similar", f"answer options reproduced ({opt_text_hit}/4) with noisy stem text"
            elif cos_masked[i, j] >= thresholds["family_template_threshold"]:
                level, why = "family", "same wording template with different specifics"
            if level:
                out.append(TextMatch(it.id, rec.id, level, round(max(cont, float(cos[i, j])), 3), round(cont, 3),
                                     round(float(cos[i, j]), 3), round(float(cos_masked[i, j]), 3),
                                     None if agree is None else round(agree, 2), _excerpt(rec.text, stem_core[i]),
                                     {"reason": why, "option_values_found": opt_hit}))
    return out
