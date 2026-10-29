"""Import pipelines for response logs and item banks (CSV / JSON / JSONL).

The same code path ingests the deterministic synthetic demo data and any official dataset, so
schema validation, duplicate handling and key-consistency checks are exercised by the demo itself.
"""
from __future__ import annotations

import io
import json
from datetime import datetime

import numpy as np
import pandas as pd
from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from app.core.errors import Unprocessable
from app.models import (
    AnswerOption,
    Attempt,
    Candidate,
    ExposureEvent,
    FormItem,
    Question,
    Response,
    Slot,
    TestForm,
    User,
)
from app.services import audit

RESPONSE_REQUIRED = ["slot_code", "form_code", "candidate_ref", "item_code", "selected_option"]
RESPONSE_OPTIONAL = ["drive", "slot_sequence", "slot_start", "is_correct", "response_time_ms", "position", "submitted_at"]


def read_table(raw: bytes, filename: str) -> pd.DataFrame:
    name = filename.lower()
    try:
        if name.endswith(".csv"):
            return pd.read_csv(io.BytesIO(raw), dtype=str, keep_default_na=False)
        if name.endswith((".jsonl", ".ndjson")):
            return pd.DataFrame([json.loads(x) for x in raw.decode().splitlines() if x.strip()])
        if name.endswith(".json"):
            data = json.loads(raw.decode())
            return pd.DataFrame(data if isinstance(data, list) else data.get("records", []))
    except (UnicodeDecodeError, json.JSONDecodeError, pd.errors.ParserError) as e:
        raise Unprocessable(f"Could not parse {filename}: {e.__class__.__name__}")
    raise Unprocessable("Unsupported file type; use .csv, .json or .jsonl")


def validate_response_frame(df: pd.DataFrame, known_items: set[str]) -> dict:
    report: dict = {"n_rows": len(df), "columns": list(df.columns), "errors": [], "warnings": []}
    if df.empty:
        report["errors"].append("Dataset is empty")
        return report
    missing = [c for c in RESPONSE_REQUIRED if c not in df.columns]
    if missing:
        report["errors"].append(f"Missing required column(s): {missing}")
        return report
    for c in RESPONSE_REQUIRED[:-1]:
        n = int((df[c].astype(str).str.strip() == "").sum())
        if n:
            report["errors"].append(f"{n} row(s) with empty '{c}'")
    sel = df["selected_option"].astype(str).str.strip().str.upper()
    bad = ~sel.isin(["", "A", "B", "C", "D", "NAN", "NONE"])
    if bad.any():
        report["errors"].append(f"{int(bad.sum())} row(s) with invalid selected_option (expected A–D or blank)")
    report["n_omitted"] = int(sel.isin(["", "NAN", "NONE"]).sum())
    unknown = set(df["item_code"].astype(str)) - known_items
    if unknown:
        report["errors"].append(f"{len(unknown)} item code(s) not in the bank, e.g. {sorted(unknown)[:5]}")
    dup = df.duplicated(subset=["candidate_ref", "form_code", "item_code"]).sum()
    if dup:
        report["errors"].append(f"{int(dup)} duplicate (candidate, form, item) rows")
    if "response_time_ms" not in df.columns:
        report["warnings"].append("No response_time_ms column: response-time leak signals will be unavailable")
    report["n_candidates"] = int(df["candidate_ref"].nunique())
    report["n_items"] = int(df["item_code"].nunique())
    report["n_slots"] = int(df["slot_code"].nunique())
    return report


