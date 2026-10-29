"""Login-failure limiter backed by the application database (table `auth_failures`).

Shared by every API process/container that uses the same database and survives restarts, without adding new
infrastructure. Keys are SHA-256(client | email); raw emails are not stored. Rows older than the window are pruned.
"""
from __future__ import annotations

import hashlib
from datetime import timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.models import AuthFailure


def key_for(client: str, email: str) -> str:
    return hashlib.sha256(f"{client}|{email}".encode()).hexdigest()


class FailureLimiter:
    def retry_after(self, db: Session, key: str, limit: int, window: int) -> int:
        since = utcnow() - timedelta(seconds=window)
        n, oldest = db.execute(select(func.count(), func.min(AuthFailure.created_at))
                               .where(AuthFailure.key_hash == key, AuthFailure.created_at >= since)).one()
        if n < limit or oldest is None:
            return 0
        return max(1, int(window - (utcnow() - oldest).total_seconds()) + 1)

    def fail(self, db: Session, key: str, window: int) -> None:
        db.execute(delete(AuthFailure).where(AuthFailure.created_at < utcnow() - timedelta(seconds=window)))
        db.add(AuthFailure(key_hash=key))

    def reset(self, db: Session, key: str | None = None) -> None:
        stmt = delete(AuthFailure)
        if key is not None:
            stmt = stmt.where(AuthFailure.key_hash == key)
        db.execute(stmt)


login_limiter = FailureLimiter()
