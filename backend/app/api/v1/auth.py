from __future__ import annotations

import logging
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.deps import get_current_user, require, user_permissions
from app.core.errors import AppError, NotFound
from app.core.ratelimit import key_for, login_limiter
from app.core.security import create_access_token, hash_password, verify_password
from app.db.base import utcnow
from app.db.session import get_db
from app.models import AuthToken, Candidate, ExternalIdentity, User
from app.services import accounts, audit, google_oauth

router = APIRouter(prefix="/auth", tags=["auth"])
log = logging.getLogger("aptiguard.auth")

# Verified against when the account does not exist, so response time does not reveal which emails are registered.
_DUMMY_HASH = hash_password("timing-equaliser-not-a-real-password")


class LoginIn(BaseModel):
    email: str = Field(min_length=3, max_length=160)
    password: str = Field(min_length=1, max_length=200)


def me_payload(db: Session, u: User) -> dict:
    cand = db.scalar(select(Candidate).where(Candidate.user_id == u.id))
    linked = db.scalar(select(ExternalIdentity.id).where(ExternalIdentity.user_id == u.id, ExternalIdentity.provider == "google"))
    return {"id": u.id, "email": u.email, "name": u.full_name, "role": u.role.name, "role_label": u.role.label,
            "permissions": sorted(user_permissions(u)), "organization": {"id": u.org.id, "name": u.org.name},
            "candidate_code": cand.code if cand else None, "auth_methods": {"google": linked is not None}}


@router.post("/login")
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    s = get_settings()
    email = body.email.strip().lower()
    client = request.client.host if request.client else "unknown"
    key = key_for(client, email)
    wait = login_limiter.retry_after(db, key, s.login_max_failures, s.login_window_seconds)
    if wait:
        raise AppError(f"Too many failed sign-in attempts. Try again in {wait} seconds.", status_code=429,
                       code="rate_limited", details={"retry_after_seconds": wait})
    u = db.scalar(select(User).where(User.email == email))
    ok = verify_password(body.password, u.password_hash if u else _DUMMY_HASH)
    if not u or not ok or not u.is_active:
        login_limiter.fail(db, key, s.login_window_seconds)
        # Only failures against a REAL account are audited, in that account's organisation. An unknown email belongs to
        # no organisation, so writing it anywhere would let unauthenticated callers fill an arbitrary tenant's audit log
        # (and queue on the audit-chain lock). The limiter above still records every failure in auth_failures.
        if u is not None:
            audit.record(db, None, "auth.login_failed", "user", None, "Failed login attempt",
                         {"email_domain": email.split("@")[-1],
                          "reason": "inactive" if (ok and not u.is_active) else "invalid_credentials"},
                         org_id=u.org_id)
        db.commit()
        # One message for unknown user, wrong password and inactive account (no account enumeration).
        raise AppError("Invalid email or password", status_code=401, code="invalid_credentials")
    login_limiter.reset(db, key)
    token, exp = create_access_token(u.id, u.role.name, u.token_version)
    u.last_login_at = utcnow()
    audit.record(db, u, "auth.login", "user", u.id, f"{u.full_name} signed in")
    db.commit()
    return {"access_token": token, "token_type": "bearer", "expires_at": exp, "user": me_payload(db, u)}


@router.get("/me")
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return me_payload(db, user)


