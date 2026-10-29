"""Text normalization and similarity used by duplicate detection and leak matching.

Scores (all in [0, 1]):
* exact        – normalized texts identical
* containment  – share of the item's word 3-shingles found in the candidate text (robust to extra chatter around a pasted question)
* char_cosine  – TF-IDF cosine over character 3–5-grams (robust to typos / light paraphrase)
* token_jaccard– Jaccard over word sets
* masked_*     – same metrics after replacing every number with '#', used to detect *family/template* level matches
"""
from __future__ import annotations

import hashlib
import re
import unicodedata

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

_PUNCT = re.compile(r"[^\w\s#%₹/.]", re.UNICODE)
_WS = re.compile(r"\s+")
_NUM = re.compile(r"\d+(?:[.,]\d+)*")


def normalize(text: str) -> str:
    t = unicodedata.normalize("NFKC", text or "").lower()
    t = re.sub(r"\b(?:rs\.?|inr)\s*(?=\d)", "₹", t)  # Rs. 400 / INR 400 / rs400 -> ₹400
    t = re.sub(r"₹\s+", "₹", t)
    t = _PUNCT.sub(" ", t)
    t = re.sub(r"(?<!\d)\.(?!\d)", " ", t)
    return _WS.sub(" ", t).strip()


def mask_numbers(norm_text: str) -> str:
    return _NUM.sub("#", norm_text)


def text_hash(text: str) -> str:
    return hashlib.sha256(normalize(text).encode()).hexdigest()


def shingles(norm_text: str, k: int = 3) -> set[tuple[str, ...]]:
    toks = norm_text.split()
    if len(toks) < k:
        return {tuple(toks)} if toks else set()
    return {tuple(toks[i : i + k]) for i in range(len(toks) - k + 1)}


def containment(item_norm: str, other_norm: str, k: int = 3) -> float:
    a = shingles(item_norm, k)
    if not a:
        return 0.0
    return len(a & shingles(other_norm, k)) / len(a)


def token_jaccard(a: str, b: str) -> float:
    sa, sb = set(a.split()), set(b.split())
    return len(sa & sb) / len(sa | sb) if sa | sb else 0.0


def char_cosine_matrix(left: list[str], right: list[str]) -> np.ndarray:
    """Cosine similarity of char 3–5-gram TF-IDF vectors; vocabulary fitted on both sides."""
    if not left or not right:
        return np.zeros((len(left), len(right)))
    vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True, min_df=1)
    m = vec.fit_transform(left + right)
    a, b = m[: len(left)], m[len(left) :]
    return (a @ b.T).toarray()


def item_fulltext(stem: str, options: list[str]) -> str:
    return stem + " " + " ".join(options)
