"""Configurable policies with safe defaults. All thresholds used by algorithms live here."""
from __future__ import annotations

import copy

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Policy

DEFAULT_POLICIES: dict[str, dict] = {
    "exposure": {
        "max_slot_exposures": 3,          # distinct slots an item may appear in before it is ineligible
        "max_candidate_exposures": 600,   # candidates who have seen the item
        "min_slot_spacing": 2,            # an item reused must skip at least this many slots
        "warn_ratio": 0.67,               # exposure-risk warning once usage reaches this share of the limit
        "exclude_leak_statuses": ["suspected", "confirmed"],
    },
    "assembly": {
        "max_adjacent_overlap_pct": 10.0,  # % of the smaller form shared with an adjacent slot's form
        "separate_families_adjacent": True,
        "max_backtracks": 200,
    },
    "calibration": {
        "min_responses": 60,               # below: "insufficient data"
        "min_responses_rasch": 100,
        "tolerance_logits": 0.5,            # equivalence margin (logits) for variant-vs-source difficulty (TOST, 90% CI)
        "tolerance_p": 0.08,               # preliminary CTT margin when Rasch is unavailable
        "min_item_rest_r": 0.15,
        "band_cutoffs_b": [-0.5, 0.5],     # Rasch b → easy / medium / hard
        "exclude_leaked_from_rasch": True,  # contaminated anchors bias equating
    },
    "leak": {
        "text_exact_threshold": 0.92,      # 3-shingle containment of the item stem in the record
        "text_similar_threshold": 0.85,    # windowed char-n-gram cosine (stem + options) for paraphrase / OCR noise
        "family_template_threshold": 0.80, # same score after masking numbers (template-level exposure)
        "fdr_alpha": 0.05,
        "min_effect_delta": 1.0,           # |ETS MH delta| >= 1.0 (moderate DIF) to raise
        "min_rt_ratio": 0.75,              # later/baseline median RT below this is a speed-up signal
        "baseline_slots": 2,
        "min_group_n": 40,
    },
    "review": {
        "require_independent_reviewer": True,   # creator of an item may not approve it
        "verbal_requires_second_look": True,
    },
    "assessment": {
        "enforce_slot_window": True,     # candidates may only start inside their slot's window
        "early_entry_minutes": 15,
        "late_entry_minutes": 30,        # after slot start
        "deadline_mode": "full_duration",  # full_duration: start + duration | slot_end: also capped at slot end
    },
    "retention": {
        "response_retention_days": 365,
        "audit_retention_days": 730,
        "pseudonymize_candidates": True,
    },
}


ENUM_FIELDS = {"assessment": {"deadline_mode": ("full_duration", "slot_end")}}


def get_policy(db: Session, org_id: int, key: str) -> dict:
    row = db.scalar(select(Policy).where(Policy.org_id == org_id, Policy.key == key))
    merged = copy.deepcopy(DEFAULT_POLICIES.get(key, {}))
    if row:
        merged.update(row.value)
    return merged


def all_policies(db: Session, org_id: int) -> dict[str, dict]:
    return {k: get_policy(db, org_id, k) for k in DEFAULT_POLICIES}


def set_policy(db: Session, org_id: int, key: str, value: dict, user_id: int | None) -> dict:
    if key not in DEFAULT_POLICIES:
        raise KeyError(key)
    unknown = set(value) - set(DEFAULT_POLICIES[key])
    if unknown:
        raise ValueError(f"Unknown policy fields: {sorted(unknown)}")
    for field, allowed in ENUM_FIELDS.get(key, {}).items():
        if field in value and value[field] not in allowed:
            raise ValueError(f"{key}.{field} must be one of {allowed}")
    row = db.scalar(select(Policy).where(Policy.org_id == org_id, Policy.key == key))
    current = get_policy(db, org_id, key)
    current.update(value)
    if row:
        row.value = current
        row.updated_by = user_id
    else:
        db.add(Policy(org_id=org_id, key=key, value=current, updated_by=user_id))
    return current
