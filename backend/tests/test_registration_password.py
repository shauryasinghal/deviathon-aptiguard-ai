"""Email/password self-registration, password reset and demo-login regression.

Public registration may only create a CANDIDATE in the organisation named by REGISTRATION_ORG_SLUG; demo accounts are
untouchable. No real e-mail is sent: reset links are captured from the development-only log delivery.
"""
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.ratelimit import login_limiter
from app.db.base import utcnow
from app.demo.seed import DEMO_ORG_SLUG
from app.models import AuditEvent, AuthToken, Candidate, Organization, User

V1 = "/api/v1"
DEMO_PW = get_settings().demo_password
GOOD_PW = "Correct-Horse-Battery-9"
DEMO_ROLES = {"admin@aptiguard.demo": "admin", "designer@aptiguard.demo": "designer", "reviewer@aptiguard.demo": "reviewer",
              "reviewer2@aptiguard.demo": "reviewer", "analyst@aptiguard.demo": "analyst", "candidate1@aptiguard.demo": "candidate",
              "candidate2@aptiguard.demo": "candidate", "candidate3@aptiguard.demo": "candidate"}


@pytest.fixture(autouse=True)
def _clean_limiter(db):
    login_limiter.reset(db)
    db.commit()


@pytest.fixture()
def browser(seeded):
    from app.main import app

    return TestClient(app)


@pytest.fixture()
def reg(monkeypatch):
    monkeypatch.setattr(get_settings(), "registration_org_slug", DEMO_ORG_SLUG)


@pytest.fixture()
def dev_reset_log(monkeypatch, caplog):
    monkeypatch.setattr(get_settings(), "password_reset_delivery", "log")
    caplog.set_level(logging.WARNING, logger="aptiguard.auth")
    return caplog


def _register(client, email, name="Test Person", password=GOOD_PW, **extra):
    return client.post(f"{V1}/auth/register", json={"name": name, "email": email, "password": password, **extra})


def _hdr(token):
    return {"Authorization": f"Bearer {token}"}


def _demo_hashes(db):
    return dict(db.execute(select(User.email, User.password_hash).where(User.email.like("%@aptiguard.demo"))).all())


def _reset_token(caplog):
    m = re.findall(r"reset-password\?token=([A-Za-z0-9_-]+)", caplog.text)
    assert m, "no development reset link was logged"
    return m[-1]


# ------------------------------------------------------------------ registration
def test_registration_is_disabled_unless_an_organisation_is_configured(browser, db):
    n = db.scalar(select(func.count()).select_from(User))
    r = _register(browser, "nobody-yet@example.com")
    assert r.status_code == 403 and r.json()["error"]["code"] == "registration_disabled"
    assert db.scalar(select(func.count()).select_from(User)) == n
    p = browser.get(f"{V1}/auth/providers").json()
    assert p["registration"] is False and p["password"] is True


def test_registration_creates_a_candidate_only_and_signs_in(browser, db, reg):
    email = "Alice.Applicant@Example.com"
    r = _register(browser, f"  {email}  ", name="Alice  Applicant")
    assert r.status_code == 201, r.text
    body = r.json()
    u = body["user"]
    assert u["role"] == "candidate" and u["permissions"] == ["assessment.take"] and u["email"] == email.lower()
    assert u["name"] == "Alice Applicant" and u["candidate_code"].startswith("CAND-") and body["user"]["auth_methods"] == {"google": False}
    row = db.scalar(select(User).where(User.email == email.lower()))
    assert row.password_hash.startswith("$2") and GOOD_PW not in row.password_hash and row.is_active
    assert row.org.slug == DEMO_ORG_SLUG
    cand = db.scalar(select(Candidate).where(Candidate.user_id == row.id))
    assert cand and cand.org_id == row.org_id and cand.is_synthetic is False
    assert browser.get(f"{V1}/auth/me", headers=_hdr(body["access_token"])).json()["email"] == email.lower()
    ev = db.scalars(select(AuditEvent).where(AuditEvent.action == "auth.registered").order_by(AuditEvent.id.desc())).first()
    assert ev.org_id == row.org_id and GOOD_PW not in str(ev.details) + ev.summary and email.lower() not in ev.summary


