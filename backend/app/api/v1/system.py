"""Health, readiness, version, demo status, settings, audit, global search and notifications."""
from __future__ import annotations

import time
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session

from app.core.config import APP_VERSION, get_settings
from app.core.deps import get_current_user, require, user_permissions
from app.core.errors import NotFound, Unprocessable
from app.db.session import get_db
from app.models import AuditEvent, LeakAlert, Question, TestForm, User
from app.services import audit
from app.services.policies import DEFAULT_POLICIES, all_policies, set_policy

router = APIRouter(tags=["system"])
STARTED = time.time()


@router.get("/health")
def health():
    return {"status": "ok", "uptime_s": int(time.time() - STARTED)}


@router.get("/ready")
def ready(db: Session = Depends(get_db)):
    t0 = time.perf_counter()
    db.execute(text("SELECT 1"))
    rev = None
    try:
        rev = db.execute(text("SELECT version_num FROM alembic_version")).scalar()
    except Exception:  # noqa: BLE001 - migrations table missing means not ready
        return {"status": "not_ready", "reason": "database not migrated"}
    n = db.scalar(select(func.count()).select_from(Question))
    return {"status": "ready", "db_latency_ms": round((time.perf_counter() - t0) * 1000, 2), "migration": rev,
            "questions": n}


@router.get("/version")
def version():
    s = get_settings()
    return {"name": "AptiGuard AI", "version": APP_VERSION, "env": s.app_env, "api": "v1"}


@router.get("/demo-status")
def demo_status(db: Session = Depends(get_db)):
    s = get_settings()
    out = {"demo_mode": s.demo_mode, "seeded": bool(db.scalar(select(func.count()).select_from(Question))),
           "llm": {"provider": s.llm_provider, "configured": s.llm_configured}}
    if s.demo_mode:
        out["demo_accounts"] = [
            {"email": e, "role": r} for e, r in [("admin@aptiguard.demo", "Administrator"), ("designer@aptiguard.demo", "Assessment Designer"),
                                                 ("reviewer@aptiguard.demo", "Reviewer"), ("analyst@aptiguard.demo", "Psychometric Analyst"),
                                                 ("candidate1@aptiguard.demo", "Candidate")]]
        out["demo_password_hint"] = "See README → Demo accounts (local demo only)"
    return out


# ------------------------------------------------------------------ settings & audit
class PolicyPut(BaseModel):
    values: dict


@router.get("/settings")
def get_settings_view(user: User = Depends(require("dashboard.read")), db: Session = Depends(get_db)):
    s = get_settings()
    return {
        "policies": all_policies(db, user.org_id),
        "defaults": DEFAULT_POLICIES,
        "model_provider": {"provider": s.llm_provider, "configured": s.llm_configured, "model": s.llm_model,
                           "api_key": "set (hidden)" if s.llm_api_key else "not set",
                           "fallback": "Deterministic, verifiable templates (always available)"},
        "security": {"auth": "JWT (HS256) bearer tokens — prototype; use an OIDC provider in production",
                     "insecure_dev_secret": s.using_insecure_secret, "cors_origins": s.cors_origin_list,
                     "max_upload_mb": s.max_upload_mb, "demo_mode": s.demo_mode},
        "database": s.database_url.split(":")[0],
        "can_manage": "settings.manage" in user_permissions(user),
    }


@router.put("/settings/policies/{key}")
def put_policy(key: str, body: PolicyPut, user: User = Depends(require("settings.manage")), db: Session = Depends(get_db)):
    if key not in DEFAULT_POLICIES:
        raise NotFound("Unknown policy")
    for k, v in body.values.items():
        default = DEFAULT_POLICIES[key].get(k)
        if default is not None and type(default) is not type(v) and not (isinstance(default, float) and isinstance(v, int)):
            raise Unprocessable(f"Field '{k}' must be of type {type(default).__name__}")
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v < 0:
            raise Unprocessable(f"Field '{k}' must be non-negative")
    try:
        out = set_policy(db, user.org_id, key, body.values, user.id)
    except ValueError as e:
        raise Unprocessable(str(e))
    audit.record(db, user, "settings.policy_updated", "policy", key, f"Policy '{key}' updated", body.values)
    db.commit()
    return out


