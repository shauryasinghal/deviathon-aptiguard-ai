"""Persisted test-form assembly on top of the pure algorithm."""
from __future__ import annotations

import hashlib
import time
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AssemblyRun, CalibrationRun, FormItem, ItemCalibration, Question, Section, Slot, TestForm, User
from app.services import audit
from app.services.assembly.algorithm import AssemblyConfig, PoolItem, assemble, quotas
from app.services.exposure.service import eligibility, exposure_stats
from app.services.policies import get_policy

DEFAULT_MIX = {"easy": 0.3, "medium": 0.4, "hard": 0.3}


def calibrated_bands(db: Session, org_id: int) -> dict[int, str]:
    run = db.scalar(select(CalibrationRun).where(CalibrationRun.org_id == org_id, CalibrationRun.rasch_fitted.is_(True))
                    .order_by(CalibrationRun.id.desc()))
    if not run:
        return {}
    cut = (run.params or {}).get("band_cutoffs_b", [-0.5, 0.5])
    rows = db.execute(select(ItemCalibration.question_id, ItemCalibration.rasch_b, ItemCalibration.status)
                      .where(ItemCalibration.run_id == run.id, ItemCalibration.rasch_b.is_not(None))).all()
    return {qid: ("easy" if b < cut[0] else "hard" if b > cut[1] else "medium")
            for qid, b, st in rows if st not in ("insufficient_data",)}


def build_pool(db: Session, org_id: int, exposure_overrides: dict | None = None, use_calibrated_bands: bool = True):
    pol = {**get_policy(db, org_id, "exposure"), **(exposure_overrides or {})}
    qs = db.scalars(select(Question).where(Question.org_id == org_id)).all()
    stats = exposure_stats(db, org_id)
    bands = calibrated_bands(db, org_id) if use_calibrated_bands else {}
    pool, excluded = [], {}
    for q in qs:
        ok, why = eligibility(q, stats.get(q.id), pol)
        if not ok:
            excluded[why] = excluded.get(why, 0) + 1
            continue
        s = stats.get(q.id)
        pool.append(PoolItem(q.id, q.code, q.section.code, bands.get(q.id, q.difficulty_target), q.family_id,
                             s.slot_count if s else 0, s.candidate_exposures if s else 0))
    return pool, excluded, pol


def preview(db: Session, org_id: int, per_section: dict[str, int] | None = None, n_slots: int = 10,
            difficulty_mix: dict | None = None) -> dict:
    pool, excluded, pol = build_pool(db, org_id)
    cells = {}
    for p in pool:
        cells.setdefault(p.section, {}).setdefault(p.band, {"items": 0, "families": set()})
        cells[p.section][p.band]["items"] += 1
        cells[p.section][p.band]["families"].add(p.family_id)
    out = {sec: {b: {"items": v["items"], "families": len(v["families"])} for b, v in bands.items()} for sec, bands in cells.items()}
    need = None
    if per_section:
        need = {sec: quotas(n, (difficulty_mix or {}).get(sec, DEFAULT_MIX)) for sec, n in per_section.items()}
    return {"eligible_items": len(pool), "excluded": excluded, "by_section_band": out, "per_form_quota": need,
            "n_slots": n_slots, "exposure_policy": pol}


