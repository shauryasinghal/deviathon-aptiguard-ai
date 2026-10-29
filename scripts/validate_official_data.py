"""Official-data validation: import → calibrate → detect leaks → assemble → independently verify → report.

    backend/.venv/bin/python scripts/validate_official_data.py [--data-dir data/official] [--out reports/official-validation]

Inputs (see docs/dataset-schema.md). Files are read-only; their SHA-256 hashes are recorded.
  DATASET.json            required provenance: {"name","version","provider","license","synthetic": false, ...}
  item_bank.csv|.jsonl    required
  response_logs.csv       required
  leak_posts.jsonl|.csv   optional (authorised leak dataset)
  leak_labels.csv         optional ground truth: item_code, leaked (0/1), leak_type, leak_first_slot, split (dev|heldout)
Exit codes: 0 = completed, 3 = BLOCKED (inputs/provenance missing), 1 = failed.

The run uses a FRESH, isolated database (temporary SQLite unless --database-url names an empty *_validation DB) and
the frozen default policies. Nothing here tunes thresholds; if labels carry a dev/heldout split, metrics are reported
per split and only heldout metrics may be quoted as independent validation.
"""
import argparse
import hashlib
import json
import math
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BLOCKED, FAILED = 3, 1
REQUIRED = {"DATASET.json": ["DATASET.json"], "item_bank": ["item_bank.csv", "item_bank.jsonl"], "response_logs": ["response_logs.csv"]}
OPTIONAL = {"leak_posts": ["leak_posts.jsonl", "leak_posts.csv"], "leak_labels": ["leak_labels.csv"]}


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def find(d: Path, names: list[str]) -> Path | None:
    return next((d / n for n in names if (d / n).is_file()), None)


def wilson(k: int, n: int, z: float = 1.96):
    if n == 0:
        return None
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return [round(max(0, c - h), 4), round(min(1, c + h), 4)]


def rate(k, n):
    return {"value": round(k / n, 4) if n else None, "k": k, "n": n, "ci95": wilson(k, n)}