@router.get("/audit")
def audit_log(action: str | None = None, entity_type: str | None = None, q: str | None = None,
              date_from: datetime | None = None, date_to: datetime | None = None, page: int = Query(1, ge=1),
              page_size: int = Query(50, ge=1, le=200), user: User = Depends(require("audit.read")), db: Session = Depends(get_db)):
    stmt = select(AuditEvent).where(AuditEvent.org_id == user.org_id)
    if action:
        stmt = stmt.where(AuditEvent.action.ilike(f"{action}%"))
    if entity_type:
        stmt = stmt.where(AuditEvent.entity_type == entity_type)
    if q:
        stmt = stmt.where(or_(AuditEvent.summary.ilike(f"%{q}%"), AuditEvent.actor_label.ilike(f"%{q}%")))
    if date_from:
        stmt = stmt.where(AuditEvent.created_at >= date_from)
    if date_to:
        stmt = stmt.where(AuditEvent.created_at <= date_to)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(AuditEvent.id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    actions = sorted({a.split(".")[0] for a in db.scalars(select(AuditEvent.action).distinct()).all()})
    return {"total": total, "page": page, "page_size": page_size, "action_groups": actions,
            "items": [{"id": e.id, "at": e.created_at, "actor": e.actor_label, "action": e.action, "entity_type": e.entity_type,
                       "entity_id": e.entity_id, "summary": e.summary, "details": e.details} for e in rows]}


@router.post("/system/demo/reset")
def demo_reset(user: User = Depends(require("demo.reset")), db: Session = Depends(get_db)):
    if not get_settings().demo_mode:
        raise Unprocessable("Demo reset is disabled outside demo mode")
    from app.demo.seed import seed_demo

    t0 = time.perf_counter()
    out = seed_demo(db)
    return {"status": "reset", "seconds": round(time.perf_counter() - t0, 1), "responses": out["responses"],
            "leak_alerts": out["leak_run"]}


# ------------------------------------------------------------------ search & notifications
@router.get("/search")
def search(q: str = Query(min_length=2, max_length=100), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    perms = user_permissions(user)
    out = []
    like = f"%{q}%"
    if "questions.read" in perms:
        for x in db.scalars(select(Question).where(Question.org_id == user.org_id, or_(Question.code.ilike(like),
                                                                                       Question.stem.ilike(like))).limit(8)).all():
            out.append({"type": "question", "id": x.id, "label": x.code, "detail": x.stem[:90], "status": x.status})
    if "leaks.read" in perms:
        for a in db.scalars(select(LeakAlert).where(LeakAlert.org_id == user.org_id, or_(LeakAlert.code.ilike(like),
                                                                                         LeakAlert.title.ilike(like))).limit(5)).all():
            out.append({"type": "alert", "id": a.id, "label": a.code, "detail": a.title, "status": a.status})
    if "assembly.read" in perms:
        for f in db.scalars(select(TestForm).where(TestForm.code.ilike(like)).limit(5)).all():
            out.append({"type": "form", "id": f.id, "label": f.code, "detail": f.slot.name, "status": f.status,
                        "run_id": f.assembly_run_id})
    return {"results": out}


@router.get("/notifications")
def notifications(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    perms = user_permissions(user)
    items = []
    if "leaks.read" in perms:
        for a in db.scalars(select(LeakAlert).where(LeakAlert.org_id == user.org_id, LeakAlert.status == "open",
                                                    LeakAlert.severity.in_(("critical", "high")))
                            .order_by(LeakAlert.detected_at.desc()).limit(8)).all():
            items.append({"kind": "alert", "severity": a.severity, "title": f"{a.code} · {a.severity.upper()}", "body": a.title,
                          "at": a.detected_at, "link": f"/leaks?alert={a.id}"})
    if "review.decide" in perms or "questions.write" in perms:
        n = db.scalar(select(func.count()).select_from(Question).where(Question.org_id == user.org_id,
                                                                       Question.status == "pending_review"))
        if n:
            items.append({"kind": "review", "severity": "info", "title": f"{n} item(s) awaiting review",
                          "body": "Generated variants need an independent human decision before use.", "at": None,
                          "link": "/review"})
    return {"items": items, "unread": len(items)}
