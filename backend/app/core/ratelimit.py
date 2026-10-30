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


RETENTION_SECONDS = 3600


class FailureLimiter:
    def retry_after(self, db: Session, key: str, limit: int, window: int) -> int:
        since = utcnow() - timedelta(seconds=window)
        n, oldest = db.execute(select(func.count(), func.min(AuthFailure.created_at))
                               .where(AuthFailure.key_hash == key, AuthFailure.created_at >= since)).one()
        if n < limit or oldest is None:
            return 0
        return max(1, int(window - (utcnow() - oldest).total_seconds()) + 1)

    def fail(self, db: Session, key: str, window: int) -> None:
        # Rows are kept for at least RETENTION_SECONDS so that limits with a longer window (registration, password
        # reset) are not forgotten when a login failure prunes the table; each check still counts only its own window.
        db.execute(delete(AuthFailure).where(AuthFailure.created_at < utcnow() - timedelta(seconds=max(window, RETENTION_SECONDS))))
        db.add(AuthFailure(key_hash=key))

    def hit(self, db: Session, key: str, limit: int, window: int) -> int:
        """Count one attempt against `key` unless the limit is already reached. Returns 0 if allowed, else the seconds
        to wait. Used for actions where every attempt (not only failures) must be limited."""
        wait = self.retry_after(db, key, limit, window)
        if wait:
            return wait
        self.fail(db, key, window)
        return 0

    def reset(self, db: Session, key: str | None = None) -> None:
        stmt = delete(AuthFailure)
        if key is not None:
            stmt = stmt.where(AuthFailure.key_hash == key)
        db.execute(stmt)


login_limiter = FailureLimiter()
