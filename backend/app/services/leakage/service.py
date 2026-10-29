"""Leak detection orchestration: combine independent signals into explainable, evidence-backed alerts."""
from __future__ import annotations

import math
import time
from collections import defaultdict

import numpy as np
import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import Conflict, NotFound
from app.db.base import utcnow
from app.models import (
    ExposureEvent,
    Investigation,
    InvestigationEvent,
    LeakAlert,
    LeakDataset,
    LeakDetectionRun,
    LeakRecord,
    Question,
    Slot,
    User,
)
from app.services import audit
from app.services.calibration.service import load_response_frame
from app.services.leakage.stats import ets_class, purified_drift
from app.services.leakage.text_match import ItemText, RecordText, match_items
from app.services.policies import get_policy

SEVERITY_RANK = {"critical": 4, "high": 3, "medium": 2, "low": 1}
EVIDENCE_LABELS = {
    "confirmed_text_match": "Confirmed text match in supplied dataset",
    "statistical_suspicion": "Statistically suspicious performance change",
    "unverified_external": "Unverified / family-level external exposure",
    "human_confirmed": "Human-confirmed incident",
}


def _slot_for_time(slots: list[Slot], ts) -> int | None:
    if ts is None:
        return None
    for s in sorted(slots, key=lambda s: s.starts_at):
        if s.starts_at >= ts:
            return s.sequence
    return None


