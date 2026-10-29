"""Idempotent bootstrap for non-demo deployments: reference data (permissions, roles, sections) and the first admin.

    python -m app.bootstrap                      # reference data only (safe to run on every start)
    python /srv/scripts/create_admin.py          # first administrator (see scripts/create_admin.py)

Never deletes or modifies business data. Role permissions are synchronised with app/core/security.py.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import PERMISSIONS, ROLES, hash_password
from app.models import Organization, Permission, Role, Section, User
from app.services import audit

SECTIONS = [("QUANT", "Quantitative Reasoning", "Arithmetic, rates, interest, ratios and probability"),
            ("LOGICAL", "Logical Reasoning", "Series, syllogisms, arrangements, coding and directions"),
            ("VERBAL", "Verbal Reasoning", "Vocabulary, analogies, grammar and reading inference")]
MIN_ADMIN_PASSWORD = 12


def ensure_reference_data(db: Session) -> dict:
    created = {"permissions": 0, "roles": 0, "sections": 0}
    perms = {p.code: p for p in db.scalars(select(Permission)).all()}
    for code, desc in PERMISSIONS.items():
        if code not in perms:
            perms[code] = Permission(code=code, description=desc)
            db.add(perms[code])
            created["permissions"] += 1
    db.flush()
    for name, spec in ROLES.items():
        role = db.scalar(select(Role).where(Role.name == name))
        if role is None:
            role = Role(name=name, label=spec["label"], description=spec["description"])
            db.add(role)
            created["roles"] += 1
        role.permissions = [perms[p] for p in spec["permissions"]]
    for code, name, desc in SECTIONS:
        if not db.scalar(select(Section).where(Section.code == code)):
            db.add(Section(code=code, name=name, description=desc))
            created["sections"] += 1
    db.flush()
    return created


def create_admin(db: Session, org_name: str, org_slug: str, email: str, full_name: str, password: str) -> User:
    if len(password) < MIN_ADMIN_PASSWORD:
        raise ValueError(f"Admin password must be at least {MIN_ADMIN_PASSWORD} characters")
    email = email.strip().lower()
    if "@" not in email:
        raise ValueError("A valid email is required")
    if db.scalar(select(User).where(User.email == email)):
        raise ValueError("A user with this email already exists")
    ensure_reference_data(db)
    org = db.scalar(select(Organization).where(Organization.slug == org_slug))
    if org is None:
        org = Organization(name=org_name, slug=org_slug)
        db.add(org)
        db.flush()
    admin_role = db.scalar(select(Role).where(Role.name == "admin"))
    u = User(org_id=org.id, email=email, full_name=full_name, password_hash=hash_password(password), role_id=admin_role.id)
    db.add(u)
    db.flush()
    audit.record(db, None, "auth.admin_bootstrapped", "user", u.id, f"Administrator account created for {full_name}", org_id=org.id)
    return u


if __name__ == "__main__":
    from app.db.session import SessionLocal

    with SessionLocal() as s:
        out = ensure_reference_data(s)
        s.commit()
    print(f"reference data ensured: {out}")
