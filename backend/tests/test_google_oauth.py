"""Google sign-in with a fully mocked provider: a locally generated RSA key signs the ID tokens and Google's token endpoint
and key set are replaced. No network, no real credentials."""
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qs, urlparse

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.ratelimit import login_limiter
from app.demo.seed import DEMO_ORG_SLUG
from app.models import AuthToken, Candidate, ExternalIdentity, Organization, Role, User
from app.services import google_oauth

V1 = "/api/v1"
CLIENT_ID = "test-client-id.apps.googleusercontent.com"
FRONT = "http://localhost:5173"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
DEMO_PW = get_settings().demo_password
PW = "Correct-Horse-Battery-9"


class FakeGoogle:
    """Stands in for Google: signs ID tokens, answers the token endpoint, records what the backend sent."""

    def __init__(self):
        self.nonce = ""
        self.sub, self.email, self.name = "g-sub-1", "new.person@example.com", "New Person"
        self.overrides: dict = {}
        self.signing_key = KEY
        self.alg = "RS256"
        self.status = 200
        self.network_error = False
        self.jwks_error = False
        self.sent: list[dict] = []
        self.nonce_by_code: dict[str, str] = {}  # lets concurrent flows each get an ID token with their own nonce

    def claims(self, code=None):
        now = int(time.time())
        c = {"iss": "https://accounts.google.com", "aud": CLIENT_ID, "sub": self.sub, "email": self.email, "email_verified": True,
             "name": self.name, "nonce": self.nonce_by_code.get(code, self.nonce), "iat": now, "exp": now + 3600}
        c.update(self.overrides)
        return {k: v for k, v in c.items() if v is not None}

    def post(self, url, data=None, timeout=None, **_):
        self.sent.append({"url": url, **(data or {})})
        if self.network_error:
            raise httpx.ConnectError("simulated outage")
        if self.status != 200:
            return httpx.Response(self.status, json={"error": "invalid_grant"})
        return httpx.Response(200, json={"id_token": jwt.encode(self.claims((data or {}).get("code")), self.signing_key, algorithm=self.alg), "access_token": "ignored"})


@pytest.fixture(autouse=True)
def _clean_limiter(db):
    login_limiter.reset(db)
    db.commit()


@pytest.fixture()
def fake(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "google_client_id", CLIENT_ID)
    monkeypatch.setattr(s, "google_client_secret", "unit-test-secret")
    monkeypatch.setattr(s, "google_redirect_uri", "http://localhost:8000/api/v1/auth/google/callback")
    monkeypatch.setattr(s, "frontend_url", FRONT)
    monkeypatch.setattr(s, "registration_org_slug", DEMO_ORG_SLUG)
    f = FakeGoogle()

    def key(_token):
        if f.jwks_error:
            raise RuntimeError("jwks unavailable")
        return KEY.public_key()

    monkeypatch.setattr(google_oauth, "_signing_key", key)
    monkeypatch.setattr(google_oauth.httpx, "post", f.post)
    return f


@pytest.fixture()
def browser(seeded):
    from app.main import app

    return TestClient(app)


def _start(client, fake):
    r = client.get(f"{V1}/auth/google/start", follow_redirects=False)
    assert r.status_code == 302, r.text
    q = {k: v[0] for k, v in parse_qs(urlparse(r.headers["location"]).query).items()}
    fake.nonce = q.get("nonce", "")
    return r, q


def _callback(client, state, code="auth-code", **params):
    return client.get(f"{V1}/auth/google/callback", params={"code": code, "state": state, **params}, follow_redirects=False)


def _flow(client, fake, **kw):
    r, q = _start(client, fake)
    return q, _callback(client, q["state"], **kw)


def _outcome(resp):
    """('ticket', value) | ('error', code) | ('status', value) from the redirect back to the frontend."""
    loc = resp.headers["location"]
    assert loc.startswith(FRONT + "/auth/callback?"), loc
    q = parse_qs(urlparse(loc).query)
    for k in ("ticket", "error", "status"):
        if k in q:
            return k, q[k][0]
    raise AssertionError(loc)


def _exchange(client, ticket):
    return client.post(f"{V1}/auth/google/exchange", json={"ticket": ticket})


def _count_users(db):
    db.expire_all()
    return db.scalar(select(func.count()).select_from(User)), db.scalar(select(func.count()).select_from(ExternalIdentity))