def run_detection(db: Session, org_id: int, user: User | None, replay: bool = True) -> LeakDetectionRun:
    t0 = time.perf_counter()
    pol = get_policy(db, org_id, "leak")
    run = LeakDetectionRun(org_id=org_id, created_by=user.id if user else None, params=pol)
    db.add(run)
    db.flush()

    questions = db.scalars(select(Question).where(Question.org_id == org_id, Question.status != "archived")).all()
    qmap = {q.id: q for q in questions}
    recs = db.execute(
        select(LeakRecord, LeakDataset.name, LeakDataset.is_synthetic)
        .join(LeakDataset, LeakDataset.id == LeakRecord.dataset_id).where(LeakDataset.org_id == org_id)
    ).all()
    rmap = {r.id: (r, ds_name, syn) for r, ds_name, syn in recs}
    slots = db.scalars(select(Slot).where(Slot.org_id == org_id)).all()

    # ---------------- signal 1: text
    matches = match_items([ItemText(q.id, q.code, q.family_id, q.stem, [o.text for o in q.options]) for q in questions],
                          [RecordText(r.id, r.external_id, r.channel, r.posted_at, r.text) for r, _, _ in recs], pol)
    text_by_item: dict[int, list] = defaultdict(list)
    best_family_per_record: dict[int, object] = {}
    item_level_records = {m.record_id for m in matches if m.level != "family"}
    for m in matches:
        if m.level == "family":
            # one family-level finding per record (its best-matching item), and only if the record is not
            # already explained by an item-level match
            if m.record_id in item_level_records:
                continue
            cur = best_family_per_record.get(m.record_id)
            if cur is None or m.masked_score > cur.masked_score:
                best_family_per_record[m.record_id] = m
        else:
            text_by_item[m.item_id].append(m)
    for m in best_family_per_record.values():
        text_by_item[m.item_id].append(m)

    # ---------------- signals 2/3: performance + response time drift
    df = load_response_frame(db, org_id)
    drift = pd.DataFrame()
    onset: dict[int, int] = {}
    if not df.empty:
        df["scored"] = df["score"].fillna(0.0)
        drift = purified_drift(df, pol)
        if replay and not drift.empty:
            max_seq = int(df["slot_seq"].max())
            sig_items = set(drift.loc[(drift.q_mh < pol["fdr_alpha"]) & (drift.delta >= pol["min_effect_delta"]), "item"])
            for k in range(pol["baseline_slots"] + 1, max_seq + 1):
                if not sig_items - set(onset):
                    break
                part = purified_drift(df, pol, max_seq=k)
                if part.empty:
                    continue
                hit = part.loc[(part.q_mh < pol["fdr_alpha"]) & (part.delta >= pol["min_effect_delta"]), "item"]
                for i in hit:
                    onset.setdefault(int(i), k)
    drift_by_item = {int(r["item"]): r for r in drift.to_dict("records")} if not drift.empty else {}

    exposure = dict(db.execute(select(ExposureEvent.question_id, func.count(func.distinct(ExposureEvent.slot_id)))
                               .group_by(ExposureEvent.question_id)).all())

    # ---------------- combine per item
    findings: dict[int, dict] = {}
    for item_id in set(text_by_item) | set(drift_by_item):
        q = qmap.get(item_id)
        if q is None:
            continue
        signals, evidence = [], {}
        item_level = [m for m in text_by_item.get(item_id, []) if m.level in ("item_exact", "item_similar")]
        family_level = [m for m in text_by_item.get(item_id, []) if m.level == "family"]
        if item_level:
            best = max(item_level, key=lambda m: m.score)
            r, ds_name, syn = rmap[best.record_id]
            signals.append({
                "signal": "text_match", "level": best.level, "strength": best.score, "significant": True,
                "summary": f"{'Verbatim' if best.level == 'item_exact' else 'Near-verbatim/paraphrased'} copy found in "
                           f"'{r.channel}' ({r.channel_type}) record {r.external_id}: {best.details.get('reason')}",
            })
            evidence["text_matches"] = [{
                "record_id": m.record_id, "external_id": rmap[m.record_id][0].external_id,
                "channel": rmap[m.record_id][0].channel, "channel_type": rmap[m.record_id][0].channel_type,
                "dataset": rmap[m.record_id][1], "dataset_is_synthetic": rmap[m.record_id][2],
                "posted_at": rmap[m.record_id][0].posted_at.isoformat() if rmap[m.record_id][0].posted_at else None,
                "level": m.level, "score": m.score, "containment": m.containment, "char_cosine": m.char_cosine,
                "number_agreement": m.number_agreement, "excerpt": m.matched_excerpt, "reason": m.details.get("reason"),
                "option_values_found": m.details.get("option_values_found"),
            } for m in sorted(item_level, key=lambda m: -m.score)[:5]]
        elif family_level:
            best = max(family_level, key=lambda m: m.masked_score)
            r, ds_name, _ = rmap[best.record_id]
            signals.append({"signal": "family_text_match", "level": "family", "strength": best.masked_score,
                            "significant": False,
                            "summary": f"Same wording template (numbers differ) seen in '{r.channel}' record {r.external_id}"})
            evidence["family_matches"] = [{"external_id": rmap[m.record_id][0].external_id, "channel": rmap[m.record_id][0].channel,
                                           "masked_score": m.masked_score, "number_agreement": m.number_agreement,
                                           "excerpt": m.matched_excerpt} for m in family_level[:3]]
        d = drift_by_item.get(item_id)
        dif_sig = rt_sig = False
        if d is not None:
            dif_sig = d["q_mh"] < pol["fdr_alpha"] and d["delta"] >= pol["min_effect_delta"]
            rt_sig = (d["p_rt"] is not None and d["q_rt"] < pol["fdr_alpha"] and d["rt_rel_ratio"] is not None
                      and d["rt_rel_ratio"] <= pol["min_rt_ratio"])
            evidence["performance"] = {
                "test": "Mantel–Haenszel (rest-score strata, purified)", "baseline_slots": d["baseline_slots"],
                "later_slots": d["later_slots"], "n_baseline": d["n_ref"], "n_later": d["n_foc"],
                "p_baseline": round(d["p_ref"], 3), "p_later": round(d["p_foc"], 3),
                "rest_baseline": round(d["rest_ref"], 3), "rest_later": round(d["rest_foc"], 3),
                "alpha_mh": d["alpha_mh"], "ets_delta": d["delta"], "ets_class": ets_class(d["delta"], d["q_mh"], pol["fdr_alpha"]),
                "chi2": d["chi2"], "p_value": d["p_mh_dir"], "q_value_bh": d["q_mh"], "per_slot": d["per_slot"],
            }
            evidence["response_time"] = {
                "median_rt_baseline_ms": d["median_rt_ref"], "median_rt_later_ms": d["median_rt_foc"],
                "ratio": d["rt_ratio"], "ratio_vs_slot_pace": d["rt_rel_ratio"], "p_value": d["p_rt"], "q_value_bh": d["q_rt"],
            }
            if dif_sig or d["q_mh"] < pol["fdr_alpha"] * 2:
                signals.append({"signal": "performance_shift", "strength": d["delta"], "significant": dif_sig,
                                "summary": f"Ability-adjusted easier in later slots: ETS Δ = {d['delta']:+.2f}, "
                                           f"q = {d['q_mh']:.3g} (raw p {d['p_ref']:.2f} → {d['p_foc']:.2f})"})
            if rt_sig:
                signals.append({"signal": "response_time_drop", "strength": d["rt_rel_ratio"], "significant": True,
                                "summary": f"Median response time fell to {d['rt_rel_ratio']:.0%} of slot-adjusted baseline "
                                           f"(q = {d['q_rt']:.3g})"})
        if not signals:
            continue
        findings[item_id] = {"q": q, "signals": signals, "evidence": evidence, "item_text": bool(item_level),
                             "family_text": bool(family_level) and not item_level, "dif": dif_sig, "rt": rt_sig, "drift": d}

    # affected family: every finding lists its sibling variants so reviewers can act on the whole family
    fam_members: dict[int, list] = defaultdict(list)
    for q in questions:
        fam_members[q.family_id].append(q)
    for item_id, f in findings.items():
        q = f["q"]
        f["evidence"]["affected_family"] = {
            "family_code": q.family.code, "concept": q.family.concept,
            "siblings": [{"code": s.code, "status": s.status, "leak_status": s.leak_status}
                         for s in fam_members[q.family_id] if s.id != q.id],
        }

    # ---------------- severity, explanation, persistence
    created = updated = 0
    counts: dict[str, int] = defaultdict(int)
    for item_id, f in findings.items():
        q = f["q"]
        if f["item_text"] and f["dif"]:
            sev, etype, eclass = "critical", "composite_text_and_performance", "confirmed_text_match"
        elif f["item_text"]:
            sev, etype, eclass = "high", "text_match", "confirmed_text_match"
        elif f["dif"] and f["rt"]:
            sev, etype, eclass = "high", "performance_and_response_time", "statistical_suspicion"
        elif f["dif"]:
            sev, etype, eclass = "medium", "performance_shift", "statistical_suspicion"
        elif f["rt"]:
            sev, etype, eclass = "low", "response_time_drop", "statistical_suspicion"
        elif f["family_text"]:
            sev, etype, eclass = "low", "family_exposure", "unverified_external"
        else:
            continue  # sub-threshold drift only: not alerted
        strengths = []
        for s in f["signals"]:
            if s["signal"] == "text_match":
                strengths.append(0.9 if s["level"] == "item_exact" else 0.7 * s["strength"])
            elif s["signal"] == "performance_shift" and s["significant"]:
                strengths.append(min(0.85, 0.3 + 0.25 * s["strength"]))
            elif s["signal"] == "response_time_drop":
                strengths.append(0.4)
            elif s["signal"] in ("family_text_match", "family_exposure"):
                strengths.append(0.25)
        n_slots = exposure.get(item_id, 0)
        strengths.append(min(0.2, 0.03 * n_slots))
        score = round(100 * (1 - math.prod(1 - s for s in strengths)), 1)

        posted = [m["posted_at"] for m in f["evidence"].get("text_matches", []) if m.get("posted_at")]
        text_slot = None
        if posted:
            from datetime import datetime
            text_slot = _slot_for_time(slots, min(datetime.fromisoformat(p) for p in posted))
        first_slot = min([s for s in (text_slot, onset.get(item_id)) if s is not None], default=None)
        f["evidence"]["timeline"] = {"text_detectable_before_slot": text_slot, "statistical_onset_slot": onset.get(item_id),
                                     "exposure_slots": n_slots}
        explanation = _explain(q, f, sev, eclass, pol)
        action = {
            "critical": "Quarantine the item and its family's exposed variants; exclude from upcoming forms; open an investigation.",
            "high": "Quarantine pending investigation; confirm the source; check scores of affected slots.",
            "medium": "Investigate: compare with other evidence; consider excluding the item from scoring in later slots.",
            "low": "Monitor; avoid placing family siblings in adjacent slots.",
        }[sev]
        baseline = observed = None
        if f["drift"] is not None:
            d = f["drift"]
            baseline = {"p_correct": round(d["p_ref"], 3), "median_rt_ms": d["median_rt_ref"], "slots": d["baseline_slots"], "n": d["n_ref"]}
            observed = {"p_correct": round(d["p_foc"], 3), "median_rt_ms": d["median_rt_foc"], "slots": d["later_slots"], "n": d["n_foc"]}
        existing = db.scalar(select(LeakAlert).where(LeakAlert.question_id == item_id, LeakAlert.org_id == org_id))
        title = f"{q.code}: {EVIDENCE_LABELS[eclass]}"
        if existing:
            existing.run_id, existing.severity, existing.score, existing.alert_type = run.id, sev, score, etype
            existing.evidence_class = existing.evidence_class if existing.evidence_class == "human_confirmed" else eclass
            existing.title, existing.explanation, existing.signals = title, explanation, f["signals"]
            existing.evidence, existing.baseline, existing.observed = f["evidence"], baseline, observed
            existing.recommended_action, existing.first_detectable_slot = action, first_slot
            updated += 1
        else:
            n = (db.scalar(select(func.count()).select_from(LeakAlert)) or 0) + 1
            db.add(LeakAlert(code=f"ALR-{n:04d}", org_id=org_id, run_id=run.id, question_id=item_id, family_id=q.family_id,
                             alert_type=etype, evidence_class=eclass, severity=sev, score=score, title=title,
                             explanation=explanation, signals=f["signals"], baseline=baseline, observed=observed,
                             evidence=f["evidence"], recommended_action=action, first_detectable_slot=first_slot))
            db.flush()
            created += 1
        if sev in ("critical", "high") and q.leak_status in ("none",):
            q.leak_status = "suspected"
            from app.services.assembly.service import flag_forms_for_item

            db.flush()
            flag_forms_for_item(db, q.id, f"{q.code}: suspected leak ({sev} alert)", user)
        counts[sev] += 1

    run.duration_ms = int((time.perf_counter() - t0) * 1000)
    run.summary = {"alerts_created": created, "alerts_updated": updated, "by_severity": dict(counts),
                   "text_matches": len(matches), "items_tested_for_drift": int(len(drift)),
                   "records_scanned": len(recs), "items_scanned": len(questions),
                   "datasets": sorted({ds for _, ds, _ in recs})}
    audit.record(db, user, "leaks.detection_run", "leak_detection_run", run.id,
                 f"Leak detection: {created} new / {updated} updated alerts in {run.duration_ms} ms", run.summary)
    return run


