"""Convert the SYNTHETIC demo data (data/synthetic) into the official-data input format, for pipeline testing only.

    backend/.venv/bin/python scripts/make_synthetic_validation_fixture.py OUT_DIR
DATASET.json declares synthetic=true, so every downstream report is labelled as a synthetic pipeline check.
Leak labels are marked split=dev: detection thresholds were developed on this very scenario, so these numbers
can never count as independent (held-out) validation.
"""
import csv
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data" / "synthetic"


def main(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "DATASET.json").write_text(json.dumps({
        "name": "aptiguard-synthetic-seed107", "version": json.loads((SRC / "MANIFEST.json").read_text())["files"]["item_bank.jsonl"][:12],
        "provider": "AptiGuard demo generator (scripts/seed_demo.py)", "license": "project-internal synthetic data",
        "synthetic": True, "notes": "Pipeline check only. Not official data."}, indent=2))
    items = [json.loads(line) for line in (SRC / "item_bank.jsonl").read_text().splitlines() if line.strip()]
    items = [i for i in items if i["status"] == "approved"]
    with (out / "item_bank.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["item_code", "section", "stem", "option_a", "option_b", "option_c", "option_d", "correct_option",
                    "difficulty", "skill", "family_code", "parent_code"])
        for i in items:
            parent = "" if i["item_code"].endswith("-S") else i["item_code"].rsplit("-", 1)[0] + "-S"
            w.writerow([i["item_code"], i["section"], i["stem"], *[i["options"][k] for k in "ABCD"], i["correct_option"],
                        i["difficulty_target"], i["skill"], i["family"], parent])
    shutil.copyfile(SRC / "response_logs.csv", out / "response_logs.csv")
    shutil.copyfile(SRC / "leak_simulation_posts.jsonl", out / "leak_posts.jsonl")
    gt = json.loads((SRC / "leak_ground_truth.json").read_text())["injections"]
    leaked = {c: ("text_and_performance", 3) for c in gt["L1_text_and_performance"]["items"]}
    leaked |= {c: ("statistical_only", 6) for c in gt["L2_statistical_only"]["items"]}
    leaked |= {c: ("text_only", 9) for c in gt["L3_text_only"]["items"]}
    with (out / "leak_labels.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["item_code", "leaked", "leak_type", "leak_first_slot", "split"])
        for i in items:
            lt, slot = leaked.get(i["item_code"], ("", ""))
            w.writerow([i["item_code"], int(i["item_code"] in leaked), lt, slot, "dev"])
    print(f"synthetic fixture written to {out} ({len(items)} items)")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