def test_registered_user_can_log_in_and_wrong_credentials_are_generic(browser, db, reg):
    assert _register(browser, "bob.login@example.com").status_code == 201
    ok = browser.post(f"{V1}/auth/login", json={"email": "bob.login@example.com", "password": GOOD_PW})
    assert ok.status_code == 200 and ok.json()["user"]["role"] == "candidate"
    wrong = browser.post(f"{V1}/auth/login", json={"email": "bob.login@example.com", "password": "Wrong-Password-1234"})
    unknown = browser.post(f"{V1}/auth/login", json={"email": "ghost.user@example.com", "password": "Wrong-Password-1234"})
    assert wrong.status_code == unknown.status_code == 401 and wrong.json() == unknown.json()


def test_duplicate_registration_is_rejected_case_insensitively(browser, db, reg):
    assert _register(browser, "dup.person@example.com").status_code == 201
    r = _register(browser, "DUP.Person@EXAMPLE.com", password="Another-Good-Passw0rd")
    assert r.status_code == 409 and r.json()["error"]["code"] == "email_taken"
    assert db.scalar(select(func.count()).select_from(User).where(User.email == "dup.person@example.com")) == 1
    first = browser.post(f"{V1}/auth/login", json={"email": "dup.person@example.com", "password": GOOD_PW})
    assert first.status_code == 200  # the original password still works: the duplicate did not overwrite anything


def test_concurrent_registrations_of_one_email_create_exactly_one_account(db, reg, seeded):
    from app.main import app

    def go(_):
        return _register(TestClient(app), "race.condition@example.com").status_code

    with ThreadPoolExecutor(4) as ex:
        codes = sorted(ex.map(go, range(4)))
    assert codes.count(201) == 1 and set(codes) <= {201, 409}, codes
    db.expire_all()
    u = db.scalar(select(User).where(User.email == "race.condition@example.com"))
    assert db.scalar(select(func.count()).select_from(User).where(User.email == "race.condition@example.com")) == 1
    assert db.scalar(select(func.count()).select_from(Candidate).where(Candidate.user_id == u.id)) == 1


@pytest.mark.parametrize("payload", [
    {"name": "A", "email": "not-an-email", "password": GOOD_PW},
    {"name": "A", "email": "a@b", "password": GOOD_PW},
    {"name": "A", "email": "a..b@example.com", "password": GOOD_PW},
    {"name": "   ", "email": "blank.name@example.com", "password": GOOD_PW},
    {"name": "x" * 81, "email": "long.name@example.com", "password": GOOD_PW},
    {"name": "A", "email": "weak1@example.com", "password": "short"},
    {"name": "A", "email": "weak2@example.com", "password": "aaaaaaaaaaaaaaaa"},
    {"name": "A", "email": "weak3@example.com", "password": "weak3-and-then-some-1"},     # contains the e-mail name
    {"name": "A", "email": "toolong@example.com", "password": "Aa1!" * 30},                # > 72 bytes (bcrypt would truncate)
    {"name": "A", "email": "common@example.com", "password": "passwordpassword"},
    {"email": "missing.name@example.com", "password": GOOD_PW},
])
def test_invalid_registration_inputs_are_rejected_without_creating_users(browser, db, reg, payload):
    n = db.scalar(select(func.count()).select_from(User))
    r = browser.post(f"{V1}/auth/register", json=payload)
    assert r.status_code == 422, r.text
    assert db.scalar(select(func.count()).select_from(User)) == n


def test_clients_cannot_choose_role_organisation_or_permissions(browser, db, reg):
    for extra in ({"role": "admin"}, {"role_id": 1}, {"org_id": 999}, {"organization": "other"}, {"permissions": ["settings.manage"]},
                  {"is_active": True}, {"candidate_code": "DEMO-CAND-01"}):
        r = _register(browser, "escalate@example.com", **extra)
        assert r.status_code == 422, (extra, r.text)
    assert db.scalar(select(User).where(User.email == "escalate@example.com")) is None
    ok = _register(browser, "escalate@example.com")
    assert ok.status_code == 201 and ok.json()["user"]["role"] == "candidate"