def run_assembly(db: Session, org_id: int, user: User | None, cfg_in: dict) -> AssemblyRun:
    t0 = time.perf_counter()
    apol = get_policy(db, org_id, "assembly")
    epol = get_policy(db, org_id, "exposure")
    per_section = cfg_in.get("per_section") or {"QUANT": 10, "LOGICAL": 10, "VERBAL": 10}
    mix = cfg_in.get("difficulty_mix") or {}
    cfg = AssemblyConfig(
        n_slots=int(cfg_in.get("n_slots", 10)), per_section=per_section,
        difficulty_mix={sec: mix.get(sec, DEFAULT_MIX) for sec in per_section},
        max_adjacent_overlap_pct=float(cfg_in.get("max_adjacent_overlap_pct", apol["max_adjacent_overlap_pct"])),
        max_slot_exposures=int(cfg_in.get("max_slot_exposures", epol["max_slot_exposures"])),
        min_slot_spacing=int(cfg_in.get("min_slot_spacing", epol["min_slot_spacing"])),
        separate_families_adjacent=bool(cfg_in.get("separate_families_adjacent", apol["separate_families_adjacent"])),
        forms_per_slot=int(cfg_in.get("forms_per_slot", 1)), seed=int(cfg_in.get("seed", 107)),
        max_backtracks=int(apol["max_backtracks"]),
    )
    pool, excluded, _ = build_pool(db, org_id, {"max_slot_exposures": cfg.max_slot_exposures})
    result = assemble(pool, cfg, excluded)
    drive = cfg_in.get("drive") or "Unnamed drive"
    weights = cfg_in.get("section_weights") or {sec: 1.0 for sec in per_section}
    duration = int(cfg_in.get("duration_minutes", 40))
    config_record = {**cfg.__dict__, "section_weights": weights, "duration_minutes": duration, "drive": drive,
                     "start_date": cfg_in.get("start_date")}
    run = AssemblyRun(org_id=org_id, created_by=user.id if user else None, drive=drive, seed=cfg.seed,
                      config=config_record, status="succeeded" if result.ok else "failed",
                      diagnostics=result.diagnostics, overlap=[])
    db.add(run)
    db.flush()
    if result.ok:
        start = datetime.fromisoformat(cfg_in["start_date"]) if cfg_in.get("start_date") else datetime(2026, 11, 9, 4, 0)
        slots = _ensure_slots(db, org_id, drive, cfg.n_slots, start)
        pmap = {p.id: p for p in pool}
        sec_order = {s.code: i for i, s in enumerate(db.scalars(select(Section).order_by(Section.id)).all())}
        band_order = {"easy": 0, "medium": 1, "hard": 2}
        forms: list[TestForm] = []
        for f in result.forms:
            slot = slots[f["slot_index"]]
            code = f"{_drive_code(drive)}-R{run.id}-S{slot.sequence:02d}-F{f['form_index'] + 1}"
            items = sorted(f["item_ids"], key=lambda i: (sec_order[pmap[i].section], band_order[pmap[i].band], pmap[i].code))
            form = TestForm(code=code, slot_id=slot.id, assembly_run_id=run.id, seed=cfg.seed, status="draft",
                            duration_minutes=duration, is_synthetic=False)
            form.items = [FormItem(question_id=i, section_id=_section_id(db, pmap[i].section), position=k)
                          for k, i in enumerate(items)]
            sec_dist, band_dist = {}, {}
            for i in items:
                sec_dist[pmap[i].section] = sec_dist.get(pmap[i].section, 0) + 1
                key = f"{pmap[i].section}/{pmap[i].band}"
                band_dist[key] = band_dist.get(key, 0) + 1
            form.validation = {"status": "verified", "section_distribution": sec_dist, "difficulty_distribution": band_dist,
                               "mean_prior_slot_exposure": round(sum(pmap[i].prior_slots for i in items) / len(items), 3),
                               "max_prior_slot_exposure": max(pmap[i].prior_slots for i in items),
                               "section_weights": weights, "seed": cfg.seed}
            db.add(form)
            forms.append(form)
        db.flush()
        run.overlap = [{**o, "form_a": forms[o["a"]].code, "form_b": forms[o["b"]].code,
                        "slot_a": slots[result.forms[o["a"]]["slot_index"]].sequence,
                        "slot_b": slots[result.forms[o["b"]]["slot_index"]].sequence} for o in result.overlap]
    run.duration_ms = int((time.perf_counter() - t0) * 1000)
    audit.record(db, user, "assembly.run", "assembly_run", run.id,
                 f"Assembly for '{drive}' {run.status} ({cfg.n_slots} slots, seed {cfg.seed}): "
                 f"{result.diagnostics.get('explanation', '')}"[:400])
    return run


def _drive_code(drive: str) -> str:
    return "".join(ch for ch in drive.upper() if ch.isalnum())[:10] or "DRIVE"


def _section_id(db: Session, code: str) -> int:
    return db.scalar(select(Section.id).where(Section.code == code))


def _ensure_slots(db: Session, org_id: int, drive: str, n: int, start: datetime) -> list[Slot]:
    # Slots belong to one organisation: another tenant's drive of the same name must never be reused or extended.
    existing = {s.sequence: s for s in db.scalars(select(Slot).where(Slot.org_id == org_id, Slot.drive == drive)).all()}
    slots = []
    for k in range(1, n + 1):
        if k in existing:
            slots.append(existing[k])
            continue
        day, half = divmod(k - 1, 2)
        st = start + timedelta(days=day, hours=5 * half)
        code = f"{_drive_code(drive)}-{hashlib.sha1(drive.encode()).hexdigest()[:4].upper()}-S{k:02d}"
        if db.scalar(select(Slot.id).where(Slot.code == code)):  # slot codes share one namespace across tenants
            code = f"{code}-O{org_id}"
        s = Slot(org_id=org_id, code=code, drive=drive, sequence=k,
                 name=f"{drive} · Slot {k}", starts_at=st, ends_at=st + timedelta(hours=1), status="scheduled",
                 is_synthetic=False)
        db.add(s)
        slots.append(s)
        db.flush()
    return slots


