"""Password hashing, JWT issuance and the role → permission matrix.

Prototype note: tokens are HS256 JWTs signed with JWT_SECRET. Production deployments should use an
identity provider (OIDC), short-lived tokens with refresh rotation, and httpOnly cookies.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import uuid

import bcrypt
import jwt

from app.core.config import get_settings

PERMISSIONS: dict[str, str] = {
    "dashboard.read": "View the integrity command center",
    "questions.read": "Browse the question bank",
    "questions.write": "Create, edit and archive source questions",
    "variants.generate": "Generate parallel variants",
    "review.decide": "Approve, reject or request regeneration of variants",
    "calibration.read": "View calibration results",
    "calibration.run": "Run calibration and import response data",
    "exposure.read": "View exposure intelligence",
    "exposure.manage": "Quarantine/retire items and change exposure policy",
    "leaks.read": "View leak alerts and evidence",
    "leaks.manage": "Run leak detection and update investigations",
    "leaks.import": "Import authorized leak datasets",
    "assembly.read": "View assembled forms and manifests",
    "assembly.run": "Assemble test forms",
    "reports.read": "Generate and download reports",
    "settings.manage": "Change assessment policies",
    "audit.read": "View the audit log",
    "demo.reset": "Reset deterministic demo data",
    "assessment.take": "Take an assigned assessment",
}

_STAFF_READ = ["dashboard.read", "questions.read", "calibration.read", "exposure.read", "leaks.read",
               "assembly.read", "reports.read"]

ROLES: dict[str, dict] = {
    "admin": {"label": "Administrator", "description": "Full access including policies and demo reset",
              "permissions": [p for p in PERMISSIONS if p != "assessment.take"]},
    "designer": {"label": "Assessment Designer", "description": "Authors items, generates variants, assembles forms",
                 "permissions": _STAFF_READ + ["questions.write", "variants.generate", "assembly.run"]},
    "reviewer": {"label": "Reviewer", "description": "Independent approval of generated items; leak investigation",
                 "permissions": _STAFF_READ + ["review.decide", "exposure.manage", "leaks.manage"]},
    "analyst": {"label": "Psychometric Analyst", "description": "Calibration, leak analytics and reporting",
                "permissions": _STAFF_READ + ["calibration.run", "leaks.manage", "leaks.import", "audit.read"]},
    "candidate": {"label": "Candidate", "description": "Takes assigned assessments only",
                  "permissions": ["assessment.take"]},
}


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except ValueError:
        return False


def create_access_token(user_id: int, role: str) -> tuple[str, datetime]:
    s = get_settings()
    now = datetime.now(timezone.utc)
    exp = now + timedelta(minutes=s.jwt_expire_minutes)
    claims = {"sub": str(user_id), "role": role, "iat": now, "nbf": now, "exp": exp, "iss": "aptiguard",
              "jti": uuid.uuid4().hex}
    token = jwt.encode(claims, s.jwt_secret, "HS256")
    return token, exp


def decode_token(token: str) -> dict:
    return jwt.decode(token, get_settings().jwt_secret, algorithms=["HS256"], issuer="aptiguard",
                      options={"require": ["exp", "iat", "sub", "iss"]})