def _login_pw(client, email, pw=PW):
    return client.post(f"{V1}/auth/login", json={"email": email, "password": pw})


def _make_local(db, email, role="candidate", password=PW):
    from app.core.security import hash_password

    org = db.scalar(select(Organization).where(Organization.slug == DEMO_ORG_SLUG))
    u = User(org_id=org.id, email=email, full_name="Local Person", password_hash=hash_password(password),
             role_id=db.scalar(select(Role.id).where(Role.name == role)))
    db.add(u)
    db.commit()
    return u


# ------------------------------------------------------------------ the happy path
def test_authorization_request_is_correct_and_binds_the_browser(browser, fake):
    r, q = _start(browser, fake)
    u = urlparse(r.headers["location"])
    assert u.scheme == "https" and u.netloc == "accounts.google.com" and u.path == "/o/oauth2/v2/auth"
    assert q["client_id"] == CLIENT_ID and q["response_type"] == "code" and q["scope"] == "openid email profile"  # minimal scopes
    assert q["redirect_uri"] == "http://localhost:8000/api/v1/auth/google/callback"
    assert q["code_challenge_method"] == "S256" and len(q["code_challenge"]) >= 43 and len(q["state"]) >= 32 and len(q["nonce"]) >= 32
    assert "unit-test-secret" not in r.headers["location"]
    cookie = r.headers["set-cookie"].lower()
    assert "ag_oauth_bind=" in cookie and "httponly" in cookie and "samesite=lax" in cookie and "path=/api/v1/auth/google" in cookie


def test_new_google_user_is_registered_as_a_candidate_and_signed_in(browser, fake, db):
    users, idents = _count_users(db)
    q, cb = _flow(browser, fake)
    kind, ticket = _outcome(cb)
    assert kind == "ticket" and "id_token" not in cb.headers["location"] and "access_token" not in cb.headers["location"]
    sent = fake.sent[-1]
    assert sent["code"] == "auth-code" and sent["code_verifier"] and sent["client_secret"] == "unit-test-secret"  # exchanged server side
    r = _exchange(browser, ticket)
    assert r.status_code == 200, r.text
    u = r.json()["user"]
    assert u["role"] == "candidate" and u["permissions"] == ["assessment.take"] and u["email"] == "new.person@example.com"
    assert u["auth_methods"]["google"] is True and u["candidate_code"].startswith("CAND-") and u["organization"]["name"].startswith("Integraminds")
    assert _count_users(db) == (users + 1, idents + 1)
    ident = db.scalar(select(ExternalIdentity).where(ExternalIdentity.subject == "g-sub-1"))
    assert ident.provider == "google" and db.scalar(select(Candidate).where(Candidate.user_id == ident.user_id))
    assert browser.get(f"{V1}/auth/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"}).status_code == 200
    # an account made through Google has no usable password
    assert _login_pw(browser, "new.person@example.com").status_code == 401
    assert _login_pw(browser, "new.person@example.com", "anything-at-all-123").status_code == 401


def test_returning_google_user_signs_in_without_creating_anything(browser, fake, db):
    fake.sub, fake.email = "g-sub-returning", "returning@example.com"
    _, cb = _flow(browser, fake)
    first = _exchange(browser, _outcome(cb)[1]).json()["user"]["id"]
    users = _count_users(db)
    fake.email = "changed.address@example.com"  # identity is the stable `sub`, not the e-mail
    _, cb2 = _flow(TestClient(browser.app), fake)
    second = _exchange(browser, _outcome(cb2)[1]).json()["user"]
    assert second["id"] == first and second["email"] == "returning@example.com" and _count_users(db) == users


def test_login_ticket_is_single_use_short_lived_and_not_a_session_token(browser, fake, db):
    _, cb = _flow(browser, fake)
    _, ticket = _outcome(cb)
    assert browser.get(f"{V1}/auth/me", headers={"Authorization": f"Bearer {ticket}"}).status_code == 401
    assert _exchange(browser, ticket).status_code == 200
    again = _exchange(browser, ticket)
    assert again.status_code == 401 and again.json()["error"]["code"] == "invalid_ticket"
    fake.sub, fake.email = "g-sub-expiring", "expiring@example.com"
    _, cb2 = _flow(browser, fake)
    from app.services.accounts import hash_token
    from app.db.base import utcnow
    from datetime import timedelta

    row = db.scalar(select(AuthToken).where(AuthToken.token_hash == hash_token(_outcome(cb2)[1])))
    row.expires_at = utcnow() - timedelta(seconds=1)
    db.commit()
    assert _exchange(browser, _outcome(cb2)[1]).status_code == 401
    assert _exchange(browser, "z" * 43).status_code == 401