def test_demo_addresses_cannot_be_registered_and_demo_accounts_are_untouched(browser, db, reg):
    before = _demo_hashes(db)
    n = db.scalar(select(func.count()).select_from(User))
    for email in ("admin@aptiguard.demo", "ADMIN@aptiguard.demo", "brand.new@aptiguard.demo", "x@sub.aptiguard.demo"):
        r = _register(browser, email, password="Totally-Different-Passw0rd")
        assert r.status_code == 422 and r.json()["error"]["code"] == "email_reserved", (email, r.text)
    db.expire_all()
    assert _demo_hashes(db) == before and db.scalar(select(func.count()).select_from(User)) == n
    assert browser.post(f"{V1}/auth/login", json={"email": "admin@aptiguard.demo", "password": DEMO_PW}).status_code == 200


def test_registration_is_rate_limited(browser, db, reg):
    codes = [browser.post(f"{V1}/auth/register", json={"name": "A", "email": f"bad{i}", "password": GOOD_PW}).status_code for i in range(11)]
    assert codes[:10] == [422] * 10 and codes[10] == 429


def test_inactive_account_cannot_log_in_and_logout_revokes_sessions(browser, db, reg):
    r = _register(browser, "inactive.me@example.com")
    tok = r.json()["access_token"]
    u = db.scalar(select(User).where(User.email == "inactive.me@example.com"))
    u.is_active = False
    db.commit()
    assert browser.get(f"{V1}/auth/me", headers=_hdr(tok)).status_code == 401
    assert browser.post(f"{V1}/auth/login", json={"email": "inactive.me@example.com", "password": GOOD_PW}).status_code == 401
    u.is_active = True
    db.commit()
    t1 = browser.post(f"{V1}/auth/login", json={"email": "inactive.me@example.com", "password": GOOD_PW}).json()["access_token"]
    t2 = browser.post(f"{V1}/auth/login", json={"email": "inactive.me@example.com", "password": GOOD_PW}).json()["access_token"]
    assert browser.post(f"{V1}/auth/logout", headers=_hdr(t1)).status_code == 200
    assert browser.get(f"{V1}/auth/me", headers=_hdr(t1)).status_code == 401 and browser.get(f"{V1}/auth/me", headers=_hdr(t2)).status_code == 401


# ------------------------------------------------------------------ authorisation of self-registered users
def test_self_registered_candidate_has_no_staff_access_and_no_access_to_other_candidates(browser, db, reg):
    tok = _register(browser, "plain.candidate@example.com").json()["access_token"]
    h = _hdr(tok)
    for path in ("/dashboard/summary", "/questions", "/reports/templates", "/settings", "/audit", "/leaks/alerts", "/assembly/runs",
                 "/calibration/runs", "/exposure/items", "/review/queue", "/integrity/flagged-attempts", "/notifications/../audit"):
        assert browser.get(f"{V1}{path}", headers=h).status_code in (403, 404), path
    assert browser.post(f"{V1}/auth/users/1/revoke-sessions", headers=h).status_code == 403
    assert browser.post(f"{V1}/system/demo/reset", headers=h).status_code == 403
    other = db.scalar(select(func.min(User.id)).where(User.email == "candidate1@aptiguard.demo"))
    assert other
    from app.models import Attempt, CandidateAssignment

    att = db.scalar(select(Attempt.id).limit(1))
    assert browser.get(f"{V1}/assessment/attempts/{att}", headers=h).status_code == 404
    form = db.scalar(select(CandidateAssignment.form_id).limit(1))
    assert browser.get(f"{V1}/assessment/forms/{form}", headers=h).status_code == 404
    assert browser.get(f"{V1}/assessment/available", headers=h).json()["forms"] == []


