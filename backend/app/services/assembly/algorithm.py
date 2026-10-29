"""Exposure-aware multi-slot test assembly (pure, DB-free, deterministic for a given seed).

Algorithm
1. Pre-flight capacity check per (section, difficulty band): required item-uses vs. what the pool can supply
   under the exposure limit and minimum reuse spacing. Infeasible plans fail fast with the bottleneck named.
2. Build slots in order. For each form fill integer quotas (section × band, largest-remainder rounding) by
   picking the eligible item with the lowest (prior exposure + planned uses), ties broken by a seeded jitter.
   Hard constraints checked on every pick: approved & not leaked (pre-filtered), one item per variant family per
   form, optional family separation across adjacent slots, exposure budget, reuse spacing, adjacent-overlap budget.
3. If a quota cannot be filled, re-randomize the slot (bounded retries), then backtrack one slot; give up after
   `max_backtracks` with a constraint-elimination report for the failing cell.
4. Verify the finished plan independently (`verify_plan`) — the plan is rejected if any hard constraint fails.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

BANDS = ("easy", "medium", "hard")


@dataclass
class PoolItem:
    id: int
    code: str
    section: str
    band: str
    family_id: int
    prior_slots: int = 0
    prior_candidates: int = 0


@dataclass
class AssemblyConfig:
    n_slots: int
    per_section: dict[str, int]
    difficulty_mix: dict[str, dict[str, float]]  # section -> band -> proportion
    max_adjacent_overlap_pct: float = 10.0
    max_slot_exposures: int = 3
    min_slot_spacing: int = 2
    separate_families_adjacent: bool = True
    forms_per_slot: int = 1
    seed: int = 107
    max_backtracks: int = 200
    retries_per_slot: int = 6


@dataclass
class AssemblyResult:
    ok: bool
    forms: list[dict] = field(default_factory=list)  # {slot_index, form_index, item_ids}
    overlap: list[dict] = field(default_factory=list)
    diagnostics: dict = field(default_factory=dict)


def quotas(n: int, mix: dict[str, float]) -> dict[str, int]:
    total = sum(mix.get(b, 0) for b in BANDS) or 1
    raw = {b: n * mix.get(b, 0) / total for b in BANDS}
    q = {b: int(math.floor(v)) for b, v in raw.items()}
    for b in sorted(BANDS, key=lambda b: -(raw[b] - q[b]))[: n - sum(q.values())]:
        q[b] += 1
    return q


def overlap_stats(a: set[int], b: set[int]) -> dict:
    shared = len(a & b)
    union = len(a | b)
    smaller = min(len(a), len(b)) or 1
    return {"shared": shared, "jaccard": round(shared / union, 4) if union else 0.0,
            "smaller_form_pct": round(100 * shared / smaller, 2)}


def _allowed_shared(form_size: int, pct: float) -> int:
    return int(math.floor(form_size * pct / 100 + 1e-9))


def preflight(pool: list[PoolItem], cfg: AssemblyConfig) -> list[dict]:
    issues = []
    total_forms = cfg.n_slots * cfg.forms_per_slot
    max_uses_by_spacing = math.ceil(cfg.n_slots / (cfg.min_slot_spacing + 1)) if cfg.min_slot_spacing >= 0 else cfg.n_slots
    for sec, n in cfg.per_section.items():
        qs = quotas(n, cfg.difficulty_mix.get(sec, {"medium": 1}))
        for band, k in qs.items():
            if k == 0:
                continue
            cell = [p for p in pool if p.section == sec and p.band == band]
            families = {p.family_id for p in cell}
            capacity = sum(max(0, min(cfg.max_slot_exposures - p.prior_slots, max_uses_by_spacing)) for p in cell)
            need = k * total_forms
            if capacity < need or len(families) < k:
                issues.append({
                    "section": sec, "band": band, "required_item_uses": need, "available_item_uses": capacity,
                    "eligible_items": len(cell), "distinct_families": len(families), "per_form_quota": k,
                    "reason": (f"Need {need} {band} {sec} item-uses ({k} per form × {total_forms} forms) but the eligible "
                               f"pool supplies {capacity} under exposure limit {cfg.max_slot_exposures} and spacing "
                               f"{cfg.min_slot_spacing}" if capacity < need else
                               f"Only {len(families)} distinct families for a per-form quota of {k}"),
                })
    return issues


class _Planner:
    def __init__(self, pool: list[PoolItem], cfg: AssemblyConfig):
        self.pool, self.cfg = pool, cfg
        self.by_cell: dict[tuple[str, str], list[PoolItem]] = {}
        for p in pool:
            self.by_cell.setdefault((p.section, p.band), []).append(p)
        self.form_size = sum(cfg.per_section.values())
        self.allowed_shared = _allowed_shared(self.form_size, cfg.max_adjacent_overlap_pct)
        self.backtracks = 0
        self.failure: dict | None = None

    def _uses(self, plan: list[list[set[int]]], item_id: int) -> list[int]:
        return [si for si, forms in enumerate(plan) for f in forms if item_id in f]

    def build_form(self, plan, si, rng) -> set[int] | None:
        cfg = self.cfg
        chosen: set[int] = set()
        fams: set[int] = set()
        prev_forms = plan[si - 1] if si > 0 else []
        same_slot = plan[si] if si < len(plan) else []
        prev_items = set().union(*prev_forms) if prev_forms else set()
        prev_fams = {p.family_id for p in self.pool if p.id in prev_items} if cfg.separate_families_adjacent else set()
        used = {}
        for forms in plan:
            for f in forms:
                for i in f:
                    used[i] = used.get(i, 0) + 1
        for sec, n in cfg.per_section.items():
            for band, k in quotas(n, cfg.difficulty_mix.get(sec, {"medium": 1})).items():
                if k == 0:
                    continue
                cands = self.by_cell.get((sec, band), [])
                elim = {"family_in_form": 0, "family_in_adjacent_slot": 0, "exposure_limit": 0, "reuse_spacing": 0,
                        "adjacent_overlap_budget": 0, "already_in_form": 0}
                ranked = []
                for p in cands:
                    if p.id in chosen:
                        elim["already_in_form"] += 1; continue
                    if p.family_id in fams:
                        elim["family_in_form"] += 1; continue
                    if p.family_id in prev_fams and p.id not in prev_items:
                        elim["family_in_adjacent_slot"] += 1; continue
                    if p.prior_slots + used.get(p.id, 0) >= cfg.max_slot_exposures:
                        elim["exposure_limit"] += 1; continue
                    uses = self._uses(plan, p.id)
                    if uses and cfg.min_slot_spacing > 0 and any(si - u <= cfg.min_slot_spacing for u in uses):
                        elim["reuse_spacing"] += 1; continue
                    neighbours = [f for f in list(prev_forms) + list(same_slot) if p.id in f]
                    if any(len(chosen & f) + 1 > self.allowed_shared for f in neighbours):
                        elim["adjacent_overlap_budget"] += 1; continue
                    ranked.append((p.prior_slots + used.get(p.id, 0) * 1.5 + rng.random() * 0.9, p))
                ranked.sort(key=lambda t: t[0])
                picked = 0
                for _, p in ranked:
                    if picked == k:
                        break
                    if p.family_id in fams:
                        continue
                    chosen.add(p.id); fams.add(p.family_id); picked += 1
                if picked < k:
                    self.failure = {"slot_index": si, "section": sec, "band": band, "quota": k, "filled": picked,
                                    "candidates_in_cell": len(cands), "eliminated_by": elim,
                                    "bottleneck": max(elim, key=elim.get) if any(elim.values()) else "pool_size"}
                    return None
        return chosen

    def run(self) -> list[list[set[int]]] | None:
        cfg = self.cfg
        plan: list[list[set[int]]] = []
        rngs = [random.Random(cfg.seed * 1000 + si) for si in range(cfg.n_slots)]
        tries = [0] * cfg.n_slots
        si = 0
        while si < cfg.n_slots:
            forms = []
            ok = True
            plan.append(forms)
            for _ in range(cfg.forms_per_slot):
                f = self.build_form(plan, si, rngs[si])
                if f is None:
                    ok = False
                    break
                forms.append(f)
            if ok:
                si += 1
                continue
            plan.pop()
            tries[si] += 1
            if tries[si] <= cfg.retries_per_slot:
                continue
            self.backtracks += 1
            if self.backtracks > cfg.max_backtracks or si == 0:
                return None
            tries[si] = 0
            si -= 1
            plan.pop()
        return plan


def verify_plan(plan: list[list[set[int]]], pool: dict[int, PoolItem], cfg: AssemblyConfig) -> list[dict]:
    """Independent re-check of every hard constraint. Returns a list of violations (empty = valid)."""
    v = []
    form_size = sum(cfg.per_section.values())
    allowed = _allowed_shared(form_size, cfg.max_adjacent_overlap_pct)
    uses: dict[int, list[int]] = {}
    for si, forms in enumerate(plan):
        for fi, f in enumerate(forms):
            if len(f) != form_size:
                v.append({"constraint": "form_size", "slot": si + 1, "detail": f"{len(f)} items, expected {form_size}"})
            fams = [pool[i].family_id for i in f]
            if len(fams) != len(set(fams)):
                v.append({"constraint": "one_item_per_family", "slot": si + 1, "detail": "duplicate family in form"})
            for sec, n in cfg.per_section.items():
                got = sum(1 for i in f if pool[i].section == sec)
                if got != n:
                    v.append({"constraint": "section_count", "slot": si + 1, "detail": f"{sec}: {got} != {n}"})
                for band, k in quotas(n, cfg.difficulty_mix.get(sec, {"medium": 1})).items():
                    got_b = sum(1 for i in f if pool[i].section == sec and pool[i].band == band)
                    if got_b != k:
                        v.append({"constraint": "difficulty_mix", "slot": si + 1, "detail": f"{sec}/{band}: {got_b} != {k}"})
            for i in f:
                uses.setdefault(i, []).append(si)
        if si > 0:
            for a in plan[si - 1]:
                for b in forms:
                    st = overlap_stats(a, b)
                    if st["shared"] > allowed:
                        v.append({"constraint": "adjacent_overlap", "slot": si + 1,
                                  "detail": f"{st['smaller_form_pct']}% shared > {cfg.max_adjacent_overlap_pct}%"})
                    if cfg.separate_families_adjacent:
                        fa = {pool[i].family_id for i in a - b}
                        fb = {pool[i].family_id for i in b - a}
                        if fa & fb:
                            v.append({"constraint": "family_separation_adjacent", "slot": si + 1,
                                      "detail": f"{len(fa & fb)} sibling family(ies) in adjacent slots"})
    for i, sl in uses.items():
        if pool[i].prior_slots + len(sl) > cfg.max_slot_exposures:
            v.append({"constraint": "exposure_limit", "item": pool[i].code,
                      "detail": f"{pool[i].prior_slots}+{len(sl)} > {cfg.max_slot_exposures}"})
        for x, y in zip(sl, sl[1:]):
            if 0 < y - x <= cfg.min_slot_spacing:
                v.append({"constraint": "reuse_spacing", "item": pool[i].code, "detail": f"slots {x + 1} and {y + 1}"})
    return v


def assemble(pool: list[PoolItem], cfg: AssemblyConfig, excluded: dict | None = None) -> AssemblyResult:
    diag: dict = {"pool_size": len(pool), "excluded_before_assembly": excluded or {}, "seed": cfg.seed,
                  "allowed_shared_items_adjacent": _allowed_shared(sum(cfg.per_section.values()), cfg.max_adjacent_overlap_pct)}
    issues = preflight(pool, cfg)
    if issues:
        diag["stage"] = "preflight"
        diag["infeasible_cells"] = issues
        diag["explanation"] = "Assembly is infeasible before search: " + issues[0]["reason"]
        return AssemblyResult(False, diagnostics=diag)
    planner = _Planner(pool, cfg)
    plan = planner.run()
    diag["backtracks"] = planner.backtracks
    if plan is None:
        f = planner.failure or {}
        diag["stage"] = "search"
        diag["failure"] = f
        diag["explanation"] = (f"Could not fill {f.get('band')} {f.get('section')} quota ({f.get('filled')}/{f.get('quota')}) "
                               f"for slot {f.get('slot_index', 0) + 1} after {planner.backtracks} backtracks. Main bottleneck: "
                               f"{f.get('bottleneck', 'unknown').replace('_', ' ')}. Relax that constraint or add approved items.")
        return AssemblyResult(False, diagnostics=diag)
    pmap = {p.id: p for p in pool}
    violations = verify_plan(plan, pmap, cfg)
    if violations:
        diag["stage"] = "verification"
        diag["violations"] = violations
        diag["explanation"] = f"Plan rejected: {len(violations)} hard-constraint violation(s) found during verification."
        return AssemblyResult(False, diagnostics=diag)
    forms = [{"slot_index": si, "form_index": fi, "item_ids": sorted(f)} for si, fs in enumerate(plan) for fi, f in enumerate(fs)]
    overlap = []
    for i in range(len(forms)):
        for j in range(i + 1, len(forms)):
            a, b = set(forms[i]["item_ids"]), set(forms[j]["item_ids"])
            st = overlap_stats(a, b)
            adj = abs(forms[i]["slot_index"] - forms[j]["slot_index"]) <= 1
            overlap.append({"a": i, "b": j, "adjacent": adj, **st,
                            "constraint_ok": (not adj) or st["shared"] <= diag["allowed_shared_items_adjacent"]})
    diag["stage"] = "verified"
    diag["violations"] = []
    diag["explanation"] = "All hard constraints verified independently after assembly."
    return AssemblyResult(True, forms, overlap, diag)