def test_google_created_users_are_always_plain_candidates(browser, fake, db):
    fake.sub, fake.email = "g-sub-escalate", "escalate.google@example.com"
    fake.overrides = {"role": "admin", "roles": ["admin"], "hd": "aptiguard.demo", "org_id": 1, "is_admin": True}
    _, cb = _flow(browser, fake)
    u = _exchange(browser, _outcome(cb)[1]).json()["user"]
    assert u["role"] == "candidate" and u["permissions"] == ["assessment.take"]


# ------------------------------------------------------------------ state / CSRF
def test_state_is_validated_single_use_and_bound_to_the_browser(browser, fake, db):
    fake.sub, fake.email = "g-sub-state-test", "state.test@example.com"
    users = _count_users(db)
    r, q = _start(browser, fake)
    assert _outcome(_callback(browser, "not-the-state"))[1] == "google_state"
    ok = _callback(browser, q["state"])
    assert _outcome(ok)[0] == "ticket"
    replay = _callback(browser, q["state"])  # the same callback again
    assert _outcome(replay) == ("error", "google_state")
    # login CSRF: an attacker's flow completed in a victim's browser (no / other cookie)
    attacker = TestClient(browser.app)
    _, qa = _start(attacker, fake)
    victim = TestClient(browser.app)
    assert _outcome(_callback(victim, qa["state"])) == ("error", "google_state")
    other = TestClient(browser.app)
    _start(other, fake)  # has *a* cookie, but for a different state
    assert _outcome(_callback(other, qa["state"])) == ("error", "google_state")
    assert _count_users(db)[0] == users[0] + 1  # only the one legitimate sign-up


def test_expired_state_is_rejected(browser, fake, db):
    r, q = _start(browser, fake)
    from datetime import timedelta
    from app.db.base import utcnow
    from app.services.accounts import hash_token

    row = db.scalar(select(AuthToken).where(AuthToken.token_hash == hash_token(q["state"])))
    row.expires_at = utcnow() - timedelta(seconds=1)
    db.commit()
    assert _outcome(_callback(browser, q["state"])) == ("error", "google_state")


def test_denied_consent_and_missing_parameters_are_handled_and_burn_the_state(browser, fake, db):
    r, q = _start(browser, fake)
    denied = browser.get(f"{V1}/auth/google/callback", params={"error": "access_denied", "state": q["state"]}, follow_redirects=False)
    assert _outcome(denied) == ("error", "google_denied")
    assert _outcome(_callback(browser, q["state"])) == ("error", "google_state")  # state was consumed by the denial
    assert _outcome(browser.get(f"{V1}/auth/google/callback", follow_redirects=False)) == ("error", "google_failed")
    assert _outcome(browser.get(f"{V1}/auth/google/callback", params={"code": "c"}, follow_redirects=False)) == ("error", "google_failed")
    assert _outcome(browser.get(f"{V1}/auth/google/callback", params={"error": "x"}, follow_redirects=False)) == ("error", "google_denied")


# ------------------------------------------------------------------ ID-token validation
def _bad_token_cases():
    now = int(time.time())
    return [
        ("expired", {"exp": now - 600, "iat": now - 4000}, {}),
        ("wrong audience", {"aud": "someone-elses-client"}, {}),
        ("wrong issuer", {"iss": "https://evil.example.com"}, {}),
        ("no issuer", {"iss": None}, {}),
        ("no expiry", {"exp": None}, {}),
        ("no subject", {"sub": None}, {}),
        ("wrong nonce", {"nonce": "replayed-from-another-flow"}, {}),
        ("no nonce", {"nonce": None}, {}),
        ("signed by another key", {}, {"signing_key": OTHER_KEY}),
        ("empty subject", {"sub": ""}, {}),
        ("no email", {"email": None}, {}),
    ]