def test_registration_lands_only_in_the_configured_organisation(browser, db, monkeypatch):
    org = Organization(name="Registration Tenant", slug="registration-tenant")
    db.add(org)
    db.commit()
    monkeypatch.setattr(get_settings(), "registration_org_slug", "registration-tenant")
    r = _register(browser, "tenant.joiner@example.com")
    assert r.status_code == 201 and r.json()["user"]["organization"]["id"] == org.id
    monkeypatch.setattr(get_settings(), "registration_org_slug", "no-such-org")
    assert _register(browser, "tenant.joiner2@example.com").status_code == 403


# ------------------------------------------------------------------ password reset
def test_forgot_password_is_uniform_and_never_returns_the_token(browser, db, reg, dev_reset_log):
    assert _register(browser, "reset.me@example.com").status_code == 201
    u = db.scalar(select(User).where(User.email == "reset.me@example.com"))
    off = db.scalar(select(User).where(User.email == "candidate2@aptiguard.demo"))
    db.add(User(org_id=u.org_id, email="off.account@example.com", full_name="Off", password_hash=u.password_hash, role_id=u.role_id, is_active=False))
    db.commit()
    replies = [browser.post(f"{V1}/auth/password/forgot", json={"email": e}) for e in
               ("reset.me@example.com", "nobody.here@example.com", "off.account@example.com", "candidate2@aptiguard.demo", "garbage")]
    assert {r.status_code for r in replies} == {202} and len({r.text for r in replies}) == 1
    assert "token" not in replies[0].text.lower()
    mine = db.scalars(select(AuthToken).where(AuthToken.kind == "password_reset", AuthToken.user_id == u.id)).all()
    assert len(mine) == 1 and len(mine[0].token_hash) == 64
    for other in (off.id, db.scalar(select(User.id).where(User.email == "off.account@example.com"))):  # demo and inactive: no token
        assert db.scalar(select(func.count()).select_from(AuthToken).where(AuthToken.user_id == other)) == 0
    toks = mine
    raw = _reset_token(dev_reset_log)
    assert raw not in "".join(t.token_hash for t in toks)  # stored hashed, never raw


def test_forgot_password_without_delivery_sends_nothing(browser, db, reg, caplog):
    caplog.set_level(logging.WARNING, logger="aptiguard.auth")
    assert get_settings().password_reset_delivery == "none"
    assert _register(browser, "silent.reset@example.com").status_code == 201
    assert browser.post(f"{V1}/auth/password/forgot", json={"email": "silent.reset@example.com"}).status_code == 202
    assert "reset-password" not in caplog.text


def test_password_reset_changes_password_revokes_sessions_and_is_single_use(browser, db, reg, dev_reset_log):
    old = _register(browser, "full.reset@example.com").json()["access_token"]
    browser.post(f"{V1}/auth/password/forgot", json={"email": "full.reset@example.com"})
    raw = _reset_token(dev_reset_log)
    new_pw = "Brand-New-Passw0rd-77"
    r = browser.post(f"{V1}/auth/password/reset", json={"token": raw, "password": new_pw})
    assert r.status_code == 200 and r.json() == {"status": "password_updated"}
    assert browser.get(f"{V1}/auth/me", headers=_hdr(old)).status_code == 401  # all earlier sessions revoked
    assert browser.post(f"{V1}/auth/login", json={"email": "full.reset@example.com", "password": GOOD_PW}).status_code == 401
    assert browser.post(f"{V1}/auth/login", json={"email": "full.reset@example.com", "password": new_pw}).status_code == 200
    again = browser.post(f"{V1}/auth/password/reset", json={"token": raw, "password": "Yet-Another-Passw0rd-1"})
    assert again.status_code == 400 and again.json()["error"]["code"] == "invalid_token"  # single use
    ev = db.scalars(select(AuditEvent).where(AuditEvent.action == "auth.password_reset").order_by(AuditEvent.id.desc())).first()
    assert ev and new_pw not in str(ev.details) + ev.summary and raw not in str(ev.details) + ev.summary


