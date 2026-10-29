from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.serializers import user_label
from app.core.deps import require
from app.core.errors import Conflict, NotFound
from app.db.session import get_db
from app.models import AssemblyRun, Question, TestForm, User
from app.services.assembly.algorithm import AssemblyConfig, preflight
from app.services.assembly.service import DEFAULT_MIX, build_pool, preview, publish_run, run_assembly
from app.services.exposure.service import exposure_stats

router = APIRouter(prefix="/assembly", tags=["test assembly"])
SECTIONS = ("QUANT", "LOGICAL", "VERBAL")


class Mix(BaseModel):
    easy: float = Field(ge=0, le=1)
    medium: float = Field(ge=0, le=1)
    hard: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def _sum(self):
        if abs(self.easy + self.medium + self.hard - 1) > 0.011:
            raise ValueError("difficulty proportions must sum to 1")
        return self


class AssembleIn(BaseModel):
    drive: str = Field(min_length=3, max_length=80)
    n_slots: int = Field(ge=1, le=30)
    forms_per_slot: int = Field(default=1, ge=1, le=4)
    per_section: dict[str, int]
    section_weights: dict[str, float] | None = None
    difficulty_mix: dict[str, Mix] | None = None
    max_adjacent_overlap_pct: float = Field(ge=0, le=100)
    max_slot_exposures: int = Field(ge=1, le=50)
    min_slot_spacing: int = Field(ge=0, le=20)
    separate_families_adjacent: bool = True
    seed: int = Field(ge=0, le=2**31)
    start_date: datetime | None = None
    duration_minutes: int = Field(default=40, ge=5, le=240)

    @field_validator("per_section")
    @classmethod
    def _sections(cls, v):
        if not v or any(k not in SECTIONS for k in v) or any(n < 0 or n > 60 for n in v.values()) or sum(v.values()) == 0:
            raise ValueError("per_section must map QUANT/LOGICAL/VERBAL to 0–60 items with at least one item")
        return {k: n for k, n in v.items() if n > 0}

    def as_cfg(self) -> dict:
        d = self.model_dump()
        d["difficulty_mix"] = {k: v.model_dump() for k, v in (self.difficulty_mix or {}).items()}
        d["start_date"] = self.start_date.replace(tzinfo=None).isoformat() if self.start_date else None
        return d


def _run_dict(db: Session, r: AssemblyRun, with_forms: bool = False) -> dict:
    d = {"id": r.id, "drive": r.drive, "seed": r.seed, "status": r.status, "config": r.config, "diagnostics": r.diagnostics,
         "overlap": r.overlap, "duration_ms": r.duration_ms, "created_at": r.created_at, "created_by": user_label(db, r.created_by)}
    forms = db.scalars(select(TestForm).where(TestForm.assembly_run_id == r.id).order_by(TestForm.id)).all()
    d["form_count"] = len(forms)
    d["published"] = sum(1 for f in forms if f.status == "published")
    if with_forms:
        d["forms"] = [_form_dict(db, f, manifest=True) for f in forms]
    return d


def _form_dict(db: Session, f: TestForm, manifest: bool = False) -> dict:
    d = {"id": f.id, "code": f.code, "status": f.status, "slot": {"id": f.slot.id, "code": f.slot.code, "name": f.slot.name,
         "sequence": f.slot.sequence, "starts_at": f.slot.starts_at, "drive": f.slot.drive}, "seed": f.seed,
         "duration_minutes": f.duration_minutes, "n_items": len(f.items), "validation": f.validation}
    if manifest:
        stats = exposure_stats(db, f.slot.org_id, [i.question_id for i in f.items])
        items = []
        for fi in f.items:
            q = db.get(Question, fi.question_id)
            items.append({"position": fi.position + 1, "question_id": q.id, "code": q.code, "family_code": q.family.code,
                          "variant_of": db.get(Question, q.parent_id).code if q.parent_id else None, "section": q.section.code,
                          "difficulty": q.difficulty_target, "status": q.status, "leak_status": q.leak_status,
                          "exposure_slots": stats[q.id].slot_count if q.id in stats else 0})
        d["items"] = items
    return d


@router.get("/preview")
def get_preview(n_slots: int = 10, quant: int = 10, logical: int = 10, verbal: int = 10,
                user: User = Depends(require("assembly.read")), db: Session = Depends(get_db)):
    return preview(db, user.org_id, {"QUANT": quant, "LOGICAL": logical, "VERBAL": verbal}, n_slots)


@router.post("/validate")
def validate(body: AssembleIn, user: User = Depends(require("assembly.read")), db: Session = Depends(get_db)):
    pool, excluded, _ = build_pool(db, user.org_id, {"max_slot_exposures": body.max_slot_exposures})
    mix = {k: v.model_dump() for k, v in (body.difficulty_mix or {}).items()}
    cfg = AssemblyConfig(body.n_slots, body.per_section, {s: mix.get(s, DEFAULT_MIX) for s in body.per_section},
                         body.max_adjacent_overlap_pct, body.max_slot_exposures, body.min_slot_spacing,
                         body.separate_families_adjacent, body.forms_per_slot, body.seed)
    issues = preflight(pool, cfg)
    form_size = sum(body.per_section.values())
    return {"feasible_preflight": not issues, "issues": issues, "eligible_pool": len(pool), "excluded": excluded,
            "form_size": form_size, "allowed_shared_items_adjacent": int(form_size * body.max_adjacent_overlap_pct / 100 + 1e-9)}


@router.post("/runs", status_code=201)
def create_run(body: AssembleIn, user: User = Depends(require("assembly.run")), db: Session = Depends(get_db)):
    r = run_assembly(db, user.org_id, user, body.as_cfg())
    db.commit()
    return _run_dict(db, r, with_forms=True)


@router.get("/runs")
def list_runs(user: User = Depends(require("assembly.read")), db: Session = Depends(get_db)):
    rows = db.scalars(select(AssemblyRun).where(AssemblyRun.org_id == user.org_id).order_by(AssemblyRun.id.desc()).limit(30)).all()
    return [_run_dict(db, r) for r in rows]


@router.get("/runs/{run_id}")
def get_run(run_id: int, user: User = Depends(require("assembly.read")), db: Session = Depends(get_db)):
    r = db.get(AssemblyRun, run_id)
    if not r or r.org_id != user.org_id:
        raise NotFound("Assembly run not found")
    return _run_dict(db, r, with_forms=True)


@router.post("/runs/{run_id}/publish")
def publish(run_id: int, user: User = Depends(require("assembly.run")), db: Session = Depends(get_db)):
    r = db.get(AssemblyRun, run_id)
    if not r or r.org_id != user.org_id:
        raise NotFound("Assembly run not found")
    if r.status != "succeeded":
        raise Conflict("Only a verified (succeeded) assembly run can be published")
    n = publish_run(db, r, user)
    db.commit()
    return {"published": n}


@router.get("/forms/{form_id}")
def form_manifest(form_id: int, user: User = Depends(require("assembly.read")), db: Session = Depends(get_db)):
    f = db.get(TestForm, form_id)
    if not f or f.slot.org_id != user.org_id:
        raise NotFound("Form not found")
    return _form_dict(db, f, manifest=True)