@pytest.mark.parametrize("name,overrides,attrs", _bad_token_cases(), ids=[c[0] for c in _bad_token_cases()])
def test_invalid_id_tokens_are_rejected_without_creating_anything(browser, fake, db, name, overrides, attrs):
    users = _count_users(db)
    fake.sub, fake.email = f"g-bad-{abs(hash(name))}", f"bad.{abs(hash(name))}@example.com"
    fake.overrides = overrides
    for k, v in attrs.items():
        setattr(fake, k, v)
    r, q = _start(browser, fake)
    fake.overrides = {**overrides, **({"nonce": overrides["nonce"]} if "nonce" in overrides else {})}
    cb = _callback(browser, q["state"])
    assert _outcome(cb) == ("error", "google_failed"), name
    assert _count_users(db) == users


def test_unsigned_or_symmetric_tokens_are_refused(browser, fake, db, monkeypatch):
    users = _count_users(db)
    r, q = _start(browser, fake)
    for forged in (jwt.encode(fake.claims(), key=None, algorithm="none"),
                   jwt.encode(fake.claims(), "unit-test-secret" * 4, algorithm="HS256")):
        monkeypatch.setattr(google_oauth, "exchange_code", lambda code, verifier, t=forged: t)
        # new state each time: the previous one is consumed
        r, q = _start(browser, fake)
        assert _outcome(_callback(browser, q["state"])) == ("error", "google_failed")
    assert _count_users(db) == users


def test_unverified_email_is_refused(browser, fake, db):
    users = _count_users(db)
    fake.overrides = {"email_verified": False}
    _, cb = _flow(browser, fake)
    assert _outcome(cb) == ("error", "google_email_unverified")
    fake.overrides = {"email_verified": None}
    _, cb = _flow(browser, fake)
    assert _outcome(cb) == ("error", "google_email_unverified")
    fake.overrides = {"email_verified": "true"}  # Google sometimes serialises the boolean as a string
    fake.sub, fake.email = "g-sub-strbool", "strbool@example.com"
    _, cb = _flow(browser, fake)
    assert _outcome(cb)[0] == "ticket"
    assert _count_users(db)[0] == users[0] + 1


def test_provider_and_network_failures_are_reported_safely(browser, fake, db):
    users = _count_users(db)
    fake.status = 500
    assert _outcome(_flow(browser, fake)[1]) == ("error", "google_failed")
    fake.status, fake.network_error = 200, True
    assert _outcome(_flow(browser, fake)[1]) == ("error", "google_failed")
    fake.network_error, fake.jwks_error = False, True
    assert _outcome(_flow(browser, fake)[1]) == ("error", "google_failed")
    fake.jwks_error = False
    assert _count_users(db) == users


def test_google_not_configured_degrades_gracefully_and_demo_login_still_works(browser, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "google_client_id", "")
    monkeypatch.setattr(s, "google_client_secret", "")
    assert browser.get(f"{V1}/auth/providers").json()["google"] is False
    assert _outcome(browser.get(f"{V1}/auth/google/start", follow_redirects=False)) == ("error", "google_not_configured")
    assert _login_pw(browser, "candidate1@aptiguard.demo", DEMO_PW).status_code == 200


def test_redirects_only_ever_go_to_google_or_the_fixed_frontend_routes(browser, fake, db):
    r, q = _start(browser, fake)
    assert urlparse(r.headers["location"]).netloc == "accounts.google.com"
    cb = browser.get(f"{V1}/auth/google/callback", params={"code": "c", "state": q["state"], "next": "https://evil.example.com",
                                                          "redirect": "//evil.example.com", "redirect_uri": "https://evil.example.com"},
                     follow_redirects=False)
    loc = cb.headers["location"]
    assert loc.startswith(FRONT + "/auth/callback?") and "evil" not in loc
    for bad in ("denied", "state"):
        assert _callback(browser, "x" * 10).headers["location"].startswith(FRONT + "/auth/callback?error=")


# ------------------------------------------------------------------ account linking and takeover protection
def test_matching_email_never_merges_or_logs_into_an_existing_account(browser, fake, db):
    local = _make_local(db, "has.password@example.com")
    users = _count_users(db)
    fake.sub, fake.email = "g-sub-attacker", "has.password@example.com"
    for _ in range(2):
        _, cb = _flow(browser, fake)
        assert _outcome(cb) == ("error", "google_account_exists")
    assert _count_users(db) == users
    assert _login_pw(browser, "has.password@example.com").status_code == 200  # the local account is untouched
    assert db.scalar(select(ExternalIdentity).where(ExternalIdentity.user_id == local.id)) is None