def test_expired_unknown_and_superseded_reset_tokens_are_rejected_and_weak_password_keeps_the_token(browser, db, reg, dev_reset_log):
    _register(browser, "expiry.test@example.com")
    browser.post(f"{V1}/auth/password/forgot", json={"email": "expiry.test@example.com"})
    first = _reset_token(dev_reset_log)
    dev_reset_log.clear()
    login_limiter.reset(db)
    db.commit()
    browser.post(f"{V1}/auth/password/forgot", json={"email": "expiry.test@example.com"})
    second = _reset_token(dev_reset_log)
    assert first != second
    bad = {"password": "Fresh-Passw0rd-1234"}
    assert browser.post(f"{V1}/auth/password/reset", json={"token": first, **bad}).status_code == 400  # superseded by the newer link
    assert browser.post(f"{V1}/auth/password/reset", json={"token": "x" * 43, **bad}).status_code == 400
    weak = browser.post(f"{V1}/auth/password/reset", json={"token": second, "password": "short"})
    assert weak.status_code == 422  # a weak password does not burn the link
    from app.services.accounts import hash_token

    row = db.scalar(select(AuthToken).where(AuthToken.token_hash == hash_token(second)))
    row.expires_at = utcnow() - timedelta(seconds=1)
    db.commit()
    assert browser.post(f"{V1}/auth/password/reset", json={"token": second, **bad}).status_code == 400  # expired


def test_reset_link_cannot_be_used_twice_concurrently(browser, db, reg, dev_reset_log):
    from app.main import app

    _register(browser, "double.use@example.com")
    browser.post(f"{V1}/auth/password/forgot", json={"email": "double.use@example.com"})
    raw = _reset_token(dev_reset_log)

    def go(i):
        return TestClient(app).post(f"{V1}/auth/password/reset", json={"token": raw, "password": f"Concurrent-Passw0rd-{i}x"}).status_code

    with ThreadPoolExecutor(3) as ex:
        codes = sorted(ex.map(go, range(3)))
    assert codes.count(200) == 1 and set(codes) <= {200, 400}, codes


def test_per_address_and_per_client_reset_limits(browser, db, reg, dev_reset_log):
    _register(browser, "limit.reset@example.com")
    for _ in range(5):
        assert browser.post(f"{V1}/auth/password/forgot", json={"email": "limit.reset@example.com"}).status_code == 202
    uid = db.scalar(select(User.id).where(User.email == "limit.reset@example.com"))
    assert db.scalar(select(func.count()).select_from(AuthToken).where(AuthToken.kind == "password_reset", AuthToken.user_id == uid)) == 3  # cap is silent
    login_limiter.reset(db)
    db.commit()
    codes = [browser.post(f"{V1}/auth/password/reset", json={"token": "t" * 20, "password": GOOD_PW}).status_code for _ in range(11)]
    assert codes[:10] == [400] * 10 and codes[10] == 429


def test_demo_accounts_cannot_be_reset_even_with_a_forged_token_row(browser, db, reg):
    """Demo credentials are shared and public: a reset must be impossible for them, whatever is in the token table."""
    from app.services.accounts import issue_token

    demo = db.scalar(select(User).where(User.email == "candidate3@aptiguard.demo"))
    before = demo.password_hash
    raw = issue_token(db, "password_reset", 600, user_id=demo.id)
    db.commit()
    r = browser.post(f"{V1}/auth/password/reset", json={"token": raw, "password": "Hijacked-Passw0rd-1"})
    assert r.status_code == 400
    db.expire_all()
    assert db.get(User, demo.id).password_hash == before
    assert browser.post(f"{V1}/auth/login", json={"email": "candidate3@aptiguard.demo", "password": DEMO_PW}).status_code == 200


# ------------------------------------------------------------------ demo login regression
def test_all_demo_accounts_still_log_in_with_unchanged_roles_and_organisation(browser, db):
    org = db.scalar(select(Organization).where(Organization.slug == DEMO_ORG_SLUG))
    for email, role in DEMO_ROLES.items():
        r = browser.post(f"{V1}/auth/login", json={"email": email, "password": DEMO_PW})
        assert r.status_code == 200, (email, r.text)
        u = r.json()["user"]
        assert u["role"] == role and u["organization"]["id"] == org.id and u["email"] == email
        if role == "candidate":
            assert u["candidate_code"].startswith("DEMO-CAND-")
        assert browser.get(f"{V1}/auth/me", headers=_hdr(r.json()["access_token"])).status_code == 200
    assert len(DEMO_ROLES) == db.scalar(select(func.count()).select_from(User).where(User.email.like("%@aptiguard.demo")))


