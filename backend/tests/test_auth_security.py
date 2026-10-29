"""Authentication, token handling, rate limiting and production-configuration guards."""
from datetime import datetime, timedelta, timezone

import jwt
import pytest

from app.core.config import Settings, get_settings
from app.core.ratelimit import login_limiter

V1 = "/api/v1"
PW = get_settings().demo_password


@pytest.fixture(autouse=True)
def _clear_limiter():
    login_limiter.reset()
    yield
    login_limiter.reset()


@pytest.mark.parametrize("email,role", [("admin", "admin"), ("designer", "designer"), ("reviewer", "reviewer"),
                                        ("analyst", "analyst"), ("candidate1", "candidate")])
def test_demo_accounts_sign_in(client, email, role):
    r = client.post(f"{V1}/auth/login", json={"email": f"{email}@aptiguard.demo", "password": PW})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["user"]["role"] == role and "password" not in str(body["user"]).lower()
    me = client.get(f"{V1}/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200 and me.json()["email"] == f"{email}@aptiguard.demo"


def test_email_is_normalised(client):
    r = client.post(f"{V1}/auth/login", json={"email": "  Candidate1@AptiGuard.demo ", "password": PW})
    assert r.status_code == 200


def test_wrong_password_and_unknown_user_are_indistinguishable(client):
    a = client.post(f"{V1}/auth/login", json={"email": "candidate1@aptiguard.demo", "password": PW + " "})
    b = client.post(f"{V1}/auth/login", json={"email": "nobody@aptiguard.demo", "password": PW})
    assert a.status_code == b.status_code == 401
    assert a.json() == b.json()


def test_inactive_account_cannot_sign_in_or_use_token(client, db):
    from sqlalchemy import select

    from app.models import User

    tok = client.post(f"{V1}/auth/login", json={"email": "candidate3@aptiguard.demo", "password": PW}).json()["access_token"]
    u = db.scalar(select(User).where(User.email == "candidate3@aptiguard.demo"))
    u.is_active = False
    db.commit()
    try:
        r = client.post(f"{V1}/auth/login", json={"email": "candidate3@aptiguard.demo", "password": PW})
        assert r.status_code == 401
        assert client.get(f"{V1}/auth/me", headers={"Authorization": f"Bearer {tok}"}).status_code == 401
    finally:
        u.is_active = True
        db.commit()


def _forge(claims: dict, secret: str | None = None, alg: str = "HS256") -> str:
    return jwt.encode(claims, secret or get_settings().jwt_secret, algorithm=alg)


@pytest.mark.parametrize("make", [
    lambda: "not-a-jwt",
    lambda: _forge({"sub": "1", "iss": "aptiguard", "iat": datetime.now(timezone.utc) - timedelta(hours=10),
                    "exp": datetime.now(timezone.utc) - timedelta(minutes=1)}),           # expired
    lambda: _forge({"sub": "1", "iss": "aptiguard", "iat": datetime.now(timezone.utc),
                    "exp": datetime.now(timezone.utc) + timedelta(hours=1)}, secret="x" * 40),  # wrong key
    lambda: _forge({"sub": "1", "iss": "someone-else", "iat": datetime.now(timezone.utc),
                    "exp": datetime.now(timezone.utc) + timedelta(hours=1)}),              # wrong issuer
    lambda: _forge({"sub": "1", "iss": "aptiguard"}),                                       # no exp/iat
    lambda: jwt.encode({"sub": "1", "iss": "aptiguard"}, key=None, algorithm="none"),        # unsigned
    lambda: _forge({"sub": "99999", "iss": "aptiguard", "iat": datetime.now(timezone.utc),
                    "exp": datetime.now(timezone.utc) + timedelta(hours=1)}),              # unknown user
])
def test_bad_tokens_rejected(client, make):
    r = client.get(f"{V1}/auth/me", headers={"Authorization": f"Bearer {make()}"})
    assert r.status_code == 401


def test_login_rate_limited_after_repeated_failures(client):
    s = get_settings()
    for _ in range(s.login_max_failures):
        assert client.post(f"{V1}/auth/login", json={"email": "admin@aptiguard.demo", "password": "wrong"}).status_code == 401
    r = client.post(f"{V1}/auth/login", json={"email": "admin@aptiguard.demo", "password": PW})
    assert r.status_code == 429 and r.json()["error"]["details"]["retry_after_seconds"] > 0
    # other accounts are not locked out by someone else's failures
    assert client.post(f"{V1}/auth/login", json={"email": "analyst@aptiguard.demo", "password": PW}).status_code == 200


def test_failed_login_audit_does_not_store_password(client, db):
    from sqlalchemy import select

    from app.models import AuditEvent

    client.post(f"{V1}/auth/login", json={"email": "admin@aptiguard.demo", "password": "S3cret-should-not-be-logged"})
    ev = db.scalars(select(AuditEvent).where(AuditEvent.action == "auth.login_failed").order_by(AuditEvent.id.desc())).first()
    assert "S3cret" not in str(ev.details) and "S3cret" not in ev.summary


def test_production_guard_rejects_unsafe_configuration():
    with pytest.raises(ValueError, match="DEMO_MODE"):
        Settings(app_env="production", demo_mode=True, jwt_secret="y" * 48)
    with pytest.raises(ValueError, match="JWT_SECRET"):
        Settings(app_env="production", demo_mode=False)
    ok = Settings(app_env="production", demo_mode=False, jwt_secret="z" * 48)
    assert ok.is_production


def test_demo_status_exposes_demo_credentials_only_in_demo_mode(client, monkeypatch):
    assert client.get(f"{V1}/demo-status").json()["demo_password"] == PW
    from app.api.v1 import system

    monkeypatch.setattr(system, "get_settings", lambda: Settings(demo_mode=False))
    body = client.get(f"{V1}/demo-status").json()
    assert "demo_password" not in body and "demo_accounts" not in body


def test_seed_refuses_when_demo_mode_disabled(monkeypatch, db):
    from app.demo import seed

    monkeypatch.setattr("app.core.config.get_settings", lambda: Settings(demo_mode=False))
    with pytest.raises(RuntimeError, match="Refusing"):
        seed.seed_demo(db)


def test_security_headers_present(client):
    r = client.get(f"{V1}/health")
    assert r.headers["X-Content-Type-Options"] == "nosniff" and r.headers["X-Frame-Options"] == "DENY"


@pytest.mark.parametrize("env", ["prod", "staging", "", "live"])
def test_unknown_app_env_is_rejected(env):
    with pytest.raises(ValueError, match="APP_ENV"):
        Settings(app_env=env)


def test_app_env_is_case_and_space_normalised_before_the_production_guard():
    with pytest.raises(ValueError, match="DEMO_MODE"):
        Settings(app_env=" Production ", demo_mode=True, jwt_secret="q" * 48)