def import_response_log(db: Session, org_id: int, user: User | None, df: pd.DataFrame, source_label: str,
                        is_synthetic: bool) -> dict:
    qrows = db.execute(select(Question.code, Question.id).where(Question.org_id == org_id)).all()
    code_to_id = {c: i for c, i in qrows}
    report = validate_response_frame(df, set(code_to_id))
    if report["errors"]:
        raise Unprocessable("Response log failed validation", report)
    df = df.copy()
    df["selected_option"] = df["selected_option"].astype(str).str.strip().str.upper().replace({"": None, "NAN": None, "NONE": None})
    df["qid"] = df["item_code"].map(code_to_id)
    keys = dict(db.execute(select(AnswerOption.question_id, AnswerOption.key).where(AnswerOption.is_correct.is_(True))).all())
    df["computed_correct"] = [(s is not None and s == keys.get(q)) for s, q in zip(df["selected_option"], df["qid"])]
    if "is_correct" in df.columns:
        supplied = df["is_correct"].astype(str).str.strip().isin(["1", "true", "True", "TRUE"])
        answered = df["selected_option"].notna()
        mism = int((supplied[answered] != df.loc[answered, "computed_correct"]).sum())
        report["key_mismatches"] = mism
        if mism:
            report["warnings"].append(f"{mism} row(s) where supplied is_correct disagrees with the bank's answer key; "
                                      "the bank key is used")
    # slots
    slots = {s.code: s for s in db.scalars(select(Slot).where(Slot.org_id == org_id)).all()}
    for code, g in df.groupby("slot_code"):
        if code in slots:
            continue
        start = pd.to_datetime(g["slot_start"].iloc[0]).to_pydatetime().replace(tzinfo=None) if "slot_start" in g else datetime(2026, 1, 1)
        seq = int(g["slot_sequence"].iloc[0]) if "slot_sequence" in g else len(slots) + 1
        drive = str(g["drive"].iloc[0]) if "drive" in g else source_label
        s = Slot(org_id=org_id, code=code, drive=drive, sequence=seq, name=f"{drive} · Slot {seq}", starts_at=start,
                 ends_at=start + pd.Timedelta(hours=1), status="completed", is_synthetic=is_synthetic)
        db.add(s)
        slots[code] = s
    db.flush()
    # forms + manifests
    forms = {f.code: f for f in db.scalars(select(TestForm)).all()}
    for code, g in df.groupby("form_code"):
        if code in forms:
            continue
        slot = slots[g["slot_code"].iloc[0]]
        first = g[g["candidate_ref"] == g["candidate_ref"].iloc[0]]
        if "position" in first:
            first = first.assign(_p=first["position"].astype(int)).sort_values("_p")
        sec = dict(db.execute(select(Question.id, Question.section_id).where(Question.id.in_(first["qid"].tolist()))).all())
        f = TestForm(code=code, slot_id=slot.id, status="historical", duration_minutes=40, is_synthetic=is_synthetic,
                     validation={"status": "imported", "source": source_label})
        f.items = [FormItem(question_id=int(q), section_id=sec[int(q)], position=k) for k, q in enumerate(first["qid"])]
        db.add(f)
        forms[code] = f
    db.flush()
    # candidates
    cands = {c.code: c.id for c in db.scalars(select(Candidate).where(Candidate.org_id == org_id)).all()}
    new_c = [{"org_id": org_id, "code": c, "display_name": f"Candidate {c[-5:]}", "is_synthetic": is_synthetic}
             for c in df["candidate_ref"].unique() if c not in cands]
    if new_c:
        db.execute(insert(Candidate), new_c)
        cands = {c.code: c.id for c in db.scalars(select(Candidate).where(Candidate.org_id == org_id)).all()}
    # attempts
    att_rows = []
    groups = df.groupby(["candidate_ref", "form_code"], sort=False)
    for (cref, fcode), g in groups:
        f = forms[fcode]
        sub = pd.to_datetime(g["submitted_at"].iloc[0]).to_pydatetime().replace(tzinfo=None) if "submitted_at" in g else f.slot.ends_at
        att_rows.append({"candidate_id": cands[cref], "form_id": f.id, "slot_id": f.slot_id, "status": "submitted",
                         "started_at": f.slot.starts_at, "deadline_at": f.slot.starts_at + pd.Timedelta(minutes=f.duration_minutes),
                         "submitted_at": sub, "score": float(g["computed_correct"].sum()), "max_score": float(len(g)),
                         "is_synthetic": is_synthetic})
    db.execute(insert(Attempt), att_rows)
    att = {(a.candidate_id, a.form_id): a.id for a in db.scalars(select(Attempt)).all()}
    rt = pd.to_numeric(df["response_time_ms"], errors="coerce") if "response_time_ms" in df else pd.Series(np.nan, index=df.index)
    resp = [{"attempt_id": att[(cands[c], forms[f].id)], "question_id": int(q), "selected_key": s,
             "is_correct": bool(ok), "response_time_ms": None if pd.isna(t) else int(t),
             "answered_at": forms[f].slot.starts_at}
            for c, f, q, s, ok, t in zip(df["candidate_ref"], df["form_code"], df["qid"], df["selected_option"],
                                         df["computed_correct"], rt)]
    for i in range(0, len(resp), 5000):
        db.execute(insert(Response), resp[i:i + 5000])
    # exposure events per (form, item)
    exp = df.groupby(["form_code", "qid"])["candidate_ref"].nunique().reset_index()
    db.execute(insert(ExposureEvent), [
        {"question_id": int(q), "slot_id": forms[f].slot_id, "form_id": forms[f].id, "event_type": "administered",
         "candidate_count": int(n), "occurred_at": forms[f].slot.starts_at} for f, q, n in exp.itertuples(index=False)])
    report.update({"attempts_created": len(att_rows), "responses_created": len(resp), "forms": len(df["form_code"].unique())})
    audit.record(db, user, "calibration.responses_imported", "dataset", source_label,
                 f"Imported {len(resp)} responses / {len(att_rows)} attempts from {source_label}", {"report": {k: v for k, v in report.items() if k != 'columns'}},
                 org_id=org_id)
    return report


