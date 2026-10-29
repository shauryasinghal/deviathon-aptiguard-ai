"""Regressions found by the independent review of hardening round 2 (each failed before its fix)."""
from sqlalchemy import select, text

from app.models import Attempt
from tests.test_timing_and_expiry import _backdate_interval, _expire, _responses, _start

V1 = "/api/v1"


def test_p1_audit_action_groups_are_org_scoped(client, auth):
    a = client.get(f"{V1}/audit", headers=auth("admin")).json()["action_groups"]
    assert "calibration" in a or "assembly" in a or "review" in a
    from app.core.security import hash_password
    from app.db.session import SessionLocal
    from app.models import Organization, Role, User

    with SessionLocal() as s:
        org = Organization(name="Probe Tenant", slug="probe-tenant")
        s.add(org)
        s.flush()
        s.add(User(org_id=org.id, email="admin@probe.test", full_name="Probe Admin", password_hash=hash_password("Probe-Tenant-Pass-1"),
                   role_id=s.scalar(select(Role.id).where(Role.name == "admin"))))
        s.commit()
    tok = client.post(f"{V1}/auth/login", json={"email": "admin@probe.test", "password": "Probe-Tenant-Pass-1"}).json()["access_token"]
    b = client.get(f"{V1}/audit", headers={"Authorization": f"Bearer {tok}"}).json()
    own = {e["action"].split(".")[0] for e in b["items"]}
    assert set(b["action_groups"]) <= own, f"leaks other tenants' action groups: {set(b['action_groups']) - own}"


def test_p2_resume_gap_is_not_credited_to_the_last_item(client, auth, db):
    h, aid, refs, fid = _start(client, auth, db)
    url = f"{V1}/assessment/attempts/{aid}/focus"
    client.post(url, json={"item_ref": refs[0]}, headers=h)
    _backdate_interval(db, aid, 5)
    client.post(url, json={"item_ref": refs[1]}, headers=h)
    _backdate_interval(db, aid, 600)  # candidate closed the tab / lost the connection for ten minutes
    assert client.post(f"{V1}/assessment/forms/{fid}/attempts", headers=h).status_code in (200, 201)  # resume
    client.post(url, json={"item_ref": refs[0]}, headers=h)
    row = _responses(db, aid).get(refs[1])
    credited = (row.response_time_ms or 0) if row else 0
    assert credited < 60_000, f"{credited} ms of offline time credited to an item"
    assert _responses(db, aid)[refs[0]].response_time_ms < 60_000


def test_p3_submit_after_deadline_plus_grace_is_stamped_at_the_deadline(client, auth, db):
    h, aid, refs, _ = _start(client, auth, db)
    _expire(db, aid, 600)
    r = client.post(f"{V1}/assessment/attempts/{aid}/submit", headers=h)
    db.expire_all()
    a = db.get(Attempt, aid)
    assert a.submitted_at <= a.deadline_at, f"submitted_at {a.submitted_at} is after deadline {a.deadline_at} (HTTP {r.status_code})"


def test_p9_alternating_and_stale_events_never_credit_more_than_elapsed_time(client, auth, db):
    h, aid, refs, _ = _start(client, auth, db)
    url = f"{V1}/assessment/attempts/{aid}/focus"
    client.post(url, json={"item_ref": refs[0]}, headers=h)
    _backdate_interval(db, aid, 10)
    for r in (refs[1], refs[0], refs[1], refs[0], refs[2]):  # two tabs fighting over the pointer
        client.post(url, json={"item_ref": r}, headers=h)
    total = sum((x.response_time_ms or 0) for x in _responses(db, aid).values())
    assert 9_000 <= total <= 20_000


def test_p6_empty_chain_and_anchor(db):
    from app.services.audit import GENESIS, verify_chain

    db.execute(text("DELETE FROM audit_events"))
    ok = verify_chain(db)
    anchored = verify_chain(db, anchor_count=1, anchor_head="a" * 64)
    db.rollback()
    assert ok == {"ok": True, "checked": 0, "head": GENESIS, "anchor_verified": False}
    assert not anchored["ok"]


def test_p8_audit_verify_exposes_global_counts_to_every_tenant(client, auth):
    own_org = client.get(f"{V1}/audit?page_size=1", headers=auth("admin")).json()["total"]
    v = client.get(f"{V1}/audit/verify", headers=auth("admin")).json()
    assert v["checked"] >= own_org  # global chain: a tenant learns the platform-wide event count (documented below)