@router.post("/logout")
def logout(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Revoke every outstanding token of this user (sign out everywhere)."""
    user.token_version = (user.token_version or 0) + 1
    audit.record(db, user, "auth.logout", "user", user.id, f"{user.full_name} signed out (all sessions revoked)")
    db.commit()
    return {"status": "signed_out"}


@router.post("/users/{user_id}/revoke-sessions")
def revoke_sessions(user_id: int, admin: User = Depends(require("settings.manage")), db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if not u or u.org_id != admin.org_id:
        raise NotFound("User not found")
    u.token_version = (u.token_version or 0) + 1
    audit.record(db, admin, "auth.sessions_revoked", "user", u.id, f"All sessions of {u.full_name} revoked by {admin.full_name}")
    db.commit()
    return {"status": "revoked", "user_id": u.id}


# ================================================================== self-registration, password reset, Google sign-in
# All three coexist with the unchanged /login (used by the demo accounts too). Public registration can only ever create a
# CANDIDATE in the organisation named by REGISTRATION_ORG_SLUG; the request body cannot carry a role or organisation.
def _client(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _throttle(db: Session, key: str, limit: int, window: int) -> None:
    wait = login_limiter.hit(db, key, limit, window)
    db.commit()  # keep the count even when the request fails afterwards
    if wait:
        raise AppError(f"Too many attempts. Try again in {wait} seconds.", status_code=429, code="rate_limited",
                       details={"retry_after_seconds": wait})


def _session(db: Session, u: User, method: str) -> dict:
    token, exp = create_access_token(u.id, u.role.name, u.token_version)
    u.last_login_at = utcnow()
    audit.record(db, u, "auth.login", "user", u.id, f"{u.full_name} signed in", {"method": method})
    return {"access_token": token, "token_type": "bearer", "expires_at": exp, "user": me_payload(db, u)}


@router.get("/providers")
def providers():
    """What the login page may offer. No secrets; `registration` only says whether public sign-up is switched on."""
    s = get_settings()
    return {"password": True, "google": s.google_configured, "registration": bool(s.registration_org_slug.strip()),
            "password_reset": True, "demo_mode": s.demo_mode and not s.is_production}


class RegisterIn(BaseModel):
    model_config = ConfigDict(extra="forbid")  # a client-supplied role / org_id / permissions is rejected, not ignored
    name: str = Field(min_length=1, max_length=80)
    email: str = Field(min_length=3, max_length=160)
    password: str = Field(min_length=1, max_length=200)


@router.post("/register", status_code=201)
def register(body: RegisterIn, request: Request, db: Session = Depends(get_db)):
    _throttle(db, key_for("register", _client(request)), 10, 3600)
    org = accounts.registration_org(db)  # 403 when self-registration is not enabled
    email = accounts.normalize_email(body.email)
    if not accounts.valid_email(email):
        raise AppError("Enter a valid email address", status_code=422, code="invalid_email")
    if accounts.is_demo_email(email):
        raise AppError("This email address cannot be used to register", status_code=422, code="email_reserved")
    name = accounts.clean_name(body.name)
    accounts.require_good_password(body.password, email, name)
    user = accounts.create_candidate_user(db, org, name, email, hash_password(body.password))
    audit.record(db, user, "auth.registered", "user", user.id, "Candidate registered with email and password", {"method": "password"})
    out = _session(db, user, "password")
    db.commit()
    return out


class ForgotIn(BaseModel):
    email: str = Field(min_length=3, max_length=160)


_FORGOT_REPLY = {"status": "accepted", "message": "If an account exists for that email, a reset link has been sent."}


def _deliver_reset(email: str, raw: str) -> None:
    s = get_settings()
    if s.password_reset_delivery == "log" and not s.is_production:
        # DEVELOPMENT ONLY: there is no e-mail service, so the link is written to the server log. It is never returned
        # in the HTTP response (that would let anyone reset any account).
        log.warning("DEV password-reset link for %s: %s/reset-password?token=%s", email, s.frontend_url.rstrip("/"), raw)


@router.post("/password/forgot", status_code=202)
def forgot_password(body: ForgotIn, request: Request, db: Session = Depends(get_db)):
    _throttle(db, key_for("forgot", _client(request)), 10, 3600)
    email = accounts.normalize_email(body.email)
    allowed = login_limiter.hit(db, key_for("forgot-email", email), 3, 3600) == 0  # per-address cap, silent
    user = db.scalar(select(User).where(User.email == email)) if (allowed and accounts.valid_email(email)) else None
    if user is not None and user.is_active and not accounts.is_demo_email(user.email):
        accounts.invalidate_tokens(db, "password_reset", user.id)
        raw = accounts.issue_token(db, "password_reset", get_settings().password_reset_ttl_minutes * 60, user_id=user.id)
        audit.record(db, user, "auth.password_reset_requested", "user", user.id, "Password reset requested")
        _deliver_reset(user.email, raw)
    db.commit()
    return _FORGOT_REPLY  # identical for unknown, inactive, demo and rate-limited addresses


class ResetIn(BaseModel):
    token: str = Field(min_length=10, max_length=256)
    password: str = Field(min_length=1, max_length=200)


@router.post("/password/reset")
def reset_password(body: ResetIn, request: Request, db: Session = Depends(get_db)):
    _throttle(db, key_for("reset", _client(request)), 10, 3600)
    bad = AppError("This reset link is invalid or has expired", status_code=400, code="invalid_token")
    h, now = accounts.hash_token(body.token), utcnow()
    row = db.scalar(select(AuthToken).where(AuthToken.token_hash == h, AuthToken.kind == "password_reset",
                                            AuthToken.used_at.is_(None), AuthToken.expires_at > now))
    user = db.get(User, row.user_id) if row and row.user_id else None
    if user is None or not user.is_active or accounts.is_demo_email(user.email):
        raise bad
    accounts.require_good_password(body.password, user.email, user.full_name)  # before consuming: a weak password can retry
    if accounts.claim_token(db, "password_reset", body.token) is None:  # atomic single use (a concurrent reuse loses)
        raise bad
    user = db.get(User, user.id)
    user.password_hash = hash_password(body.password)
    user.token_version = (user.token_version or 0) + 1  # every existing session of this account is revoked
    accounts.invalidate_tokens(db, "password_reset", user.id)
    audit.record(db, user, "auth.password_reset", "user", user.id, "Password changed through a reset link; all sessions revoked")
    db.commit()
    return {"status": "password_updated"}


# ------------------------------------------------------------------ Google
BIND_COOKIE = "ag_oauth_bind"
BIND_PATH = "/api/v1/auth/google"


def _front(path: str, **query) -> str:
    """Redirect target: the configured frontend origin + a FIXED internal route. Nothing from the request is echoed."""
    return get_settings().frontend_url.rstrip("/") + path + (("?" + urlencode(query)) if query else "")


def _set_bind(resp, bind: str) -> None:
    resp.set_cookie(BIND_COOKIE, bind, max_age=google_oauth.STATE_TTL, httponly=True, samesite="lax", path=BIND_PATH,
                    secure=get_settings().google_redirect_uri.startswith("https://"))


def _fail(code: str, clear_cookie: bool = True) -> RedirectResponse:
    resp = RedirectResponse(_front("/auth/callback", error=code), status_code=302)
    if clear_cookie:
        resp.delete_cookie(BIND_COOKIE, path=BIND_PATH)
    return resp


@router.get("/google/start")
def google_start(request: Request, db: Session = Depends(get_db)):
    """Begin Google sign-in / sign-up. Browser navigation endpoint: always answers with a redirect."""
    if login_limiter.hit(db, key_for("google", _client(request)), 20, 300):
        db.commit()
        return _fail("google_failed")
    try:
        url, bind = google_oauth.start_flow(db, "login")
    except google_oauth.OAuthError as e:
        db.commit()
        return _fail(e.code)
    db.commit()
    resp = RedirectResponse(url, status_code=302)
    _set_bind(resp, bind)
    return resp


@router.post("/google/link/start")
def google_link_start(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Start linking a Google account to the account that is CURRENTLY signed in. This is the only way to attach a Google
    identity to an existing account."""
    if accounts.is_demo_email(user.email):
        raise AppError("Demo accounts cannot be linked to Google", status_code=403, code="demo_blocked")
    try:
        url, bind = google_oauth.start_flow(db, "link", link_user_id=user.id)
    except google_oauth.OAuthError as e:
        raise AppError("Google sign-in is not configured on this server", status_code=503, code=e.code) from None
    db.commit()
    resp = JSONResponse({"authorization_url": url})
    _set_bind(resp, bind)
    return resp


@router.get("/google/callback")
def google_callback(request: Request, code: str | None = None, state: str | None = None, error: str | None = None,
                    db: Session = Depends(get_db)):
    if error:  # consent denied / cancelled / provider error: burn the state if we can, then show a fixed message
        if state:
            accounts.claim_token(db, "oauth_state", state)
            db.commit()
        return _fail("google_denied", clear_cookie=False)
    if not code or not state or len(code) > 2048:
        return _fail("google_failed", clear_cookie=False)
    try:
        outcome = google_oauth.complete_flow(db, state, code, request.cookies.get(BIND_COOKIE))
    except google_oauth.OAuthError as e:
        db.commit()  # persist the consumed state
        # An unknown/replayed/foreign state must not clear the cookie: otherwise anyone could break a victim's in-flight
        # sign-in by sending them a forged callback link.
        return _fail(e.code, clear_cookie=e.code != "google_state")
    except Exception:  # noqa: BLE001 - never leak provider/internal detail to the browser
        log.exception("google callback failed")
        db.rollback()
        return _fail("google_failed")
    if outcome.kind == "linked":
        db.commit()
        resp = RedirectResponse(_front("/auth/callback", status="linked"), status_code=302)
    else:
        ticket = google_oauth.issue_ticket(db, outcome.user)
        db.commit()
        resp = RedirectResponse(_front("/auth/callback", ticket=ticket), status_code=302)
    resp.delete_cookie(BIND_COOKIE, path=BIND_PATH)
    return resp


class ExchangeIn(BaseModel):
    ticket: str = Field(min_length=10, max_length=256)


@router.post("/google/exchange")
def google_exchange(body: ExchangeIn, request: Request, db: Session = Depends(get_db)):
    """Swap the one-time ticket from the callback redirect for our own session token (same format as /login)."""
    _throttle(db, key_for("exchange", _client(request)), 30, 300)
    tok = accounts.claim_token(db, "login_ticket", body.ticket)
    user = db.get(User, tok.user_id) if tok and tok.user_id else None
    if user is None or not user.is_active or accounts.is_demo_email(user.email):
        db.commit()
        raise AppError("This sign-in link is invalid or has expired", status_code=401, code="invalid_ticket")
    out = _session(db, user, "google")
    db.commit()
    return out
