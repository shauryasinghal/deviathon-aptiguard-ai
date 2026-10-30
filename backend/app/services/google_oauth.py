"""Google sign-in (OAuth 2.0 authorization-code flow with PKCE + OpenID Connect), server side only.

Security properties implemented here:
* `state` is random, stored hashed in `auth_tokens`, single use, expires in 10 minutes, and is bound to the browser that
  started the flow by an HttpOnly cookie (login-CSRF protection); `nonce` and the PKCE verifier are stored with it.
* The authorization code is exchanged by the backend using the client secret; nothing from Google reaches the browser.
* The ID token's RS256 signature is verified against Google's published keys, together with issuer, audience, expiry,
  issued-at, required claims, nonce and `email_verified`.
* The external identity is Google's stable `sub`. An e-mail match NEVER merges or logs into an existing account: linking
  requires an authenticated session of that account (see `start_flow(link_user_id=...)`). Demo accounts can never be
  linked or created, and Google-created users are always candidates.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import secrets
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx
import jwt
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import ExternalIdentity, User
from app.services import accounts, audit

log = logging.getLogger("aptiguard.google")

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
ISSUERS = ["https://accounts.google.com", "accounts.google.com"]
SCOPE = "openid email profile"
STATE_TTL = 600
TICKET_TTL = 60
PROVIDER = "google"


class OAuthError(Exception):
    """`code` is one of the fixed, safe identifiers the frontend knows how to display (never provider text)."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass
class Outcome:
    kind: str  # login | linked
    user: User


# ------------------------------------------------------------------ step 1: authorization request
def start_flow(db: Session, mode: str = "login", link_user_id: int | None = None) -> tuple[str, str]:
    """Create the single-use state and return (authorization_url, browser_binding_secret)."""
    s = get_settings()
    if not s.google_configured:
        raise OAuthError("google_not_configured")
    state, nonce = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    verifier, bind = secrets.token_urlsafe(64), secrets.token_urlsafe(32)
    accounts.issue_token(db, "oauth_state", STATE_TTL, user_id=link_user_id, raw=state,
                         payload={"nonce": nonce, "verifier": verifier, "mode": mode, "bind": accounts.hash_token(bind)})
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    url = AUTH_URL + "?" + urlencode({
        "client_id": s.google_client_id, "redirect_uri": s.google_redirect_uri, "response_type": "code", "scope": SCOPE,
        "state": state, "nonce": nonce, "code_challenge": challenge, "code_challenge_method": "S256",
        "prompt": "select_account"})
    return url, bind


# ------------------------------------------------------------------ step 2: code exchange + ID-token validation
def exchange_code(code: str, verifier: str) -> str:
    s = get_settings()
    try:
        r = httpx.post(TOKEN_URL, data={"code": code, "client_id": s.google_client_id, "client_secret": s.google_client_secret,
                                        "redirect_uri": s.google_redirect_uri, "grant_type": "authorization_code",
                                        "code_verifier": verifier}, timeout=10.0)
    except httpx.HTTPError:
        log.warning("Google token endpoint unreachable")
        raise OAuthError("google_failed") from None
    if r.status_code != 200:
        log.warning("Google token exchange refused (HTTP %s)", r.status_code)  # body is never logged: it may echo the code
        raise OAuthError("google_failed")
    try:
        id_token = r.json().get("id_token")
    except ValueError:
        id_token = None
    if not isinstance(id_token, str) or not id_token:
        raise OAuthError("google_failed")
    return id_token


_jwks: jwt.PyJWKClient | None = None


def _signing_key(id_token: str):
    """Google's public key for this token (cached by PyJWKClient). Replaced by tests; the network is never used there."""
    global _jwks
    if _jwks is None:
        _jwks = jwt.PyJWKClient(JWKS_URL, cache_keys=True, timeout=10)
    return _jwks.get_signing_key_from_jwt(id_token).key


def verify_id_token(id_token: str, nonce: str) -> dict:
    s = get_settings()
    try:
        key = _signing_key(id_token)
        claims = jwt.decode(id_token, key, algorithms=["RS256"], audience=s.google_client_id, issuer=ISSUERS, leeway=30,
                            options={"require": ["exp", "iat", "aud", "iss", "sub"]})
    except jwt.PyJWTError:
        raise OAuthError("google_failed") from None
    except Exception:  # noqa: BLE001 - JWKS fetch/parse problems are provider failures, not crashes
        log.warning("could not obtain Google signing keys")
        raise OAuthError("google_failed") from None
    if not hmac.compare_digest(str(claims.get("nonce", "")), nonce):
        raise OAuthError("google_failed")
    sub, email = claims.get("sub"), claims.get("email")
    if not isinstance(sub, str) or not sub or len(sub) > 255 or not isinstance(email, str) or not email:
        raise OAuthError("google_failed")
    if claims.get("email_verified") not in (True, "true"):
        raise OAuthError("google_email_unverified")
    claims["email"] = accounts.normalize_email(email)
    return claims