def _explain(q: Question, f: dict, sev: str, eclass: str, pol: dict) -> str:
    parts = [f"Severity {sev.upper()} — {EVIDENCE_LABELS[eclass]}."]
    for s in f["signals"]:
        parts.append(f"• {s['summary']}.")
    perf = f["evidence"].get("performance")
    if perf and not f["dif"]:
        parts.append(f"• Performance change not significant after FDR control (q = {perf['q_value_bh']:.3g}).")
    if f["item_text"] and not f["dif"]:
        parts.append("• No significant ability-adjusted performance change yet; the text match alone does not prove "
                     "candidates used the material.")
    if f["dif"] and not f["item_text"]:
        parts.append("• No matching text in the supplied datasets. The shift is consistent with exposure but could also "
                     "reflect a scoring or content issue; human investigation required.")
    parts.append("Similarity and statistical signals are evidence, not proof of misconduct.")
    return "\n".join(parts)


TRANSITIONS = {
    "acknowledge": ({"open"}, "acknowledged"),
    "investigate": ({"open", "acknowledged"}, "investigating"),
    "confirm": ({"open", "acknowledged", "investigating"}, "confirmed"),
    "dismiss": ({"open", "acknowledged", "investigating"}, "dismissed"),
    "reopen": ({"confirmed", "dismissed"}, "investigating"),
    "comment": (None, None),
}


