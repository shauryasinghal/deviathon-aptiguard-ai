"""Integration tests against the seeded synthetic demo database (end-to-end through HTTP)."""
import io
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
V1 = "/api/v1"


def test_health_and_readiness(client):
    assert client.get(f"{V1}/health").json()["status"] == "ok"
    r = client.get(f"{V1}/ready").json()
    assert r["status"] == "ready" and r["migration"] == "0003"


def test_login_rejects_bad_password(client):
    r = client.post(f"{V1}/auth/login", json={"email": "admin@aptiguard.demo", "password": "nope"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "invalid_credentials"


@pytest.mark.parametrize("role,url,expected", [
    ("candidate", "/questions", 403), ("candidate", "/dashboard/summary", 403), ("admin", "/assessment/available", 403),
    ("designer", "/audit", 403), ("analyst", "/settings/policies/exposure", 405), ("reviewer", "/calibration/runs", 200),
])
def test_rbac_matrix(client, auth, role, url, expected):
    assert client.get(V1 + url, headers=auth(role)).status_code == expected


def test_unauthenticated_requests_rejected(client):
    assert client.get(f"{V1}/dashboard/summary").status_code == 401
    assert client.get(f"{V1}/questions", headers={"Authorization": "Bearer garbage"}).status_code == 401


def test_dashboard_values_come_from_backend(client, auth, db):
    from sqlalchemy import func, select

    from app.models import Question

    d = client.get(f"{V1}/dashboard/summary", headers=auth("admin")).json()
    pending = db.scalar(select(func.count()).select_from(Question).where(Question.status == "pending_review"))
    assert d["kpis"]["pending_reviews"] == pending
    assert d["data_label"].startswith("Synthetic")
    v = client.get(f"{V1}/dashboard/summary?section=VERBAL", headers=auth("admin")).json()
    assert v["kpis"]["total_questions"] < d["kpis"]["total_questions"]


def test_create_question_validation(client, auth):
    body = {"section": "QUANT", "skill": "arithmetic", "concept": "Averages", "difficulty_target": "easy",
            "stem": "What is the average of 4, 8 and 12?", "explanation": "Sum 24 / 3 = 8",
            "options": [{"key": "A", "text": "8", "is_correct": True}, {"key": "B", "text": "6", "is_correct": True},
                        {"key": "C", "text": "9", "is_correct": False}, {"key": "D", "text": "12", "is_correct": False}]}
    assert client.post(f"{V1}/questions", json=body, headers=auth("designer")).status_code == 422
    body["options"][1]["is_correct"] = False
    r = client.post(f"{V1}/questions", json=body, headers=auth("designer"))
    assert r.status_code == 201
    q = r.json()
    assert q["status"] == "pending_review" and q["generation_method"] == "human_authored"
    assert any(c["check"] == "answer_unverified" for c in q["validation"])
    assert client.post(f"{V1}/questions", json=body, headers=auth("reviewer")).status_code == 403


def test_variant_generation_review_and_independence(client, auth):
    src = client.get(f"{V1}/questions?q=QNT-SDT-E2-S", headers=auth("designer")).json()["items"][0]
    r = client.post(f"{V1}/questions/{src['id']}/variants:generate", json={"n": 2, "seed": 7}, headers=auth("designer"))
    assert r.status_code == 201
    out = r.json()
    assert out["run"]["method"] == "template" and len(out["created"]) == 2
    v = out["created"][0]
    assert v["status"] == "pending_review" and v["parent_id"] == src["id"]  # never auto-published
    assert any(c["check"] == "answer_recomputed" and c["status"] == "pass" for c in v["validation"])
    # designer cannot approve (permission), analyst cannot approve (permission)
    assert client.post(f"{V1}/review/{v['id']}/decision", json={"decision": "approve"}, headers=auth("designer")).status_code == 403
    assert client.post(f"{V1}/review/{v['id']}/decision", json={"decision": "approve"}, headers=auth("analyst")).status_code == 403
    # reviewer approves; history records who and when
    r = client.post(f"{V1}/review/{v['id']}/decision", json={"decision": "approve", "comment": "verified"}, headers=auth("reviewer"))
    assert r.status_code == 200 and r.json()["item"]["status"] == "approved"
    assert r.json()["item"]["approved_by"]["name"] == "Dr. Kavya Iyer"
    hist = client.get(f"{V1}/questions/{v['id']}/history", headers=auth("reviewer")).json()
    assert hist["decisions"][-1]["decision"] == "approve"
    # second decision on an approved item is a conflict
    assert client.post(f"{V1}/review/{v['id']}/decision", json={"decision": "reject", "comment": "late"},
                       headers=auth("reviewer")).status_code == 409


def test_reviewer_cannot_approve_own_item(client, auth):
    body = {"section": "LOGICAL", "skill": "patterns", "concept": "Odd one out", "difficulty_target": "medium",
            "stem": "Which number does not belong: 2, 3, 5, 9, 11?", "explanation": "9 is not prime.",
            "options": [{"key": "A", "text": "2", "is_correct": False}, {"key": "B", "text": "9", "is_correct": True},
                        {"key": "C", "text": "5", "is_correct": False}, {"key": "D", "text": "11", "is_correct": False}]}
    q = client.post(f"{V1}/questions", json=body, headers=auth("admin")).json()
    r = client.post(f"{V1}/review/{q['id']}/decision", json={"decision": "approve"}, headers=auth("admin"))
    assert r.status_code == 409 and "Independent" in r.json()["error"]["message"]


def test_failed_validation_blocks_approval(client, auth, db):
    from sqlalchemy import select

    from app.models import Question

    rejected = db.scalar(select(Question).where(Question.status_reason.like("%answer key deliberately%") |
                                                Question.status_reason.like("%recomputed answer disagrees%")))
    assert rejected is not None and rejected.validation_status == "failed"
    rejected.status = "pending_review"
    db.commit()
    r = client.post(f"{V1}/review/{rejected.id}/decision", json={"decision": "approve"}, headers=auth("reviewer"))
    assert r.status_code == 409 and r.json()["error"]["details"]["issues"]


def test_edit_resets_approval_and_logs_revision(client, auth):
    q = client.get(f"{V1}/questions?q=QNT-INT-E3-V01", headers=auth("reviewer")).json()["items"][0]
    detail = client.get(f"{V1}/questions/{q['id']}", headers=auth("reviewer")).json()
    r = client.patch(f"{V1}/questions/{q['id']}", json={"explanation": detail["explanation"] + " Clarified.", "note": "wording"},
                     headers=auth("reviewer"))
    assert r.status_code == 200 and r.json()["status"] == "pending_review" and r.json()["version"] == 2


def test_calibration_results(client, auth):
    latest = client.get(f"{V1}/calibration/runs/latest", headers=auth("analyst")).json()
    assert latest["rasch_fitted"] and latest["n_responses"] >= 45000
    assert any("excluded from the Rasch fit" in w for w in latest["warnings"])
    items = client.get(f"{V1}/calibration/items?variants_only=true&page_size=500", headers=auth("analyst")).json()["items"]
    statuses = {i["status"] for i in items}
    assert {"within_tolerance", "requires_review", "insufficient_data"} <= statuses
    for i in items:
        if i["diff_basis"] == "rasch_logit":
            assert i["diff_ci"][0] <= i["diff"] <= i["diff_ci"][1]


def test_new_calibration_run(client, auth):
    r = client.post(f"{V1}/calibration/runs", json={"tolerance_logits": 0.6}, headers=auth("analyst"))
    assert r.status_code == 201 and r.json()["params"]["tolerance_logits"] == 0.6
    assert client.post(f"{V1}/calibration/runs", json={}, headers=auth("designer")).status_code == 403


def test_response_import_validation(client, auth):
    bad = io.BytesIO(b"slot_code,form_code,item_code\nS1,F1,X\n")
    r = client.post(f"{V1}/calibration/import", files={"file": ("bad.csv", bad, "text/csv")}, data={"preview": "true"},
                    headers=auth("analyst"))
    assert r.status_code == 200 and any("Missing required" in e for e in r.json()["report"]["errors"])
    empty = io.BytesIO(b"   \n")
    r = client.post(f"{V1}/calibration/import", files={"file": ("e.csv", empty, "text/csv")}, headers=auth("analyst"))
    assert r.status_code == 422
    r = client.post(f"{V1}/calibration/import", files={"file": ("x.exe", io.BytesIO(b"MZ"), "application/octet-stream")},
                    headers=auth("analyst"))
    assert r.status_code == 422


def test_leak_dataset_import_and_detection(client, auth):
    raw = (ROOT / "data" / "synthetic" / "leak_simulation_posts.jsonl").read_bytes()
    p = client.post(f"{V1}/leaks/datasets/preview", files={"file": ("posts.jsonl", raw)}, headers=auth("analyst")).json()
    assert p["mapping"]["text"] == "text" and p["n_duplicate_text"] >= 1 and not p["errors"]
    r = client.post(f"{V1}/leaks/datasets", files={"file": ("posts.jsonl", raw)},
                    data={"name": "Re-import test", "source_type": "synthetic_demo"}, headers=auth("analyst"))
    assert r.status_code == 201 and r.json()["n_duplicates"] >= 1
    assert client.post(f"{V1}/leaks/datasets", files={"file": ("posts.jsonl", raw)}, data={"name": "x"},
                       headers=auth("designer")).status_code == 403
    det = client.post(f"{V1}/leaks/detect", json={"replay": True}, headers=auth("analyst")).json()
    assert det["summary"]["records_scanned"] > 0
    truth = json.loads((ROOT / "data" / "synthetic" / "leak_ground_truth.json").read_text())["injections"]
    expected = set(truth["L1_text_and_performance"]["items"]) | set(truth["L2_statistical_only"]["items"]) | set(truth["L3_text_only"]["items"])
    alerts = client.get(f"{V1}/leaks/alerts?severity=critical,high,medium", headers=auth("analyst")).json()["items"]
    assert expected <= {a["question_code"] for a in alerts}
    for a in alerts:
        if a["question_code"] in truth["L2_statistical_only"]["items"]:
            assert a["evidence_class"] == "statistical_suspicion"


def test_leak_text_missing_column_rejected(client, auth):
    bad = io.BytesIO(b'[{"foo": "bar"}]')
    r = client.post(f"{V1}/leaks/datasets/preview", files={"file": ("bad.json", bad)}, headers=auth("analyst"))
    assert r.status_code == 200 and r.json()["errors"]


def test_alert_investigation_workflow(client, auth):
    alerts = client.get(f"{V1}/leaks/alerts?severity=critical&status=open", headers=auth("reviewer")).json()["items"]
    a = alerts[0]
    detail = client.get(f"{V1}/leaks/alerts/{a['id']}", headers=auth("reviewer")).json()
    assert detail["evidence"].get("text_matches") and detail["evidence"].get("performance")
    assert detail["evidence"]["affected_family"]["siblings"]
    base = f"{V1}/leaks/alerts/{a['id']}/actions"
    assert client.post(base, json={"action": "acknowledge"}, headers=auth("designer")).status_code == 403
    assert client.post(base, json={"action": "investigate", "note": "Checking channel"}, headers=auth("reviewer")).status_code == 200
    assert client.post(base, json={"action": "confirm", "note": "short"}, headers=auth("reviewer")).status_code == 409
    r = client.post(base, json={"action": "confirm", "note": "Verbatim copy with answer key; quarantining."}, headers=auth("reviewer"))
    assert r.status_code == 200
    out = r.json()
    assert out["status"] == "confirmed" and out["evidence_class"] == "human_confirmed"
    assert out["question"]["leak_status"] == "confirmed" and out["question"]["status"] == "quarantined"
    assert [e["action"] for e in out["investigation"]["events"]] == ["investigate", "confirm"]
    assert client.post(base, json={"action": "acknowledge"}, headers=auth("reviewer")).status_code == 409


def test_quarantine_and_release(client, auth):
    q = client.get(f"{V1}/questions?q=VRB-SVA-E1-V02", headers=auth("reviewer")).json()["items"][0]
    url = f"{V1}/exposure/items/{q['id']}"
    assert client.post(url + "/quarantine", json={"reason": "Suspicious forum thread"}, headers=auth("designer")).status_code == 403
    assert client.post(url + "/quarantine", json={"reason": "Suspicious forum thread"}, headers=auth("reviewer")).json()["status"] == "quarantined"
    assert client.post(url + "/quarantine", json={"reason": "again"}, headers=auth("reviewer")).status_code == 409
    assert client.post(url + "/release", json={"reason": "Thread was unrelated"}, headers=auth("reviewer")).json()["status"] == "approved"


def test_assembly_overlap_and_quarantine_excluded(client, auth, db):
    from sqlalchemy import select

    from app.models import FormItem, Question

    cfg = {"drive": "Test drive A", "n_slots": 6, "per_section": {"QUANT": 8, "LOGICAL": 8, "VERBAL": 8},
           "max_adjacent_overlap_pct": 10, "max_slot_exposures": 3, "min_slot_spacing": 2, "seed": 99}
    r = client.post(f"{V1}/assembly/runs", json=cfg, headers=auth("designer")).json()
    assert r["status"] == "succeeded", r["diagnostics"]
    assert len(r["forms"]) == 6 and all(f["n_items"] == 24 for f in r["forms"])
    for o in r["overlap"]:
        if o["adjacent"]:
            assert o["smaller_form_pct"] <= 10 and o["constraint_ok"]
    r2 = client.post(f"{V1}/assembly/runs", json=cfg, headers=auth("designer")).json()  # reproducible with same seed
    m1 = [[i["code"] for i in f["items"]] for f in r["forms"]]
    m2 = [[i["code"] for i in f["items"]] for f in r2["forms"]]
    assert m1 == m2
    bad_ids = set(db.scalars(select(Question.id).where(Question.status.in_(("quarantined", "retired", "pending_review")) |
                                                       Question.leak_status.in_(("suspected", "confirmed")))).all())
    form_ids = [f["id"] for f in r["forms"]]
    used = set(db.scalars(select(FormItem.question_id).where(FormItem.form_id.in_(form_ids))).all())
    assert not (used & bad_ids)


def test_impossible_assembly_explains(client, auth):
    cfg = {"drive": "Impossible", "n_slots": 12, "per_section": {"QUANT": 20, "LOGICAL": 20, "VERBAL": 20},
           "max_adjacent_overlap_pct": 0, "max_slot_exposures": 1, "min_slot_spacing": 3, "seed": 1}
    r = client.post(f"{V1}/assembly/runs", json=cfg, headers=auth("designer")).json()
    assert r["status"] == "failed" and r["form_count"] == 0
    assert r["diagnostics"]["explanation"] and r["diagnostics"]["infeasible_cells"]
    v = client.post(f"{V1}/assembly/validate", json=cfg, headers=auth("designer")).json()
    assert not v["feasible_preflight"]


def test_candidate_flow_and_answer_key_protection(client, auth):
    h = auth("candidate2")
    forms = client.get(f"{V1}/assessment/available", headers=h).json()["forms"]
    fid = forms[1]["form_id"]
    content = client.get(f"{V1}/assessment/forms/{fid}", headers=h).json()
    text = json.dumps(content)
    assert "is_correct" not in text and "explanation" not in text and '"code"' not in text
    at = client.post(f"{V1}/assessment/forms/{fid}/attempts", headers=h).json()
    assert at["status"] == "in_progress" and at["remaining_seconds"] > 0
    again = client.post(f"{V1}/assessment/forms/{fid}/attempts", headers=h).json()
    assert again["attempt_id"] == at["attempt_id"]  # resume, not a new attempt
    item = content["items"][0]
    url = f"{V1}/assessment/attempts/{at['attempt_id']}"
    assert client.put(url + "/responses", json={"answers": [{"item_ref": item["item_ref"], "selected_key": "E"}]}, headers=h).status_code == 422
    assert client.put(url + "/responses", json={"answers": [{"item_ref": 10 ** 9, "selected_key": "A"}]}, headers=h).status_code == 422
    s = client.put(url + "/responses", json={"answers": [{"item_ref": item["item_ref"], "selected_key": "B", "time_spent_ms": 4000}]}, headers=h)
    assert s.json()["answers"][str(item["item_ref"])] == "B"
    assert client.get(url, headers=auth("candidate3")).status_code == 404  # other candidates cannot see it
    res = client.post(url + "/submit", headers=h).json()
    assert res["status"] == "submitted" and res["result"]["max_score"] == content["n_items"]
    assert client.post(url + "/submit", headers=h).status_code == 409
    assert client.put(url + "/responses", json={"answers": []}, headers=h).status_code == 409


def test_reports_download(client, auth):
    for kind in ("question_bank", "calibration", "leak_investigations", "form_overlap", "exposure", "slot_comparison",
                 "review_status", "validation_results"):
        r = client.get(f"{V1}/reports/{kind}.csv", headers=auth("analyst"))
        assert r.status_code == 200 and "# generated_at" in r.text and "provenance" in r.text
    pdf = client.get(f"{V1}/reports/calibration.pdf?section=QUANT", headers=auth("analyst"))
    assert pdf.content[:4] == b"%PDF"
    js = client.get(f"{V1}/reports/leak_investigations.json?severity=critical", headers=auth("analyst")).json()
    assert js["rows"] and all(r["severity"] == "critical" for r in js["rows"])
    assert client.get(f"{V1}/reports/question_bank.csv", headers=auth("candidate1")).status_code == 403


def test_policy_update_validation(client, auth):
    url = f"{V1}/settings/policies/assembly"
    assert client.put(url, json={"values": {"max_adjacent_overlap_pct": 15.0}}, headers=auth("designer")).status_code == 403
    assert client.put(url, json={"values": {"bogus": 1}}, headers=auth("admin")).status_code == 422
    assert client.put(url, json={"values": {"max_adjacent_overlap_pct": "lots"}}, headers=auth("admin")).status_code == 422
    r = client.put(url, json={"values": {"max_adjacent_overlap_pct": 12.0}}, headers=auth("admin"))
    assert r.status_code == 200 and r.json()["max_adjacent_overlap_pct"] == 12.0
    client.put(url, json={"values": {"max_adjacent_overlap_pct": 10.0}}, headers=auth("admin"))
    audit = client.get(f"{V1}/audit?action=settings", headers=auth("admin")).json()
    assert audit["total"] >= 2


def test_no_approved_item_carries_a_failed_quality_check(db):
    """Regression: the seed once approved 112 near-duplicates whose failed screen was only recorded, not enforced."""
    from sqlalchemy import func, select

    from app.models import Question, ValidationResult

    bad = db.execute(select(Question.code, ValidationResult.check).join(ValidationResult, ValidationResult.question_id == Question.id)
                     .where(Question.status == "approved", ValidationResult.status == "fail")).all()
    assert bad == [], bad
    per_tpl = dict(db.execute(select(Question.template_id, func.count()).where(Question.status == "approved", Question.org_id == 1, Question.template_id.is_not(None))
                              .group_by(Question.template_id)).all())
    assert len(per_tpl) == 16 and min(per_tpl.values()) >= 12


def test_ready_returns_503_when_database_not_migrated(client, monkeypatch):
    from sqlalchemy import text

    from app.db.session import SessionLocal

    class Broken:
        def execute(self, stmt, *a, **k):
            if "alembic_version" in str(stmt):
                raise RuntimeError("no table")
            return SessionLocal().execute(text("SELECT 1"))

        def close(self):
            pass

    from app.db.session import get_db
    from app.main import app

    app.dependency_overrides[get_db] = lambda: Broken()
    try:
        assert client.get(f"{V1}/ready").status_code == 503
    finally:
        app.dependency_overrides.pop(get_db, None)
