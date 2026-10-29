from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditEvent, User


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
    ev = AuditEvent(
        org_id=org_id or (actor.org_id if actor else 1),
        actor_id=actor.id if actor else None,
        actor_label=f"{actor.full_name} ({actor.role.label})" if actor else "system",
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        summary=summary[:400],
        details=details,
    )
    db.add(ev)
    return ev