def run_comparability(db: Session, org_id: int, forms: list[TestForm]) -> dict:
    """Advisory comparability of the forms of one run, from the latest Rasch calibration (see comparability.py)."""
    from app.services.assembly.comparability import compare_forms, form_difficulty
    from app.services.calibration.service import equivalence_decision

    pol = get_policy(db, org_id, "calibration")
    run = db.scalar(select(CalibrationRun).where(CalibrationRun.org_id == org_id, CalibrationRun.rasch_fitted.is_(True))
                    .order_by(CalibrationRun.id.desc()))
    cal = {}
    if run:
        cal = {qid: (b, se) for qid, b, se in db.execute(
            select(ItemCalibration.question_id, ItemCalibration.rasch_b, ItemCalibration.rasch_se)
            .where(ItemCalibration.run_id == run.id, ItemCalibration.rasch_b.is_not(None),
                   ItemCalibration.rasch_se.is_not(None))).all()}
    per_form = {f.code: form_difficulty([cal.get(fi.question_id) for fi in f.items]) for f in forms}
    out = compare_forms(per_form, float(pol["tolerance_logits"]), equivalence_decision)
    out["calibration_run_id"] = run.id if run else None
    return out


def publish_run(db: Session, run: AssemblyRun, user: User | None) -> int:
    return publish_checked(db, run, user)["published"]


_ = func


# ------------------------------------------------------------------ form integrity after item withdrawal
WITHDRAWN_LEAK = ("suspected", "confirmed")


def item_ineligible_reason(q: Question) -> str | None:
    if q.status != "approved":
        return f"status '{q.status}'"
    if q.leak_status in WITHDRAWN_LEAK:
        return f"leak status '{q.leak_status}'"
    return None


def flag_forms_for_item(db: Session, question_id: int, reason: str, user: User | None = None) -> list[str]:
    """Mark every non-historical form containing the item as needing reassessment; blocks new attempts.
    Attempts already started on those forms continue and are flagged for staff review (see services.assessment)."""
    from app.services.assessment import flag_attempts_for_item

    flag_attempts_for_item(db, question_id, reason, user)
    forms = db.scalars(select(TestForm).join(FormItem, FormItem.form_id == TestForm.id)
                       .where(FormItem.question_id == question_id, TestForm.status.in_(("draft", "published")))).all()
    codes = []
    for f in forms:
        v = dict(f.validation or {})
        v["reassessment"] = {"previous_status": f.status, "reason": reason, "question_id": question_id}
        f.validation = v
        f.status = "needs_review"
        codes.append(f.code)
    if codes:
        audit.record(db, user, "assembly.forms_flagged", "question", question_id,
                     f"{len(codes)} form(s) flagged for reassessment: {reason}"[:400], {"forms": codes})
    return codes


def restore_forms_if_clean(db: Session, question_id: int, user: User | None = None) -> list[str]:
    """After an item is released, restore flagged forms only if *all* their items are eligible again."""
    from app.services.assessment import note_item_released

    note_item_released(db, question_id, user)
    forms = db.scalars(select(TestForm).join(FormItem, FormItem.form_id == TestForm.id)
                       .where(FormItem.question_id == question_id, TestForm.status == "needs_review")).all()
    restored = []
    for f in forms:
        if any(item_ineligible_reason(db.get(Question, fi.question_id)) for fi in f.items):
            continue
        v = dict(f.validation or {})
        prev = (v.pop("reassessment", None) or {}).get("previous_status", "draft")
        f.validation, f.status = v, prev
        restored.append(f.code)
    if restored:
        audit.record(db, user, "assembly.forms_restored", "question", question_id,
                     f"{len(restored)} form(s) restored after item release", {"forms": restored})
    return restored


def publish_checked(db: Session, run: AssemblyRun, user: User | None) -> dict:
    """Publish draft forms of a verified run, re-checking every item's eligibility at publish time."""
    forms = db.scalars(select(TestForm).where(TestForm.assembly_run_id == run.id)).all()
    published, blocked = [], []
    for f in forms:
        if f.status != "draft":
            continue
        bad = [(db.get(Question, fi.question_id).code, item_ineligible_reason(db.get(Question, fi.question_id)))
               for fi in f.items]
        bad = [b for b in bad if b[1]]
        if bad:
            blocked.append({"form": f.code, "items": [{"code": c, "reason": r} for c, r in bad]})
            continue
        f.status = "published"
        published.append(f.code)
    audit.record(db, user, "assembly.published", "assembly_run", run.id,
                 f"Published {len(published)} form(s) of run #{run.id}; {len(blocked)} blocked")
    return {"published": len(published), "blocked": blocked}