def blocked(msg: str, data_dir: Path) -> int:
    print(json.dumps({"status": "BLOCKED", "reason": msg, "data_dir": str(data_dir),
                      "expected": {**REQUIRED, **OPTIONAL}, "schema": "docs/dataset-schema.md",
                      "next_step": f"place the official files in {data_dir} and re-run this command"}, indent=2))
    return BLOCKED


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=str(ROOT / "data" / "official"))
    ap.add_argument("--out", default=str(ROOT / "reports" / "official-validation"))
    ap.add_argument("--database-url", default=None, help="empty database whose name ends in _validation (default: temp SQLite)")
    ap.add_argument("--bank-status", default="approved", choices=["approved", "pending_review"],
                    help="status for imported official items (approved = treated as the reviewed official bank)")
    ap.add_argument("--slots", type=int, default=10)
    ap.add_argument("--per-section", default="QUANT=10,LOGICAL=10,VERBAL=10")
    ap.add_argument("--overlap-pct", type=float, default=10.0)
    ap.add_argument("--seed", type=int, default=107)
    a = ap.parse_args()
    data_dir = Path(a.data_dir)
    if not data_dir.is_dir():
        return blocked("official data directory does not exist", data_dir)
    files = {}
    for k, names in REQUIRED.items():
        p = find(data_dir, names)
        if p is None:
            return blocked(f"missing required input: one of {names}", data_dir)
        files[k] = p
    for k, names in OPTIONAL.items():
        p = find(data_dir, names)
        if p:
            files[k] = p
    meta = json.loads(files["DATASET.json"].read_text())
    for field in ("name", "version", "provider", "license", "synthetic"):
        if field not in meta:
            return blocked(f"DATASET.json lacks provenance field '{field}'", data_dir)
    synthetic = bool(meta["synthetic"])

    # ---------------------------------------------------------------- isolated database
    tmp = tempfile.mkdtemp(prefix="aptiguard-validation-")
    url = a.database_url or f"sqlite:///{tmp}/validation.db"
    if a.database_url and not url.rsplit("/", 1)[-1].split("?")[0].endswith("_validation"):
        print("refusing: --database-url must name a database ending in _validation", file=sys.stderr)
        return FAILED
    os.environ.update({"DATABASE_URL": url, "APP_ENV": "test", "DEMO_MODE": "false"})
    sys.path.insert(0, str(ROOT / "backend"))
    import subprocess

    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=ROOT / "backend", check=True,
                   capture_output=True)
    import pandas as pd
    from sqlalchemy import func, select

    from app.bootstrap import ensure_reference_data
    from app.db.session import SessionLocal
    from app.models import (Attempt, CandidateAssignment, FormItem, ItemCalibration, LeakAlert, Organization, Question,
                            Slot, TestForm)
    from app.services.assembly.algorithm import overlap_stats
    from app.services.assembly.service import run_assembly
    from app.services.calibration.service import run_calibration
    from app.services.importers import import_item_bank, import_response_log, read_table
    from app.services.leakage.importer import import_dataset
    from app.services.leakage.service import run_detection
    from app.services.policies import DEFAULT_POLICIES

    _ = CandidateAssignment, Attempt
    t0 = time.perf_counter()
    report: dict = {
        "title": ("SYNTHETIC PIPELINE CHECK — NOT OFFICIAL VALIDATION" if synthetic else "Official-data validation"),
        "status": "COMPLETED", "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dataset": meta, "inputs": {k: {"file": p.name, "sha256": sha256(p), "bytes": p.stat().st_size} for k, p in files.items()},
        "database": url.split("://")[0], "policies_frozen": DEFAULT_POLICIES,
        "policy_hash": hashlib.sha256(json.dumps(DEFAULT_POLICIES, sort_keys=True).encode()).hexdigest()[:16],
        "config": {"bank_status": a.bank_status, "slots": a.slots, "per_section": a.per_section, "overlap_pct": a.overlap_pct, "seed": a.seed},
    }
    with SessionLocal() as db:
        if db.scalar(select(func.count()).select_from(Question)):
            print("refusing: validation database is not empty", file=sys.stderr)
            return FAILED
        ensure_reference_data(db)
        org = Organization(name=f"Validation · {meta['name']}", slug="official-validation")
        db.add(org)
        db.flush()

        bank_df = read_table(files["item_bank"].read_bytes(), files["item_bank"].name)
        report["item_bank"] = import_item_bank(db, org.id, None, bank_df, f"{meta['name']}@{meta['version']}",
                                               status=a.bank_status, is_synthetic=synthetic)
        report["item_bank"]["rejections"] = report["item_bank"]["rejections"][:200]
        report["item_bank"]["held"] = report["item_bank"]["held"][:200]
        db.commit()

        resp_df = read_table(files["response_logs"].read_bytes(), files["response_logs"].name)
        try:
            rr = import_response_log(db, org.id, None, resp_df, f"{meta['name']}@{meta['version']}", is_synthetic=synthetic)
            report["responses"] = {k: v for k, v in rr.items() if k != "columns"}
        except Exception as e:  # validation errors are reported, not hidden
            report["responses"] = {"error": str(e), "details": getattr(e, "details", None)}
            report["status"] = "FAILED"
        db.commit()

        if report["status"] == "COMPLETED":
            run = run_calibration(db, org.id, None, data_source=f"{meta['name']}@{meta['version']}")
            db.commit()
            items = db.scalars(select(ItemCalibration).where(ItemCalibration.run_id == run.id)).all()
            widths = [ic.p_ci_high - ic.p_ci_low for ic in items if ic.p_ci_low is not None]
            report["calibration"] = {
                "method": run.method, "rasch_fitted": run.rasch_fitted, "n_responses": run.n_responses, "n_items": run.n_items,
                "n_persons": run.n_persons, "warnings": run.warnings, "status_counts": (run.summary or {}).get("status_counts"),
                "rasch": (run.summary or {}).get("rasch"), "median_p_ci_width": round(sorted(widths)[len(widths) // 2], 4) if widths else None,
                "variant_comparisons": sum(1 for ic in items if ic.reference_question_id is not None),
                "equivalence_margin_logits": run.params.get("tolerance_logits"),
                "slots": (run.summary or {}).get("slots"),
            }

            if "leak_posts" in files:
                import_dataset(db, org.id, None, files["leak_posts"].read_bytes(), files["leak_posts"].name,
                               f"{meta['name']} leak posts", "authorized_export", is_synthetic=synthetic)
                det = run_detection(db, org.id, None)
                db.commit()
                report["leak_detection"] = {"summary": det.summary}
                if "leak_labels" in files:
                    report["leak_detection"]["metrics"] = leak_metrics(db, org.id, pd.read_csv(files["leak_labels"]),
                                                                       LeakAlert, Question)
            per = dict(kv.split("=") for kv in a.per_section.split(","))
            asm = run_assembly(db, org.id, None, {"drive": "Validation drive", "n_slots": a.slots,
                                                  "per_section": {k: int(v) for k, v in per.items()},
                                                  "max_adjacent_overlap_pct": a.overlap_pct, "seed": a.seed,
                                                  "start_date": "2030-01-01T04:00:00"})
            db.commit()
            report["assembly"] = {"status": asm.status, "explanation": asm.diagnostics.get("explanation"),
                                  "infeasible_cells": asm.diagnostics.get("infeasible_cells")}
            if asm.status == "succeeded":
                report["assembly"]["independent_check"] = verify_forms_from_db(db, asm, a.overlap_pct, TestForm, FormItem, Question,
                                                                               Slot, overlap_stats)
    report["duration_s"] = round(time.perf_counter() - t0, 1)
    out = Path(a.out) / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(report, indent=2, default=str))
    (out / "REPORT.md").write_text(markdown(report))
    print(json.dumps({"status": report["status"], "title": report["title"], "report": str(out / "report.json")}, indent=2))
    return 0 if report["status"] == "COMPLETED" else FAILED


def leak_metrics(db, org_id, labels, LeakAlert, Question):
    import pandas as pd
    from sqlalchemy import select

    code = {q.id: q.code for q in db.scalars(select(Question).where(Question.org_id == org_id)).all()}
    alerts = {code[a.question_id]: a for a in db.scalars(select(LeakAlert).where(LeakAlert.org_id == org_id)).all()}
    labels = labels.copy()
    labels["leaked"] = labels["leaked"].astype(int)
    if "split" not in labels:
        labels["split"] = "unspecified"
    out = {}
    for split, g in labels.groupby("split"):
        res = {}
        for name, sevs in [("medium_plus", {"critical", "high", "medium"}), ("high_plus", {"critical", "high"})]:
            flagged = {c for c, a in alerts.items() if a.severity in sevs}
            pos, neg = g[g.leaked == 1], g[g.leaked == 0]
            tp = int(pos.item_code.isin(flagged).sum())
            fp = int(neg.item_code.isin(flagged).sum())
            fn, tn = len(pos) - tp, len(neg) - fp
            by_type = {}
            for lt, gg in pos.groupby(pos.get("leak_type", pd.Series(["unspecified"] * len(pos), index=pos.index))):
                by_type[str(lt)] = rate(int(gg.item_code.isin(flagged).sum()), len(gg))
            latency = []
            if "leak_first_slot" in pos:
                for _, r in pos.iterrows():
                    a = alerts.get(r.item_code)
                    if a is not None and a.severity in sevs and a.first_detectable_slot and not pd.isna(r.leak_first_slot):
                        latency.append(int(a.first_detectable_slot) - int(r.leak_first_slot))
            res[name] = {"tp": tp, "fp": fp, "fn": fn, "tn": tn, "precision": rate(tp, tp + fp), "recall": rate(tp, tp + fn),
                         "false_positive_rate": rate(fp, fp + tn), "false_negative_rate": rate(fn, fn + tp), "by_leak_type": by_type,
                         "detection_latency_slots": {"n": len(latency), "median": sorted(latency)[len(latency) // 2] if latency else None,
                                                     "values": latency[:100]}}
        out[str(split)] = res
    out["note"] = ("Only the 'heldout' split may be quoted as independent validation; 'dev'/'unspecified' labels may "
                   "have informed thresholds.")
    return out


def verify_forms_from_db(db, run, overlap_pct, TestForm, FormItem, Question, Slot, overlap_stats):
    """Recompute everything from the stored manifests (independent of the algorithm's own verification)."""
    from sqlalchemy import select

    forms = db.scalars(select(TestForm).where(TestForm.assembly_run_id == run.id)).all()
    sets, fam, bad = {}, {}, []
    for f in forms:
        qids = [fi.question_id for fi in db.scalars(select(FormItem).where(FormItem.form_id == f.id)).all()]
        sets[f.id] = (f.slot.sequence, set(qids))
        fams = [db.get(Question, q).family_id for q in qids]
        if len(fams) != len(set(fams)):
            bad.append(f"{f.code}: two items from one family")
        if len(qids) != len(set(qids)):
            bad.append(f"{f.code}: repeated item")
        for q in qids:
            qq = db.get(Question, q)
            if qq.status != "approved" or qq.leak_status in ("suspected", "confirmed"):
                bad.append(f"{f.code}: ineligible item {qq.code}")
    pairs, max_pct = [], 0.0
    ids = sorted(sets, key=lambda i: sets[i][0])
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            if abs(sets[a][0] - sets[b][0]) <= 1:
                st = overlap_stats(sets[a][1], sets[b][1])
                max_pct = max(max_pct, st["smaller_form_pct"])
                if st["smaller_form_pct"] > overlap_pct:
                    bad.append(f"forms {a},{b}: {st['smaller_form_pct']}% > {overlap_pct}%")
                pairs.append(st)
    uses = {}
    for _, s in sets.values():
        for q in s:
            uses[q] = uses.get(q, 0) + 1
    return {"forms": len(forms), "adjacent_pairs": len(pairs), "max_adjacent_overlap_pct": max_pct,
            "max_item_uses_in_plan": max(uses.values()) if uses else 0, "violations": bad}


def markdown(r: dict) -> str:
    lines = [f"# {r['title']}", "", f"Generated {r['generated_at']} · status **{r['status']}** · policy hash `{r['policy_hash']}`", ""]
    if r["dataset"].get("synthetic"):
        lines += ["> **SYNTHETIC DATA.** This run checks the pipeline only. It is not validation on official data and",
                  "> says nothing about real-world accuracy.", ""]
    lines += ["## Inputs", ""] + [f"- `{v['file']}` sha256 `{v['sha256']}` ({v['bytes']} bytes)" for v in r["inputs"].values()]
    for section in ("item_bank", "responses", "calibration", "leak_detection", "assembly"):
        if section in r:
            lines += ["", f"## {section.replace('_', ' ').title()}", "", "```json", json.dumps(r[section], indent=2, default=str)[:20000], "```"]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    sys.exit(main())