# ------------------------------------------------------------------ step 3: resolve the identity to an account
def complete_flow(db: Session, state: str, code: str, bind_cookie: str | None) -> Outcome:
    st = accounts.claim_token(db, "oauth_state", state)  # single use: consumed before anything else is checked
    if st is None:
        raise OAuthError("google_state")
    payload = st.payload or {}
    if not bind_cookie or not hmac.compare_digest(accounts.hash_token(bind_cookie), str(payload.get("bind", ""))):
        raise OAuthError("google_state")  # state was not started by this browser (login CSRF)
    claims = verify_id_token(exchange_code(code, payload["verifier"]), payload["nonce"])
    sub, email, name = claims["sub"], claims["email"], str(claims.get("name") or "").strip()

    if payload.get("mode") == "link":
        return _link(db, st.user_id, sub, email)

    ident = db.scalar(select(ExternalIdentity).where(ExternalIdentity.provider == PROVIDER, ExternalIdentity.subject == sub))
    if ident is not None:
        return _login_existing(db, ident)
    if db.scalar(select(User.id).where(User.email == email)) is not None:
        # An account with this address exists. Never merge on an e-mail match (a Google address is not proof of owning
        # the local account, and local accounts may be staff or demo accounts): the owner must link while signed in.
        raise OAuthError("google_account_exists")
    return _register(db, sub, email, name)


def _login_existing(db: Session, ident: ExternalIdentity) -> Outcome:
    user = db.get(User, ident.user_id)
    if user is None or not user.is_active:
        raise OAuthError("google_inactive")
    if accounts.is_demo_email(user.email):
        raise OAuthError("google_demo_blocked")
    return Outcome("login", user)


def _link(db: Session, user_id: int | None, sub: str, email: str) -> Outcome:
    user = db.get(User, user_id) if user_id else None
    if user is None or not user.is_active:
        raise OAuthError("google_inactive")
    if accounts.is_demo_email(user.email):
        raise OAuthError("google_demo_blocked")
    if email != accounts.normalize_email(user.email):
        raise OAuthError("google_link_mismatch")  # the verified Google address must be the account's own address
    if db.scalar(select(ExternalIdentity.id).where(ExternalIdentity.provider == PROVIDER, ExternalIdentity.subject == sub)):
        raise OAuthError("google_link_conflict")  # this Google account already belongs to a local account
    if db.scalar(select(ExternalIdentity.id).where(ExternalIdentity.provider == PROVIDER, ExternalIdentity.user_id == user.id)):
        raise OAuthError("google_link_conflict")  # this account already has a Google identity
    try:
        with db.begin_nested():
            db.add(ExternalIdentity(user_id=user.id, provider=PROVIDER, subject=sub, email=email))
            db.flush()
    except IntegrityError:
        raise OAuthError("google_link_conflict") from None
    audit.record(db, user, "auth.google_linked", "user", user.id, f"{user.full_name} linked a Google account")
    return Outcome("linked", user)


def _register(db: Session, sub: str, email: str, name: str) -> Outcome:
    if accounts.is_demo_email(email) or not accounts.valid_email(email):
        raise OAuthError("google_demo_blocked" if accounts.is_demo_email(email) else "google_failed")
    try:
        org = accounts.registration_org(db)
    except Exception:  # noqa: BLE001 - registration_disabled
        raise OAuthError("google_registration_disabled") from None
    try:
        display = accounts.clean_name(name)  # Google's display name is untrusted input: too long / control characters
    except Exception:  # noqa: BLE001 - fall back to the mailbox name instead of failing the sign-in
        display = " ".join(email.split("@")[0].split())[:80] or "Candidate"
    try:
        with db.begin_nested():
            user = accounts.create_candidate_user(db, org, display, email, accounts.unusable_password_hash())
            db.add(ExternalIdentity(user_id=user.id, provider=PROVIDER, subject=sub, email=email))
            db.flush()
    except IntegrityError:
        # a concurrent callback for the same Google account created it first: use that identity
        ident = db.scalar(select(ExternalIdentity).where(ExternalIdentity.provider == PROVIDER, ExternalIdentity.subject == sub))
        if ident is None:
            raise OAuthError("google_failed") from None
        return _login_existing(db, ident)
    except Exception as e:  # noqa: BLE001 - Conflict(email_taken) from a concurrent request
        if getattr(e, "code", "") == "email_taken":
            raise OAuthError("google_account_exists") from None
        raise
    audit.record(db, user, "auth.registered", "user", user.id, "Candidate registered with Google", {"method": "google"})
    return Outcome("login", user)


def issue_ticket(db: Session, user: User) -> str:
    """One-time login ticket handed to the SPA in the redirect; exchanged for our own JWT over POST, so no token or
    Google secret ever appears in a URL."""
    return accounts.issue_token(db, "login_ticket", TICKET_TTL, user_id=user.id)


__all__ = ["OAuthError", "Outcome", "start_flow", "complete_flow", "issue_ticket"]
