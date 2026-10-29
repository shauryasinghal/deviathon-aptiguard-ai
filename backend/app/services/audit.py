"""Append-only, tamper-evident audit log.

Each event stores hash = sha256(prev_hash || canonical(event)). Editing, deleting or re-ordering any stored event
breaks verification from that point on (`verify_chain`). Writers are serialised so the chain cannot fork:
PostgreSQL takes a transaction-scoped advisory lock; SQLite takes its database write lock before reading the head.
This detects tampering by anyone who cannot also recompute every later hash (e.g. ad-hoc edits); it is not a
substitute for write-once external log storage.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.models import AuditEvent, User

GENESIS = "0" * 64
_LOCK_KEY = 7_107_001  # arbitrary advisory-lock id for the audit chain


def canonical(org_id: int, actor_id: int | None, actor_label: str, action: str, entity_type: str,
              entity_id: str | None, summary: str, details: Any, created_at: datetime) -> str:
    return json.dumps([org_id, actor_id, actor_label, action, entity_type, entity_id, summary, details,
                       created_at.isoformat()],
                      sort_keys=True, separators=(",", ":"), default=str, ensure_ascii=False)


def event_hash(prev: str, content: str) -> str:
    return hashlib.sha256((prev + content).encode("utf-8")).hexdigest()


def _lock_chain(db: Session) -> None:
    dialect = db.get_bind().dialect.name
    if dialect == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _LOCK_KEY})
    elif dialect == "sqlite":
        # a write statement acquires SQLite's RESERVED lock for this transaction before we read the chain head
        db.execute(text("UPDATE audit_events SET id = id WHERE id = -1"))


def record(
    db: Session,
    actor: User | None,
    action: str,
    entity_type: str,
    entity_id: Any,
    summary: str,
    details: dict | None = None,
    org_id: int | None = None,
) -> AuditEvent:
    db.flush()  # earlier events of this transaction must be visible as the chain head
    _lock_chain(db)
    prev = db.scalar(select(AuditEvent.hash).where(AuditEvent.hash.is_not(None)).order_by(AuditEvent.id.desc()).limit(1)) or GENESIS
    ev = AuditEvent(
        org_id=org_id or (actor.org_id if actor else 1),
        actor_id=actor.id if actor else None,
        actor_label=f"{actor.full_name} ({actor.role.label})" if actor else "system",
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        summary=summary[:400],
        details=json.loads(json.dumps(details, default=str)) if details is not None else None,
        created_at=utcnow(),
    )
    ev.prev_hash = prev
    ev.hash = event_hash(prev, canonical(ev.org_id, ev.actor_id, ev.actor_label, ev.action, ev.entity_type, ev.entity_id,
                                         ev.summary, ev.details, ev.created_at))
    db.add(ev)
    db.flush()
    return ev


def verify_chain(db: Session, limit: int | None = None, anchor_count: int | None = None,
                 anchor_head: str | None = None) -> dict:
    """Walk the chain in id order. Returns the first broken event, if any.

    Optional external anchor: an operator who recorded `head` and `checked` from an earlier verification in storage the
    database administrator cannot rewrite can pass them back as anchor_head/anchor_count. Then deleting the newest
    events (which the chain alone cannot reveal) or rewriting the history that the anchor covers is detected too.
    Without such an anchor a party able to recompute every hash can still rewrite the whole chain undetected.
    """
    prev = GENESIS
    n = 0
    anchored = anchor_count is None
    stmt = select(AuditEvent).order_by(AuditEvent.id)
    for ev in db.scalars(stmt).yield_per(1000):
        if ev.hash is None:  # rows written before migration 0004 were back-filled; None means an untracked insert
            return {"ok": False, "checked": n, "broken_at_id": ev.id, "reason": "event without hash"}
        expect = event_hash(prev, canonical(ev.org_id, ev.actor_id, ev.actor_label, ev.action, ev.entity_type,
                                            ev.entity_id, ev.summary, ev.details, ev.created_at))
        if ev.prev_hash != prev or ev.hash != expect:
            return {"ok": False, "checked": n, "broken_at_id": ev.id,
                    "reason": "prev_hash mismatch" if ev.prev_hash != prev else "content hash mismatch"}
        prev = ev.hash
        n += 1
        if anchor_count is not None and n == anchor_count:
            if ev.hash != anchor_head:
                return {"ok": False, "checked": n, "broken_at_id": ev.id, "reason": "anchor mismatch (history rewritten)"}
            anchored = True
        if limit and n >= limit:
            break
    if not anchored:
        return {"ok": False, "checked": n, "reason": f"chain is shorter than the anchor ({n} < {anchor_count}): events were removed"}
    return {"ok": True, "checked": n, "head": prev, "anchor_verified": anchor_count is not None}
