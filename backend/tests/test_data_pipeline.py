"""Official-data validation pipeline: BLOCKED without data, full run on a SYNTHETIC fixture, import policies."""
import io
import json
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
PY = sys.executable


def test_missing_official_data_reports_blocked(tmp_path):
    r = subprocess.run([PY, str(ROOT / "scripts" / "validate_official_data.py"), "--data-dir", str(tmp_path / "nope")],
                       capture_output=True, text=True)
    assert r.returncode == 3 and json.loads(r.stdout)["status"] == "BLOCKED"
    (tmp_path / "d").mkdir()
    (tmp_path / "d" / "DATASET.json").write_text("{}")
    r = subprocess.run([PY, str(ROOT / "scripts" / "validate_official_data.py"), "--data-dir", str(tmp_path / "d")],
                       capture_output=True, text=True)
    assert r.returncode == 3 and "missing required input" in r.stdout


def test_missing_provenance_is_blocked(tmp_path):
    subprocess.run([PY, str(ROOT / "scripts" / "make_synthetic_validation_fixture.py"), str(tmp_path)], check=True, capture_output=True)
    meta = json.loads((tmp_path / "DATASET.json").read_text())
    del meta["license"]
    (tmp_path / "DATASET.json").write_text(json.dumps(meta))
    r = subprocess.run([PY, str(ROOT / "scripts" / "validate_official_data.py"), "--data-dir", str(tmp_path)], capture_output=True, text=True)
    assert r.returncode == 3 and "license" in r.stdout


def test_full_pipeline_on_synthetic_fixture_is_labelled_synthetic(tmp_path):
    fx, out = tmp_path / "fx", tmp_path / "out"
    subprocess.run([PY, str(ROOT / "scripts" / "make_synthetic_validation_fixture.py"), str(fx)], check=True, capture_output=True)
    before = {p.name: p.read_bytes() for p in fx.iterdir()}
    r = subprocess.run([PY, str(ROOT / "scripts" / "validate_official_data.py"), "--data-dir", str(fx), "--out", str(out)],
                       capture_output=True, text=True, timeout=900)
    assert r.returncode == 0, r.stdout + r.stderr
    rep = json.loads(Path(json.loads(r.stdout)["report"]).read_text())
    assert rep["title"].startswith("SYNTHETIC PIPELINE CHECK") and rep["dataset"]["synthetic"] is True
    assert {p.name: p.read_bytes() for p in fx.iterdir()} == before  # inputs never modified
    assert all(len(v["sha256"]) == 64 for v in rep["inputs"].values())
    assert rep["item_bank"]["rejected"] == 0 and rep["responses"]["responses_created"] == 45000
    assert rep["calibration"]["rasch_fitted"] is True
    m = rep["leak_detection"]["metrics"]
    assert set(m) == {"dev", "note"}  # no held-out split -> nothing may be quoted as independent validation
    assert m["dev"]["medium_plus"]["recall"]["ci95"][0] < 1.0  # uncertainty reported, not just a point estimate
    chk = rep["assembly"]["independent_check"]
    assert rep["assembly"]["status"] == "succeeded" and chk["violations"] == [] and chk["max_adjacent_overlap_pct"] <= 10
    md = next(out.glob("*/REPORT.md")).read_text()
    assert "SYNTHETIC DATA" in md and "not validation on official data" in md


def test_item_bank_import_rejects_structural_errors_and_holds_duplicates(db):
    from sqlalchemy import select

    from app.models import Organization, Question
    from app.services.importers import import_item_bank

    org = Organization(name="Import test", slug="import-test")
    db.add(org)
    db.flush()
    base = dict(section="QUANT", option_a="12", option_b="15", option_c="18", option_d="20", correct_option="B",
                difficulty="medium", skill="averages")
    df = pd.DataFrame([
        {**base, "item_code": "IMP-1", "stem": "The average of three numbers is 15. What is their sum divided by three?"},
        {**base, "item_code": "IMP-2", "stem": "The average of three numbers is 15. What is their sum divided by three?"},  # exact dup
        {**base, "item_code": "IMP-3", "stem": "A different question with two identical options listed below?", "option_c": "15"},
        {**base, "item_code": "IMP-4", "stem": "Pick the right difficulty for this broken row please.", "difficulty": "impossible"},
    ])
    rep = import_item_bank(db, org.id, None, df, "unit-test", status="approved", is_synthetic=True)
    assert rep["imported"] == 2 and rep["held_for_duplicate_review"] == 1 and rep["rejected"] == 2
    held = db.scalar(select(Question).where(Question.code == "IMP-2"))
    assert held.status == "pending_review" and "held for review" in held.status_reason
    assert db.scalar(select(Question).where(Question.code == "IMP-1")).status == "approved"
    assert db.scalar(select(Question).where(Question.code == "IMP-3")) is None
    db.rollback()


def test_item_bank_import_validates_columns(db):
    from app.core.errors import Unprocessable
    from app.services.importers import import_item_bank

    with pytest.raises(Unprocessable):
        import_item_bank(db, 1, None, pd.read_csv(io.StringIO("item_code,section\nX,QUANT\n")), "bad")
