"""Session revocation, database-backed login limiting, and the tamper-evident audit chain."""
import pytest
from sqlalchemy import select, text

from app.core.config import get_settings
from app.core.ratelimit import FailureLimiter, key_for, login_limiter

V1 = "/api/v1"
PW = get_settings().demo_password


def _login(client, email):
    r = client.post(f"{V1}/auth/login", json={"email": email, "password": PW})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(autouse=True)
def _clean_limiter(seeded):
    from app.db.session import SessionLocal

    with SessionLocal() as s:
        login_limiter.reset(s)
        s.commit()
    yield


def test_logout_revokes_all_sessions_of_that_user(client):
    a = _login(client, "reviewer2@aptiguard.demo")
    b = _login(client, "reviewer2@aptiguard.demo")  # second device
    assert client.get(f"{V1}/auth/me", headers=a).status_code == 200
    assert client.post(f"{V1}/auth/logout", headers=a).status_code == 200
    for h in (a, b):
        r = client.get(f"{V1}/auth/me", headers=h)
        assert r.status_code == 401 and "revoked" in r.json()["error"]["message"]
    c = _login(client, "reviewer2@aptiguard.demo")  # a fresh sign-in works again
    assert client.get(f"{V1}/auth/me", headers=c).status_code == 200


def test_admin_can_revoke_sessions_others_cannot(client, db):
    from app.models import User

    victim = db.scalar(select(User).where(User.email == "candidate3@aptiguard.demo"))
    vt = _login(client, "candidate3@aptiguard.demo")
    assert client.post(f"{V1}/auth/users/{victim.id}/revoke-sessions", headers=_login(client, "designer@aptiguard.demo")).status_code == 403
    assert client.post(f"{V1}/auth/users/{victim.id}/revoke-sessions", headers=vt).status_code == 403
    assert client.post(f"{V1}/auth/users/{victim.id}/revoke-sessions", headers=_login(client, "admin@aptiguard.demo")).status_code == 200
    assert client.get(f"{V1}/auth/me", headers=vt).status_code == 401
    assert client.post(f"{V1}/auth/users/999999/revoke-sessions", headers=_login(client, "admin@aptiguard.demo")).status_code == 404


def test_limiter_state_is_shared_and_survives_restart(client, db):
    s = get_settings()
    for _ in range(s.login_max_failures):
        client.post(f"{V1}/auth/login", json={"email": "analyst@aptiguard.demo", "password": "wrong"})
    fresh = FailureLimiter()  # a new process/limiter instance sees the same state through the database
    assert fresh.retry_after(db, key_for("testclient", "analyst@aptiguard.demo"), s.login_max_failures, s.login_window_seconds) > 0
    assert client.post(f"{V1}/auth/login", json={"email": "analyst@aptiguard.demo", "password": PW}).status_code == 429
    rows = db.execute(text("SELECT key_hash FROM auth_failures")).scalars().all()
    assert rows and all("@" not in r and len(r) == 64 for r in rows)  # no raw emails stored


def test_audit_chain_verifies_and_detects_tampering(client, db):
    h = _login(client, "admin@aptiguard.demo")
    ok = client.get(f"{V1}/audit/verify", headers=h).json()
    assert ok["ok"] and ok["checked"] > 20
    assert client.get(f"{V1}/audit/verify", headers=_login(client, "designer@aptiguard.demo")).status_code == 403
    target = db.execute(text("SELECT id, summary FROM audit_events ORDER BY id LIMIT 1 OFFSET 10")).one()
    db.execute(text("UPDATE audit_events SET summary = :s WHERE id = :i"), {"s": target.summary + " (edited)", "i": target.id})
    db.commit()
    try:
        bad = client.get(f"{V1}/audit/verify", headers=h).json()
        assert not bad["ok"] and bad["broken_at_id"] == target.id and bad["reason"] == "content hash mismatch"
    finally:
        db.execute(text("UPDATE audit_events SET summary = :s WHERE id = :i"), {"s": target.summary, "i": target.id})
        db.commit()
    assert client.get(f"{V1}/audit/verify", headers=h).json()["ok"]


def test_deleting_an_audit_event_breaks_the_chain(db):
    from app.services.audit import verify_chain

    row = db.execute(text("SELECT * FROM audit_events ORDER BY id LIMIT 1 OFFSET 5")).mappings().one()
    db.execute(text("DELETE FROM audit_events WHERE id = :i"), {"i": row["id"]})
    res = verify_chain(db)
    db.rollback()  # restore
    assert not res["ok"] and res["reason"] == "prev_hash mismatch"
    assert verify_chain(db)["ok"]


def test_migration_0004_backfills_existing_audit_rows(tmp_path):
    from alembic import command
    from alembic.config import Config
    from pathlib import Path

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    url = f"sqlite:///{tmp_path}/mig.db"
    backend = Path(__file__).resolve().parents[1]
    cfg = Config(str(backend / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend / "alembic"))
    import os

    old = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    get_settings.cache_clear()
    try:
        command.upgrade(cfg, "0003")
        eng = create_engine(url)
        with eng.begin() as c:
            c.execute(text("INSERT INTO organizations (id, name, slug, created_at) VALUES (1, 'o', 'o', '2026-01-01 00:00:00')"))
            for i in range(3):
                c.execute(text("INSERT INTO audit_events (org_id, actor_label, action, entity_type, summary, details, created_at) "
                               "VALUES (1, 'system', 'x.y', 'test', :s, :d, '2026-01-01 00:00:0' || :i)"),
                          {"s": f"event {i}", "d": '{"k": %d}' % i, "i": i})
        command.upgrade(cfg, "head")
        from app.services.audit import verify_chain

        with Session(eng) as s:
            res = verify_chain(s)
        assert res["ok"] and res["checked"] == 3
    finally:
        if old is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = old
        get_settings.cache_clear()


def test_bootstrap_is_idempotent_and_create_admin_enforces_policy(db):
    from app.bootstrap import create_admin, ensure_reference_data
    from app.models import Permission, Role, Section, User

    before = (db.scalar(select(text("count(*)")).select_from(Permission)), db.scalar(select(text("count(*)")).select_from(Role)))
    assert ensure_reference_data(db) == {"permissions": 0, "roles": 0, "sections": 0}  # seeded DB: nothing to add
    assert (db.scalar(select(text("count(*)")).select_from(Permission)), db.scalar(select(text("count(*)")).select_from(Role))) == before
    with pytest.raises(ValueError, match="12 characters"):
        create_admin(db, "Acme", "acme-boot", "boss@acme.test", "Boss", "short")
    with pytest.raises(ValueError, match="already exists"):
        create_admin(db, "Acme", "acme-boot", "admin@aptiguard.demo", "Boss", "a-very-long-password")
    u = create_admin(db, "Acme", "acme-boot", "Boss@Acme.test", "Boss", "a-very-long-password")
    assert u.email == "boss@acme.test" and u.role.name == "admin" and u.org.slug == "acme-boot"
    assert db.scalar(select(Section).where(Section.code == "VERBAL")) is not None
    db.rollback()
    assert db.scalar(select(User).where(User.email == "boss@acme.test")) is None
