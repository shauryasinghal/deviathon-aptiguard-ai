"""Account helpers for self-registration, password reset and Google sign-in: input validation, the reserved demo
domain, single-use tokens and candidate creation. Nothing here trusts a client-supplied role or organisation."""
from __future__ import annotations

import hashlib
import re
import secrets
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AppError, Conflict, Forbidden, Unprocessable
from app.core.security import hash_password
from app.db.base import utcnow
from app.models import AuthToken, Candidate, Organization, Role, User

# The seeded synthetic demo accounts all live in this domain. It is reserved: nobody can register, reset a password,
# sign in with Google or link a Google identity for an address in it, so demo accounts can never be taken over or
# turned into ordinary accounts, and demo login keeps working exactly as before.
DEMO_EMAIL_DOMAIN = "aptiguard.demo"

_EMAIL_RE = re.compile(
    r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$")
_COMMON = {"password1234", "passwordpassword", "123456789012", "qwertyuiop12", "letmein12345", "aptiguard-demo-2026"}
MIN_PASSWORD = 12
MAX_PASSWORD_BYTES = 72  # bcrypt ignores everything after 72 bytes; refuse instead of silently truncating


def normalize_email(email: str) -> str:
    return email.strip().lower()


def valid_email(email: str) -> bool:
    return len(email) <= 160 and ".." not in email and bool(_EMAIL_RE.match(email))


def is_demo_email(email: str) -> bool:
    e = normalize_email(email)
    return e.endswith("@" + DEMO_EMAIL_DOMAIN) or e.endswith("." + DEMO_EMAIL_DOMAIN)


def clean_name(name: str) -> str:
    n = " ".join(name.split())
    if not n or len(n) > 80 or any(ord(c) < 32 for c in name):
        raise Unprocessable("Name must be 1–80 characters")
    return n


def password_problems(password: str, email: str = "", name: str = "") -> list[str]:
    out = []
    if len(password) < MIN_PASSWORD:
        out.append(f"at least {MIN_PASSWORD} characters")
    if len(password.encode()) > MAX_PASSWORD_BYTES:
        out.append(f"at most {MAX_PASSWORD_BYTES} bytes")
    if len(set(password)) < 5:
        out.append("not a repetition of a few characters")
    local = normalize_email(email).split("@")[0]
    if len(local) >= 4 and local in password.lower():
        out.append("must not contain your email name")
    if password.lower() in _COMMON:
        out.append("not a commonly used password")
    return out


def require_good_password(password: str, email: str = "", name: str = "") -> None:
    problems = password_problems(password, email, name)
    if problems:
        raise Unprocessable("Password is too weak: " + "; ".join(problems), {"requirements": problems})


# ------------------------------------------------------------------ single-use tokens
def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def issue_token(db: Session, kind: str, ttl_seconds: int, user_id: int | None = None, payload: dict | None = None,
                raw: str | None = None) -> str:
    raw = raw or secrets.token_urlsafe(32)
    db.add(AuthToken(kind=kind, token_hash=hash_token(raw), user_id=user_id, payload=payload,
                     expires_at=utcnow() + timedelta(seconds=ttl_seconds)))
    db.flush()
    return raw


def claim_token(db: Session, kind: str, raw: str) -> AuthToken | None:
    """Consume a token exactly once. The guarded UPDATE is atomic, so of two concurrent claims only one succeeds;
    expired, unknown, already-used or wrong-kind tokens all return None (callers must not distinguish them)."""
    if not raw or len(raw) > 256:
        return None
    h, now = hash_token(raw), utcnow()
    n = db.execute(update(AuthToken).where(AuthToken.token_hash == h, AuthToken.kind == kind, AuthToken.used_at.is_(None),
                                           AuthToken.expires_at > now).values(used_at=now)
                   .execution_options(synchronize_session=False)).rowcount
    if n != 1:
        return None
    db.expire_all()
    return db.scalar(select(AuthToken).where(AuthToken.token_hash == h))


def invalidate_tokens(db: Session, kind: str, user_id: int) -> None:
    db.execute(update(AuthToken).where(AuthToken.kind == kind, AuthToken.user_id == user_id, AuthToken.used_at.is_(None))
               .values(used_at=utcnow()).execution_options(synchronize_session=False))


# ------------------------------------------------------------------ registration
def unusable_password_hash() -> str:
    """For accounts created through Google: a bcrypt hash of a random secret nobody knows, so password login is impossible
    until the owner sets a password through the password-reset flow."""
    return hash_password(secrets.token_urlsafe(48))


def registration_org(db: Session) -> Organization:
    slug = get_settings().registration_org_slug.strip()
    org = db.scalar(select(Organization).where(Organization.slug == slug)) if slug else None
    if org is None:
        raise Forbidden("Self-registration is not enabled", code="registration_disabled")
    return org


def _new_candidate_code(db: Session, org_id: int) -> str:
    for _ in range(10):
        code = "CAND-" + secrets.token_hex(4).upper()
        if not db.scalar(select(Candidate.id).where(Candidate.org_id == org_id, Candidate.code == code)):
            return code
    raise AppError("Could not allocate a candidate code", status_code=503, code="unavailable")


def create_candidate_user(db: Session, org: Organization, name: str, email: str, password_hash: str) -> User:
    """Create a CANDIDATE user + pseudonymous candidate record. Role is fixed here; callers cannot choose it. Raises
    Conflict if the e-mail is taken (also under concurrent requests: the unique constraint decides)."""
    role = db.scalar(select(Role).where(Role.name == "candidate"))
    if role is None:
        raise AppError("Candidate role is not configured", status_code=503, code="unavailable")
    user = User(org_id=org.id, email=email, full_name=name, password_hash=password_hash, role_id=role.id, is_active=True)
    try:
        with db.begin_nested():
            db.add(user)
            db.flush()
    except IntegrityError:
        raise Conflict("An account with this email already exists", code="email_taken") from None
    code = _new_candidate_code(db, org.id)
    db.add(Candidate(org_id=org.id, code=code, display_name=name[:80], user_id=user.id, is_synthetic=False))
    db.flush()
    return user