def test_demo_login_is_independent_of_google_and_registration_settings(browser, monkeypatch):
    s = get_settings()
    for gid, slug in (("", ""), ("some-client-id", ""), ("", DEMO_ORG_SLUG), ("some-client-id", DEMO_ORG_SLUG)):
        monkeypatch.setattr(s, "google_client_id", gid)
        monkeypatch.setattr(s, "google_client_secret", "x" if gid else "")
        monkeypatch.setattr(s, "registration_org_slug", slug)
        assert browser.post(f"{V1}/auth/login", json={"email": "analyst@aptiguard.demo", "password": DEMO_PW}).status_code == 200
    ds = browser.get(f"{V1}/demo-status").json()
    assert ds["demo_mode"] is True and ds["demo_password"] == DEMO_PW
    assert {a["email"] for a in ds["demo_accounts"]} == {"admin@aptiguard.demo", "designer@aptiguard.demo", "reviewer@aptiguard.demo",
                                                         "analyst@aptiguard.demo", "candidate1@aptiguard.demo"}


def test_demo_password_hashes_are_never_modified_by_any_new_flow(browser, db, reg, dev_reset_log):
    before = _demo_hashes(db)
    _register(browser, "admin@aptiguard.demo")
    browser.post(f"{V1}/auth/password/forgot", json={"email": "admin@aptiguard.demo"})
    browser.post(f"{V1}/auth/password/reset", json={"token": "n" * 30, "password": "Hijacked-Passw0rd-1"})
    db.expire_all()
    assert _demo_hashes(db) == before


def test_production_never_offers_demo_accounts(monkeypatch, browser):
    s = get_settings()
    monkeypatch.setattr(s, "app_env", "production")
    assert "demo_accounts" not in browser.get(f"{V1}/demo-status").json()
    assert browser.get(f"{V1}/auth/providers").json()["demo_mode"] is False


def test_production_rejects_dev_only_reset_delivery_and_insecure_google_urls(monkeypatch):
    from app.core.config import ConfigurationError, Settings

    base = dict(app_env="production", demo_mode=False, jwt_secret="x" * 40, cors_origins="https://app.example.com")
    with pytest.raises(ValueError, match="development-only"):
        Settings(**base, password_reset_delivery="log")
    with pytest.raises(ValueError, match="https"):
        Settings(**base, google_client_id="id", google_client_secret="s")
    ok = Settings(**base, google_client_id="id", google_client_secret="s", google_redirect_uri="https://api.example.com/api/v1/auth/google/callback",
                  frontend_url="https://app.example.com")
    assert ok.google_configured
    assert ConfigurationError  # imported to document that the cached accessor wraps these messages


def test_completing_a_reset_does_not_clear_anyone_elses_lockouts_or_rate_limits(browser, db, reg, dev_reset_log):
    """Regression: the reset handler used to wipe the whole auth_failures table (every account's brute-force counters)."""
    from app.core.ratelimit import key_for
    from app.models import AuthFailure

    _register(browser, "keeps.limits@example.com")
    browser.post(f"{V1}/auth/password/forgot", json={"email": "keeps.limits@example.com"})
    raw = _reset_token(dev_reset_log)
    victim_key = key_for("203.0.113.9", "someone.else@example.com")  # another client/account, mid lock-out
    for _ in range(8):
        db.add(AuthFailure(key_hash=victim_key))
    db.commit()
    assert browser.post(f"{V1}/auth/password/reset", json={"token": raw, "password": "Keep-The-Limits-Passw0rd"}).status_code == 200
    assert db.scalar(select(func.count()).select_from(AuthFailure).where(AuthFailure.key_hash == victim_key)) == 8
    assert login_limiter.retry_after(db, victim_key, 8, 300) > 0  # still locked out
