"""Edge cases for the human-review state machine and leak detection on empty / duplicated / hostile input."""
import json

import pytest
from sqlalchemy import func, select

from app.models import LeakAlert, Question, ReviewDecision

V1 = "/api/v1"


def _pending(db):
    return db.scalar(select(Question).where(Question.status == "pending_review").order_by(Question.id.desc()))


def test_designer_cannot_decide_and_unknown_item_is_404(client, auth, db):
    q = _pending(db)
    assert client.post(f"{V1}/review/{q.id}/decision", json={"decision": "approve"}, headers=auth("designer")).status_code == 403
    assert client.post(f"{V1}/review/{q.id}/decision", json={"decision": "approve"}, headers=auth("candidate1")).status_code == 403
    assert client.post(f"{V1}/review/999999/decision", json={"decision": "approve"}, headers=auth("reviewer")).status_code == 404
    assert client.post(f"{V1}/review/{q.id}/decision", json={"decision": "approve"}).status_code == 401


def test_rejection_needs_a_reason_and_invalid_decisions_are_refused(client, auth, db):
    q = _pending(db)
    h = auth("reviewer")
    assert client.post(f"{V1}/review/{q.id}/decision", json={"decision": "reject"}, headers=h).status_code == 409
    assert client.post(f"{V1}/review/{q.id}/decision", json={"decision": "reject", "comment": "no"}, headers=h).status_code == 409
    assert client.post(f"{V1}/review/{q.id}/decision", json={"decision": "publish_now"}, headers=h).status_code == 422
    db.expire_all()
    assert db.get(Question, q.id).status == "pending_review"  # nothing changed


def test_decided_item_cannot_be_decided_again_and_history_is_kept(client, auth, db):
    q = _pending(db)
    h = auth("reviewer")
    before = db.scalar(select(func.count()).select_from(ReviewDecision).where(ReviewDecision.question_id == q.id))
    r = client.post(f"{V1}/review/{q.id}/decision", json={"decision": "reject", "comment": "Distractor B is also correct"}, headers=h)
    assert r.status_code == 200
    again = client.post(f"{V1}/review/{q.id}/decision", json={"decision": "approve"}, headers=auth("reviewer2"))
    assert again.status_code == 409 and "pending review" in again.text
    db.expire_all()
    assert db.get(Question, q.id).status == "rejected"
    assert db.scalar(select(func.count()).select_from(ReviewDecision).where(ReviewDecision.question_id == q.id)) == before + 1


def test_generated_items_are_never_auto_approved(client, auth, db):
    src = db.scalar(select(Question).where(Question.is_source.is_(True), Question.status == "approved",
                                           Question.template_id.is_not(None)))
    r = client.post(f"{V1}/questions/{src.id}/variants:generate", json={"count": 2, "difficulty": src.difficulty_target},
                    headers=auth("designer"))
    assert r.status_code == 201, r.text
    ids = [c["id"] for c in r.json().get("created", r.json().get("items", []))] or []
    assert ids, r.json()
    db.expire_all()
    assert all(db.get(Question, i).status == "pending_review" for i in ids)


def test_leak_detection_on_a_tenant_with_no_data_is_clean(client):
    from app.core.security import hash_password
    from app.db.session import SessionLocal
    from app.models import Organization, Role, User

    with SessionLocal() as s:
        org = Organization(name="Empty Tenant", slug="empty-tenant")
        s.add(org)
        s.flush()
        s.add(User(org_id=org.id, email="admin@empty.test", full_name="Empty Admin", password_hash=hash_password("Empty-Tenant-Pass-1"),
                   role_id=s.scalar(select(Role.id).where(Role.name == "admin"))))
        s.commit()
    tok = client.post(f"{V1}/auth/login", json={"email": "admin@empty.test", "password": "Empty-Tenant-Pass-1"}).json()["access_token"]
    h = {"Authorization": f"Bearer {tok}"}
    r = client.post(f"{V1}/leaks/detect", json={}, headers=h)
    assert r.status_code == 200, r.text
    assert client.get(f"{V1}/leaks/alerts", headers=h).json()["total"] == 0
    assert client.post(f"{V1}/calibration/runs", json={}, headers=h).status_code in (201, 422)  # no 500 on an empty tenant


def _upload(client, h, body: bytes, name="posts.jsonl"):
    return client.post(f"{V1}/leaks/datasets", headers=h, data={"name": "edge dataset", "source_type": "simulated"},
                       files={"file": (name, body, "application/octet-stream")})


def test_leak_dataset_rejects_malformed_and_wrong_types(client, auth):
    h = auth("analyst")
    assert _upload(client, h, b"", "empty.jsonl").status_code in (400, 422)
    assert _upload(client, h, b"not json at all\n{broken", "bad.jsonl").status_code in (400, 422)
    assert _upload(client, h, b"MZ\x90\x00", "payload.exe").status_code in (400, 415, 422)
    row = {"post_id": "p1", "channel": "c", "channel_type": "chat", "posted_at": "2026-09-14T04:00:00Z", "text": "hello"}
    dup = (json.dumps(row) + "\n" + json.dumps(row) + "\n").encode()
    r = _upload(client, h, dup)
    assert r.status_code in (201, 422), r.text  # either rejected or de-duplicated; never a 500


def test_duplicate_detection_runs_do_not_duplicate_alerts(client, auth, db):
    h = auth("analyst")
    assert client.post(f"{V1}/leaks/detect", json={}, headers=h).status_code == 200
    n1 = db.scalar(select(func.count()).select_from(LeakAlert))
    assert client.post(f"{V1}/leaks/detect", json={}, headers=h).status_code == 200
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(LeakAlert)) == n1  # alerts are updated in place, not re-created
