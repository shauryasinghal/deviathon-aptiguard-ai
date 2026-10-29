from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.deps import get_current_user, user_permissions
from app.core.errors import AppError
from app.core.ratelimit import login_limiter
from app.core.security import create_access_token, hash_password, verify_password
from app.db.base import utcnow
from app.db.session import get_db
from app.models import Candidate, User
from app.services import audit

router = APIRouter(prefix="/auth", tags=["auth"])

# Verified against when the account does not exist, so response time does not reveal which emails are registered.
_DUMMY_HASH = hash_password("timing-equaliser-not-a-real-password")


class LoginIn(BaseModel):
    email: str = Field(min_length=3, max_length=160)
    password: str = Field(min_length=1, max_length=200)


def me_payload(db: Session, u: User) -> dict:
    cand = db.scalar(select(Candidate).where(Candidate.user_id == u.id))
    return {"id": u.id, "email": u.email, "name": u.full_name, "role": u.role.name, "role_label": u.role.label,
            "permissions": sorted(user_permissions(u)), "organization": {"id": u.org.id, "name": u.org.name},
            "candidate_code": cand.code if cand else None}


@router.post("/login")
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    s = get_settings()
    email = body.email.strip().lower()
    client = request.client.host if request.client else "unknown"
    key = f"{client}|{email}"
    wait = login_limiter.retry_after(key, s.login_max_failures, s.login_window_seconds)
    if wait:
        raise AppError(f"Too many failed sign-in attempts. Try again in {wait} seconds.", status_code=429,
                       code="rate_limited", details={"retry_after_seconds": wait})
    u = db.scalar(select(User).where(User.email == email))
    ok = verify_password(body.password, u.password_hash if u else _DUMMY_HASH)
    if not u or not ok or not u.is_active:
        login_limiter.fail(key)
        audit.record(db, None, "auth.login_failed", "user", None, "Failed login attempt",
                     {"email_domain": email.split("@")[-1],
                      "reason": "inactive" if (u and ok and not u.is_active) else "invalid_credentials"}, org_id=1)
        db.commit()
        # One message for unknown user, wrong password and inactive account (no account enumeration).
        raise AppError("Invalid email or password", status_code=401, code="invalid_credentials")
    login_limiter.reset(key)
    token, exp = create_access_token(u.id, u.role.name)
    u.last_login_at = utcnow()
    audit.record(db, u, "auth.login", "user", u.id, f"{u.full_name} signed in")
    db.commit()
    return {"access_token": token, "token_type": "bearer", "expires_at": exp, "user": me_payload(db, u)}


@router.get("/me")
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return me_payload(db, user)
