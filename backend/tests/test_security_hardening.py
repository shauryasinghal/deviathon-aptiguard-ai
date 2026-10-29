"""Session revocation, database-backed login limiting, and the tamper-evident audit chain."""
import uuid

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


def test_failed_login_on_fresh_database_without_organisation_returns_401(tmp_path, client):
    """Fresh production database (migrated + bootstrapped, no organisation yet): a failed login must be a clean 401,
    not a foreign-key error on the audit row. Regression for the Docker production smoke test."""
    from alembic import command
    from alembic.config import Config
    from pathlib import Path
    import os

    from sqlalchemy import create_engine, event, func
    from sqlalchemy.orm import sessionmaker

    from app.bootstrap import ensure_reference_data
    from app.db.session import get_db
    from app.main import app
    from app.models import AuditEvent, AuthFailure, Organization

    url = f"sqlite:///{tmp_path}/fresh.db"
    backend = Path(__file__).resolve().parents[1]
    cfg = Config(str(backend / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend / "alembic"))
    old = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    get_settings.cache_clear()
    try:
        command.upgrade(cfg, "head")
    finally:
        if old is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = old
        get_settings.cache_clear()
    eng = create_engine(url)
    event.listen(eng, "connect", lambda c, _: c.execute("PRAGMA foreign_keys=ON"))  # enforce the FK as PostgreSQL does
    Fresh = sessionmaker(bind=eng)
    with Fresh() as s:
        ensure_reference_data(s)
        s.commit()
        assert s.scalar(select(func.count()).select_from(Organization)) == 0

    def _fresh_db():
        with Fresh() as s:
            yield s

    app.dependency_overrides[get_db] = _fresh_db
    try:
        r = client.post("/api/v1/auth/login", json={"email": "admin@aptiguard.demo", "password": "AptiGuard-Demo-2026"})
    finally:
        app.dependency_overrides.pop(get_db, None)
    assert r.status_code == 401, r.text
    assert r.json()["error"]["code"] == "invalid_credentials"
    with Fresh() as s:
        assert s.scalar(select(func.count()).select_from(AuthFailure)) == 1  # limiter still counts the failure
        assert s.scalar(select(func.count()).select_from(AuditEvent)) == 0  # no organisation to attribute it to
    eng.dispose()


# ------------------------------------------------------------------ failed-login auditing (unknown vs real account)
def _audit_state(db):
    from sqlalchemy import func, select

    from app.models import AuditEvent

    db.expire_all()
    per_org = dict(db.execute(select(AuditEvent.org_id, func.count()).group_by(AuditEvent.org_id)).all())
    return per_org, db.scalar(select(func.max(AuditEvent.id)))


def test_unknown_email_login_failures_are_not_audited_in_any_organisation(client, db):
    """Regression: unknown emails used to be written to the first organisation's audit log (unauthenticated flooding)."""
    from sqlalchemy import func, select

    from app.models import AuthFailure

    before = _audit_state(db)
    emails = [f"nobody-{i}-{uuid.uuid4().hex[:8]}@nowhere.test" for i in range(5)]  # distinct limiter keys: none is rate limited
    for email in emails:
        r = client.post(f"{V1}/auth/login", json={"email": email, "password": "x" * 12})
        assert r.status_code == 401 and r.json()["error"]["code"] == "invalid_credentials"
    assert _audit_state(db) == before  # no row for any organisation, chain head unchanged
    # the limiter still records each failure. Count the exact keys (TestClient's client host is "testclient"): the limiter
    # prunes expired rows of other keys on every failure, so a table-wide count would be time dependent.
    keys = [key_for("testclient", e) for e in emails]
    assert db.scalar(select(func.count()).select_from(AuthFailure).where(AuthFailure.key_hash.in_(keys))) == 5
    assert client.get(f"{V1}/audit/verify", headers=_login(client, "admin@aptiguard.demo")).json()["ok"]


def test_failed_login_for_a_real_account_is_still_audited_in_its_own_organisation(client, db):
    from sqlalchemy import select

    from app.models import AuditEvent, User

    org = db.scalar(select(User.org_id).where(User.email == "analyst@aptiguard.demo"))
    before = _audit_state(db)[0].get(org, 0)
    r = client.post(f"{V1}/auth/login", json={"email": "analyst@aptiguard.demo", "password": "definitely-wrong"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "invalid_credentials"
    per_org, _ = _audit_state(db)
    assert per_org.get(org, 0) == before + 1
    ev = db.scalars(select(AuditEvent).where(AuditEvent.action == "auth.login_failed").order_by(AuditEvent.id.desc())).first()
    assert ev.org_id == org and ev.details == {"email_domain": "aptiguard.demo", "reason": "invalid_credentials"}
    assert "definitely-wrong" not in str(ev.details) + ev.summary
    # a successful login clears the limiter for this account so later tests are unaffected
    assert client.post(f"{V1}/auth/login", json={"email": "analyst@aptiguard.demo", "password": "AptiGuard-Demo-2026"}).status_code == 200


def test_inactive_account_failure_is_audited_with_its_reason(client, db):
    from sqlalchemy import select

    from app.models import AuditEvent, User

    u = db.scalar(select(User).where(User.email == "candidate2@aptiguard.demo"))
    u.is_active = False
    db.commit()
    try:
        r = client.post(f"{V1}/auth/login", json={"email": "candidate2@aptiguard.demo", "password": "AptiGuard-Demo-2026"})
        assert r.status_code == 401 and r.json()["error"]["message"] == "Invalid email or password"  # still generic
        ev = db.scalars(select(AuditEvent).where(AuditEvent.action == "auth.login_failed").order_by(AuditEvent.id.desc())).first()
        assert ev.org_id == u.org_id and ev.details["reason"] == "inactive"
    finally:
        u.is_active = True
        db.commit()