@pytest.mark.parametrize("role", ["admin", "analyst", "designer", "reviewer"])
def test_staff_accounts_cannot_be_taken_over_by_a_matching_google_email(browser, fake, db, role):
    _make_local(db, f"{role}.staff@corp.example", role=role)
    users = _count_users(db)
    fake.sub, fake.email = f"g-sub-{role}", f"{role}.staff@corp.example"
    assert _outcome(_flow(browser, fake)[1]) == ("error", "google_account_exists")
    assert _count_users(db) == users


def test_demo_accounts_cannot_be_reached_or_linked_through_google(browser, fake, db):
    users = _count_users(db)
    for email in ("admin@aptiguard.demo", "candidate1@aptiguard.demo", "brand.new@aptiguard.demo"):
        fake.sub, fake.email = f"g-demo-{email}", email
        outcome = _outcome(_flow(browser, fake)[1])
        assert outcome[0] == "error" and outcome[1] in ("google_account_exists", "google_demo_blocked"), (email, outcome)
    assert _count_users(db) == users
    # signed-in demo users cannot start linking
    tok = _login_pw(browser, "candidate1@aptiguard.demo", DEMO_PW).json()["access_token"]
    r = browser.post(f"{V1}/auth/google/link/start", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "demo_blocked"
    # even a stray identity row on a demo user cannot be used to sign in
    demo = db.scalar(select(User).where(User.email == "candidate2@aptiguard.demo"))
    db.add(ExternalIdentity(user_id=demo.id, provider="google", subject="g-stray-demo", email="candidate2@aptiguard.demo"))
    db.commit()
    fake.sub, fake.email = "g-stray-demo", "candidate2@aptiguard.demo"
    assert _outcome(_flow(browser, fake)[1]) == ("error", "google_demo_blocked")
    db.delete(db.scalar(select(ExternalIdentity).where(ExternalIdentity.subject == "g-stray-demo")))
    db.commit()


def test_linking_requires_an_authenticated_session_and_a_matching_verified_email(browser, fake, db):
    _make_local(db, "link.me@example.com")
    assert browser.post(f"{V1}/auth/google/link/start").status_code == 401
    tok = _login_pw(browser, "link.me@example.com").json()["access_token"]
    r = browser.post(f"{V1}/auth/google/link/start", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200
    q = {k: v[0] for k, v in parse_qs(urlparse(r.json()["authorization_url"]).query).items()}
    assert "ag_oauth_bind=" in r.headers["set-cookie"] and "httponly" in r.headers["set-cookie"].lower()
    fake.nonce, fake.sub, fake.email = q["nonce"], "g-sub-link", "link.me@example.com"
    assert _outcome(_callback(browser, q["state"])) == ("status", "linked")
    ident = db.scalar(select(ExternalIdentity).where(ExternalIdentity.subject == "g-sub-link"))
    assert ident and db.get(User, ident.user_id).email == "link.me@example.com"
    assert browser.get(f"{V1}/auth/me", headers={"Authorization": f"Bearer {tok}"}).json()["auth_methods"]["google"] is True
    # the linked Google account now signs in as that same user
    _, cb = _flow(TestClient(browser.app), fake)
    assert _exchange(browser, _outcome(cb)[1]).json()["user"]["email"] == "link.me@example.com"


def _link_attempt(browser, fake, db, email, google_email, sub):
    _make_local(db, email) if not db.scalar(select(User).where(User.email == email)) else None
    tok = _login_pw(browser, email).json()["access_token"]
    r = browser.post(f"{V1}/auth/google/link/start", headers={"Authorization": f"Bearer {tok}"})
    q = {k: v[0] for k, v in parse_qs(urlparse(r.json()["authorization_url"]).query).items()}
    fake.nonce, fake.sub, fake.email = q["nonce"], sub, google_email
    return _outcome(_callback(browser, q["state"]))


def test_linking_conflicts_and_mismatches_are_refused(browser, fake, db):
    assert _link_attempt(browser, fake, db, "mismatch.me@example.com", "different.address@example.com", "g-sub-mm") == ("error", "google_link_mismatch")
    assert db.scalar(select(ExternalIdentity).where(ExternalIdentity.subject == "g-sub-mm")) is None
    assert _link_attempt(browser, fake, db, "first.owner@example.com", "first.owner@example.com", "g-sub-shared") == ("status", "linked")
    # the same Google account cannot be attached to a second local account (duplicate identity)
    assert _link_attempt(browser, fake, db, "second.owner@example.com", "second.owner@example.com", "g-sub-shared") == ("error", "google_link_conflict")
    # and one local account cannot hold two Google identities
    assert _link_attempt(browser, fake, db, "first.owner@example.com", "first.owner@example.com", "g-sub-other") == ("error", "google_link_conflict")
    assert db.scalar(select(func.count()).select_from(ExternalIdentity).where(ExternalIdentity.subject == "g-sub-shared")) == 1


def test_link_state_cannot_be_completed_in_another_browser_or_after_the_account_is_deactivated(browser, fake, db):
    _make_local(db, "inactive.link@example.com")
    tok = _login_pw(browser, "inactive.link@example.com").json()["access_token"]
    r = browser.post(f"{V1}/auth/google/link/start", headers={"Authorization": f"Bearer {tok}"})
    q = {k: v[0] for k, v in parse_qs(urlparse(r.json()["authorization_url"]).query).items()}
    fake.nonce, fake.sub, fake.email = q["nonce"], "g-sub-inactive", "inactive.link@example.com"
    assert _outcome(_callback(TestClient(browser.app), q["state"])) == ("error", "google_state")  # other browser: no cookie
    u = db.scalar(select(User).where(User.email == "inactive.link@example.com"))
    u.is_active = False
    db.commit()
    r2 = browser.post(f"{V1}/auth/google/link/start", headers={"Authorization": f"Bearer {tok}"})
    assert r2.status_code == 401  # deactivated accounts cannot even start


def test_inactive_google_user_cannot_sign_in(browser, fake, db):
    fake.sub, fake.email = "g-sub-inactive-login", "inactive.google@example.com"
    _, cb = _flow(browser, fake)
    uid = _exchange(browser, _outcome(cb)[1]).json()["user"]["id"]
    u = db.get(User, uid)
    u.is_active = False
    db.commit()
    assert _outcome(_flow(TestClient(browser.app), fake)[1]) == ("error", "google_inactive")


def test_google_registration_respects_the_registration_policy(browser, fake, db, monkeypatch):
    monkeypatch.setattr(get_settings(), "registration_org_slug", "")
    users = _count_users(db)
    fake.sub, fake.email = "g-sub-closed", "closed.doors@example.com"
    assert _outcome(_flow(browser, fake)[1]) == ("error", "google_registration_disabled")
    assert _count_users(db) == users


def test_concurrent_first_logins_of_one_google_account_create_one_user(fake, db, seeded):
    from app.main import app

    fake.sub, fake.email = "g-sub-race", "race.google@example.com"
    clients = [TestClient(app) for _ in range(3)]
    flows = []
    for i, c in enumerate(clients):
        _, q = _start(c, fake)
        fake.nonce_by_code[f"race-code-{i}"] = q["nonce"]
        flows.append(q["state"])

    def go(i):
        return _outcome(_callback(clients[i], flows[i], code=f"race-code-{i}"))

    with ThreadPoolExecutor(3) as ex:
        results = list(ex.map(go, range(3)))
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(User).where(User.email == "race.google@example.com")) == 1
    assert db.scalar(select(func.count()).select_from(ExternalIdentity).where(ExternalIdentity.subject == "g-sub-race")) == 1
    assert all(kind in ("ticket", "error") for kind, _ in results) and any(kind == "ticket" for kind, _ in results), results


@pytest.mark.parametrize("name", ["x" * 200, "Line\nBreak Name", "", "   "])
def test_hostile_or_missing_google_display_names_fall_back_instead_of_failing(browser, fake, db, name):
    fake.sub, fake.email, fake.name = f"g-sub-name-{abs(hash(name))}", f"name.case.{abs(hash(name))}@example.com", name
    _, cb = _flow(browser, fake)
    assert _outcome(cb)[0] == "ticket"
    u = db.scalar(select(User).where(User.email == fake.email))
    assert u and 0 < len(u.full_name) <= 80 and "\n" not in u.full_name
