from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core.deps import require
from app.core.errors import NotFound
from app.db.session import get_db
from app.models import User
from app.services import audit
from app.services.reporting.reports import TEMPLATES, build, to_csv, to_json, to_pdf

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/templates")
def templates(user: User = Depends(require("reports.read"))):
    return [{"id": k, "title": t, "description": d, "formats": ["csv", "json", "pdf"]} for k, (t, d) in TEMPLATES.items()]


@router.get("/{kind}/preview")
def preview(kind: str, section: str | None = None, slot: int | None = None, severity: str | None = None,
            status: str | None = None, date_from: datetime | None = None, date_to: datetime | None = None,
            user: User = Depends(require("reports.read")), db: Session = Depends(get_db)):
    if kind not in TEMPLATES:
        raise NotFound("Unknown report")
    rep = build(db, user.org_id, kind, section, slot, severity, status, date_from, date_to)
    return {"title": rep.title, "generated_at": rep.generated_at, "columns": rep.columns, "rows": rep.rows[:50],
            "total_rows": len(rep.rows), "warnings": rep.warnings, "provenance": rep.provenance, "filters": rep.filters}


@router.get("/{kind}.{fmt}")
def download(kind: str, fmt: Literal["csv", "json", "pdf"], section: str | None = None, slot: int | None = None,
             severity: str | None = None, status: str | None = None, date_from: datetime | None = None,
             date_to: datetime | None = None, user: User = Depends(require("reports.read")), db: Session = Depends(get_db)):
    if kind not in TEMPLATES:
        raise NotFound("Unknown report")
    rep = build(db, user.org_id, kind, section, slot, severity, status, date_from, date_to)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    name = f"aptiguard-{kind}-{stamp}.{fmt}"
    audit.record(db, user, "reports.downloaded", "report", kind, f"Downloaded {rep.title} ({fmt}, {len(rep.rows)} rows)")
    db.commit()
    if fmt == "csv":
        body, media = to_csv(rep).encode("utf-8-sig"), "text/csv; charset=utf-8"
    elif fmt == "json":
        body, media = to_json(rep).encode(), "application/json"
    else:
        body, media = to_pdf(rep), "application/pdf"
    return Response(body, media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}"',
                                                     "Cache-Control": "no-store"})