def test_p11_item_import_parent_code_is_org_scoped(db):
    import pandas as pd
    from app.models import Organization, Question
    from app.services.importers import import_item_bank

    org = Organization(name="Parent Probe", slug="parent-probe")
    db.add(org)
    db.flush()
    a_code = db.scalar(select(Question.code).where(Question.org_id != org.id, Question.is_source.is_(True)))
    df = pd.DataFrame([{"item_code": "PP-1", "section": "QUANT", "stem": "What is 12 plus 30 in this probe?", "option_a": "42",
                        "option_b": "41", "option_c": "43", "option_d": "40", "correct_option": "A", "parent_code": a_code}])
    try:
        import_item_bank(db, org.id, None, df, "probe")
        q = db.scalar(select(Question).where(Question.code == "PP-1"))
        assert q is not None and q.parent_id is None, "variant was linked to another tenant's question"
    finally:
        db.rollback()


# ------------------------------------------------------------------ expiry entry points
def _lifespan_client(monkeypatch, seconds):
    import app.main as m
    from fastapi.testclient import TestClient

    monkeypatch.setattr(m.settings, "expiry_sweep_seconds", seconds)
    return TestClient(m.app)


def _wait_status(db, aid, want, timeout=8.0):
    import time

    end = time.time() + timeout
    while time.time() < end:
        db.expire_all()
        if db.get(Attempt, aid).status == want:
            return True
        time.sleep(0.2)
    return False


def test_background_sweep_finalises_expired_attempts(client, auth, db, monkeypatch):
    h, aid, refs, _ = _start(client, auth, db)
    _expire(db, aid, 120)
    with _lifespan_client(monkeypatch, 1):  # entering the context runs the application lifespan
        assert _wait_status(db, aid, "submitted"), "the in-process sweep never finalised the expired attempt"


def test_sweep_interval_zero_disables_the_background_task(client, auth, db, monkeypatch):
    h, aid, refs, _ = _start(client, auth, db)
    _expire(db, aid, 120)
    with _lifespan_client(monkeypatch, 0):
        assert not _wait_status(db, aid, "submitted", timeout=2.5), "sweep ran although EXPIRY_SWEEP_SECONDS=0"
    # the lazy path and the external script still work afterwards
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location("finalize_expired_script", Path(__file__).resolve().parents[2] / "scripts" / "finalize_expired.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.main() == 0
    assert _wait_status(db, aid, "submitted", timeout=1)
    assert mod.main() == 0  # second run: nothing left, no error (idempotent)


def test_focus_after_deadline_plus_grace_finalises_instead_of_recording(client, auth, db):
    h, aid, refs, _ = _start(client, auth, db)
    client.post(f"{V1}/assessment/attempts/{aid}/focus", json={"item_ref": refs[0]}, headers=h)
    _expire(db, aid, 120)
    r = client.post(f"{V1}/assessment/attempts/{aid}/focus", json={"item_ref": refs[1]}, headers=h)
    assert r.status_code == 409
    db.expire_all()
    a = db.get(Attempt, aid)
    assert a.status == "submitted" and a.submitted_at == a.deadline_at and a.current_item_ref is None
    assert _responses(db, aid)[refs[1]].response_time_ms is None  # the late event recorded no time


def test_second_tenant_can_author_questions_next_to_overlapping_names(client):
    """Two tenants authoring at the same time must not collide on generated codes (global unique namespace)."""
    from app.core.security import hash_password
    from app.db.session import SessionLocal
    from app.models import Organization, Role, User

    with SessionLocal() as s:
        org = Organization(name="Author Tenant", slug="author-tenant")
        s.add(org)
        s.flush()
        s.add(User(org_id=org.id, email="admin@author.test", full_name="Author Admin", password_hash=hash_password("Author-Tenant-Pass-1"),
                   role_id=s.scalar(select(Role.id).where(Role.name == "admin"))))
        s.commit()
    tok = client.post(f"{V1}/auth/login", json={"email": "admin@author.test", "password": "Author-Tenant-Pass-1"}).json()["access_token"]
    hb = {"Authorization": f"Bearer {tok}"}
    body = {"section": "QUANT", "concept": "Percentages", "skill": "percent", "difficulty_target": "easy",
            "stem": "What is 10 percent of 250 for the overlap test?", "explanation": "0.1 x 250 = 25",
            "options": [{"key": "A", "text": "25", "is_correct": True}, {"key": "B", "text": "20", "is_correct": False},
                        {"key": "C", "text": "30", "is_correct": False}, {"key": "D", "text": "35", "is_correct": False}]}
    r1 = client.post(f"{V1}/questions", json=body, headers=hb)
    assert r1.status_code == 201, r1.text
    r2 = client.post(f"{V1}/questions", json={**body, "stem": "What is 10 percent of 350 for the overlap test?", "explanation": "0.1 x 350 = 35",
                                               "options": [{"key": "A", "text": "35", "is_correct": True}, {"key": "B", "text": "30", "is_correct": False},
                                                           {"key": "C", "text": "40", "is_correct": False}, {"key": "D", "text": "45", "is_correct": False}]},
                     headers=hb)
    assert r2.status_code == 201, r2.text
    assert r1.json()["code"] != r2.json()["code"]
