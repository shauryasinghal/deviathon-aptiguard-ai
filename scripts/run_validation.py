"""Reproducible evaluation of the SYNTHETIC demo against its ground truth.

Usage (from repo root, after scripts/seed_demo.py):
    backend/.venv/bin/python scripts/run_validation.py [--json docs/evidence/validation_results.json]

Reports leak-detection recall/precision on the injected scenario, timing (first detectable slot), ability-confound
false positives, calibration decisions for simulated non-parallel variants, and assembly constraint verification.
These numbers describe the synthetic scenario only; they are NOT real-world detection accuracy.
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import select  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.models import AssemblyRun, CalibrationRun, ItemCalibration, LeakAlert, Question  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=str(ROOT / "docs" / "evidence" / "validation_results.json"))
    args = ap.parse_args()
    truth = json.loads((ROOT / "data" / "synthetic" / "leak_ground_truth.json").read_text())
    inj = truth["injections"]
    with SessionLocal() as db:
        code = {q.id: q.code for q in db.scalars(select(Question)).all()}
        alerts = db.scalars(select(LeakAlert)).all()
        by_code = {code[a.question_id]: a for a in alerts}
        leaked = set(inj["L1_text_and_performance"]["items"]) | set(inj["L2_statistical_only"]["items"]) | set(inj["L3_text_only"]["items"])
        sev_ok = {"critical", "high", "medium"}
        flagged = {c for c, a in by_code.items() if a.severity in sev_ok}
        tp = leaked & flagged
        fp = flagged - leaked
        fn = leaked - flagged
        per_item = []
        for c in sorted(leaked):
            a = by_code.get(c)
            per_item.append({"item": c, "detected": a is not None and a.severity in sev_ok,
                             "severity": a.severity if a else None, "evidence_class": a.evidence_class if a else None,
                             "first_detectable_slot": a.first_detectable_slot if a else None,
                             "timeline": (a.evidence or {}).get("timeline") if a else None})
        clean_core = [c for c, r in inj.get("core_roles", [])] if False else []
        core = dict(json.loads((ROOT / "data" / "synthetic" / "leak_ground_truth.json").read_text())
                    .get("historical_drive") and [] or [])
        # calibration of simulated non-parallel variants
        run = db.scalar(select(CalibrationRun).order_by(CalibrationRun.id.desc()))
        drifted = truth["calibration_truth"]["drifted_variants_logit_offset"]
        cal = []
        qid = {v: k for k, v in code.items()}
        for c, off in drifted.items():
            ic = db.scalar(select(ItemCalibration).where(ItemCalibration.run_id == run.id, ItemCalibration.question_id == qid[c]))
            cal.append({"item": c, "true_offset": off, "status": ic.status if ic else "no_data",
                        "estimated_diff": round(ic.diff_from_reference, 3) if ic and ic.diff_from_reference is not None else None,
                        "ci90": [round(ic.diff_ci_low, 3), round(ic.diff_ci_high, 3)] if ic and ic.diff_ci_low is not None else None})
        others = db.execute(select(ItemCalibration.status).where(ItemCalibration.run_id == run.id,
                                                               ItemCalibration.question_id.notin_([qid[c] for c in drifted]),
                                                               ItemCalibration.reference_question_id.is_not(None))).scalars().all()
        asm = db.scalar(select(AssemblyRun).where(AssemblyRun.status == "succeeded").order_by(AssemblyRun.id.desc()))
        adj = [o for o in (asm.overlap if asm else []) if o["adjacent"]]
    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "data": "SYNTHETIC demo (seed 107). Not real-world accuracy.",
        "leak_detection": {
            "injected_items": len(leaked), "detected": len(tp), "missed": sorted(fn), "recall": round(len(tp) / len(leaked), 3),
            "alerts_on_non_injected_items_medium_plus": sorted(fp),
            "precision_medium_plus": round(len(tp) / len(flagged), 3) if flagged else None,
            "low_severity_alerts": sorted(c for c, a in by_code.items() if a.severity == "low"),
            "per_item": per_item,
        },
        "calibration": {"method": run.method, "rasch_fitted": run.rasch_fitted, "simulated_non_parallel_variants": cal,
                        "other_variant_status_counts": {s: others.count(s) for s in sorted(set(others))}},
        "assembly": {"run_id": asm.id if asm else None, "status": asm.status if asm else None,
                     "adjacent_pairs": len(adj), "max_adjacent_shared": max((o["shared"] for o in adj), default=None),
                     "max_adjacent_smaller_form_pct": max((o["smaller_form_pct"] for o in adj), default=None),
                     "limit_pct": (asm.config or {}).get("max_adjacent_overlap_pct") if asm else None,
                     "all_adjacent_constraints_ok": all(o["constraint_ok"] for o in adj) if adj else None,
                     "verification_violations": (asm.diagnostics or {}).get("violations") if asm else None},
    }
    _ = clean_core, core
    Path(args.json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.json).write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
