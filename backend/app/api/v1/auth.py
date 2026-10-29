from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, user_permissions
from app.core.errors import AppError
from app.core.security import create_access_token, verify_password
from app.db.base import utcnow
from app.db.session import get_db
from app.models import Candidate, User
from app.services import audit

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginIn(BaseModel):
    email: str = Field(min_length=3, max_length=160)
    password: str = Field(min_length=1, max_length=200)


def me_payload(db: Session, u: User) -> dict:
    cand = db.scalar(select(Candidate).where(Candidate.user_id == u.id))
    return {"id": u.id, "email": u.email, "name": u.full_name, "role": u.role.name, "role_label": u.role.label,
            "permissions": sorted(user_permissions(u)), "organization": {"id": u.org.id, "name": u.org.name},
            "candidate_code": cand.code if cand else None}


@router.post("/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    u = db.scalar(select(User).where(User.email == body.email.strip().lower()))
    if not u or not u.is_active or not verify_password(body.password, u.password_hash):
        audit.record(db, None, "auth.login_failed", "user", None, "Failed login attempt", {"email_domain": body.email.split("@")[-1]}, org_id=1)
        db.commit()
        raise AppError("Invalid email or password", status_code=401, code="invalid_credentials")
    token, exp = create_access_token(u.id, u.role.name)
    u.last_login_at = utcnow()
    audit.record(db, u, "auth.login", "user", u.id, f"{u.full_name} signed in")
    db.commit()
    return {"access_token": token, "token_type": "bearer", "expires_at": exp, "user": me_payload(db, u)}


@router.get("/me")
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return me_payload(db, user)