ITEM_REQUIRED = ["item_code", "section", "stem", "option_a", "option_b", "option_c", "option_d", "correct_option"]


def validate_item_frame(df: pd.DataFrame) -> dict:
    rep = {"n_rows": len(df), "errors": [], "warnings": []}
    if df.empty:
        rep["errors"].append("Dataset is empty")
        return rep
    miss = [c for c in ITEM_REQUIRED if c not in df.columns]
    if miss:
        rep["errors"].append(f"Missing required column(s): {miss}")
        return rep
    bad_sec = ~df["section"].astype(str).str.upper().isin(["QUANT", "LOGICAL", "VERBAL"])
    if bad_sec.any():
        rep["errors"].append(f"{int(bad_sec.sum())} row(s) with unknown section")
    bad_key = ~df["correct_option"].astype(str).str.upper().isin(["A", "B", "C", "D"])
    if bad_key.any():
        rep["errors"].append(f"{int(bad_key.sum())} row(s) with invalid correct_option")
    if df["item_code"].duplicated().any():
        rep["errors"].append(f"{int(df['item_code'].duplicated().sum())} duplicate item_code(s)")
    return rep


def import_item_bank(db: Session, org_id: int, user: User | None, df: pd.DataFrame, source_label: str,
                     status: str = "pending_review", is_synthetic: bool = False) -> dict:
    """Import an item bank. Each row is validated (schema, single key, distinct options, duplicates); rows that
    fail critical checks are rejected with reasons and never stored. Optional columns: difficulty, skill, concept,
    family_code, parent_code (variant of), explanation. `status` defaults to pending_review (human approval)."""
    from app.models import AnswerOption, Section, VariantFamily
    from app.services.generation.base import GeneratedItem
    from app.services.generation.registry import DIFFICULTY_B
    from app.services.questions import add_revision, bank_entries, persist_checks
    from app.services.textsim import item_fulltext, normalize, text_hash
    from app.services.validation.validator import BankEntry, validate

    if status not in ("pending_review", "approved"):
        raise Unprocessable("status must be pending_review or approved")
    rep = validate_item_frame(df)
    if rep["errors"]:
        raise Unprocessable("Item bank failed validation", rep)
    sections = {s.code: s for s in db.scalars(select(Section)).all()}
    existing = set(db.scalars(select(Question.code)).all())
    bank = bank_entries(db, org_id)
    families: dict[str, VariantFamily] = {f.code: f for f in db.scalars(select(VariantFamily).where(VariantFamily.org_id == org_id)).all()}
    imported, rejected, held = [], [], []
    rows = df.to_dict("records")
    rows.sort(key=lambda r: bool(str(r.get("parent_code") or "").strip()))  # sources before their variants
    code_to_q: dict[str, Question] = {}
    for r in rows:
        code = str(r["item_code"]).strip()
        if code in existing:
            rejected.append({"item_code": code, "reasons": ["item_code already exists"]})
            continue
        sec = str(r["section"]).strip().upper()
        diff = str(r.get("difficulty") or "medium").strip().lower()
        if diff not in DIFFICULTY_B:
            rejected.append({"item_code": code, "reasons": [f"unknown difficulty '{diff}'"]})
            continue
        key = str(r["correct_option"]).strip().upper()
        opts = [{"key": k, "text": str(r[f"option_{k.lower()}"]).strip(), "is_correct": k == key, "rationale": None} for k in "ABCD"]
        item = GeneratedItem(sec, "", str(r.get("concept") or r.get("skill") or sec.title()), str(r.get("skill") or "unspecified"),
                             diff, str(r["stem"]).strip(), opts, str(r.get("explanation") or "").strip() or "Explanation not supplied.", {})
        status_v, checks = validate(item, bank, "imported")
        crit = [c for c in checks if c.status == "fail" and c.severity == "critical"]
        dup = [c for c in crit if c.check.startswith("duplicate")]
        structural = [c.message for c in crit if not c.check.startswith("duplicate")]
        if structural:
            rejected.append({"item_code": code, "reasons": structural})
            continue
        # An existing bank's items were administered: never drop them for being similar. Import, but hold them out of
        # assembly (pending_review) until a human resolves the duplication.
        item_status, item_reason = status, None
        if dup:
            item_status, item_reason = "pending_review", "Imported but held for review: " + "; ".join(c.message for c in dup)[:280]
            held.append({"item_code": code, "reasons": [c.message for c in dup]})
        fam_code = str(r.get("family_code") or "").strip() or f"FAM-{code}"
        fam = families.get(fam_code)
        if fam is None:
            fam = VariantFamily(code=fam_code, org_id=org_id, section_id=sections[sec].id, concept=item.concept, skill=item.skill)
            db.add(fam)
            db.flush()
            families[fam_code] = fam
        parent_code = str(r.get("parent_code") or "").strip()
        parent = code_to_q.get(parent_code) or (db.scalar(select(Question).where(Question.code == parent_code)) if parent_code else None)
        q = Question(code=code, org_id=org_id, section_id=sections[sec].id, family_id=fam.id, parent_id=parent.id if parent else None,
                     is_source=parent is None, skill=item.skill, tags=[], stem=item.stem, explanation=item.explanation,
                     difficulty_target=diff, difficulty_target_b=DIFFICULTY_B[diff], status=item_status, status_reason=item_reason,
                     generation_method="imported",
                     normalized_hash=text_hash(item_fulltext(item.stem, [o["text"] for o in opts])), validation_status=status_v,
                     data_source=f"imported:{source_label}"[:60], is_synthetic=is_synthetic, created_by=user.id if user else None)
        q.options = [AnswerOption(key=o["key"], text=o["text"], is_correct=o["is_correct"], position=i) for i, o in enumerate(opts)]
        db.add(q)
        db.flush()
        if fam.source_question_id is None and parent is None:
            fam.source_question_id = q.id
        persist_checks(db, q, checks)
        add_revision(db, q, "created", user, f"Imported from {source_label}")
        bank.append(BankEntry(q.id, code, normalize(item_fulltext(q.stem, [o["text"] for o in opts])), q.normalized_hash, None, None))
        code_to_q[code] = q
        existing.add(code)
        imported.append(code)
    audit.record(db, user, "questions.bank_imported", "dataset", source_label,
                 f"Item bank '{source_label}': {len(imported)} imported ({len(held)} held for duplicate review), {len(rejected)} rejected",
                 {"rejected": rejected[:50], "held": held[:50]}, org_id=org_id)
    return {"rows": len(rows), "imported": len(imported), "held_for_duplicate_review": len(held), "rejected": len(rejected),
            "rejections": rejected, "held": held}