def transition_alert(db: Session, alert: LeakAlert, action: str, user: User, note: str | None) -> LeakAlert:
    if action not in TRANSITIONS:
        raise NotFound(f"Unknown action '{action}'")
    allowed, target = TRANSITIONS[action]
    if allowed is not None and alert.status not in allowed:
        raise Conflict(f"Cannot {action} an alert in status '{alert.status}'", {"allowed_from": sorted(allowed)})
    if action in ("confirm", "dismiss") and not (note and len(note.strip()) >= 10):
        raise Conflict("A decision note (≥10 characters) is required to confirm or dismiss")
    inv = db.scalar(select(Investigation).where(Investigation.alert_id == alert.id))
    if inv is None:
        inv = Investigation(alert_id=alert.id, status="open", assignee_id=user.id)
        db.add(inv)
        db.flush()
    from_status = alert.status
    q = db.get(Question, alert.question_id)
    if target:
        alert.status = target
        inv.status = target
    if action == "confirm":
        alert.evidence_class = "human_confirmed"
        alert.reviewer_id, alert.reviewer_decision, alert.decided_at = user.id, note, utcnow()
        inv.closed_at, inv.resolution, inv.summary = utcnow(), "confirmed_leak", note
        q.leak_status = "confirmed"
        if q.status in ("approved", "pending_review"):
            q.status, q.status_reason = "quarantined", f"Leak confirmed via {alert.code}"
        from app.services.assembly.service import flag_forms_for_item

        db.flush()
        flag_forms_for_item(db, q.id, f"{q.code}: leak confirmed via {alert.code}", user)
    elif action == "dismiss":
        alert.reviewer_id, alert.reviewer_decision, alert.decided_at = user.id, note, utcnow()
        inv.closed_at, inv.resolution, inv.summary = utcnow(), "dismissed", note
        others = db.scalar(select(func.count()).select_from(LeakAlert).where(
            LeakAlert.question_id == q.id, LeakAlert.id != alert.id, LeakAlert.status.in_(("open", "acknowledged", "investigating", "confirmed"))))
        if not others and q.leak_status != "confirmed":
            q.leak_status = "cleared"
            from app.services.assembly.service import restore_forms_if_clean

            db.flush()
            restore_forms_if_clean(db, q.id, user)
    elif action == "reopen":
        inv.closed_at = None
        alert.decided_at = None
    db.add(InvestigationEvent(investigation_id=inv.id, actor_id=user.id, actor_label=f"{user.full_name} ({user.role.label})",
                              action=action, from_status=from_status, to_status=alert.status, note=note))
    audit.record(db, user, f"leaks.alert_{action}", "leak_alert", alert.code,
                 f"{alert.code} {from_status} → {alert.status}" + (f": {note[:120]}" if note else ""))
    return alert


_ = np
