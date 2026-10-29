"""Leak dataset import: schema detection, validation preview, de-duplication. Source files are never modified."""
from __future__ import annotations

import hashlib
import io
import json
from datetime import datetime

import pandas as pd
from sqlalchemy.orm import Session

from app.core.errors import Unprocessable
from app.models import LeakDataset, LeakRecord, User
from app.services import audit
from app.services.textsim import normalize

FIELD_CANDIDATES = {
    "text": ["text", "content", "message", "body", "post_text", "transcript", "caption"],
    "external_id": ["post_id", "id", "message_id", "record_id"],
    "channel": ["channel", "source", "group", "platform_channel", "author_channel"],
    "channel_type": ["channel_type", "platform", "source_type", "medium"],
    "posted_at": ["posted_at", "timestamp", "date", "time", "created_at"],
}
MAX_TEXT = 20000


def parse_file(raw: bytes, filename: str) -> pd.DataFrame:
    name = filename.lower()
    try:
        if name.endswith(".jsonl") or name.endswith(".ndjson"):
            rows = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
            return pd.DataFrame(rows)
        if name.endswith(".json"):
            data = json.loads(raw.decode("utf-8"))
            if isinstance(data, dict):
                data = data.get("records") or data.get("data") or data.get("posts") or []
            return pd.DataFrame(data)
        if name.endswith(".csv"):
            return pd.read_csv(io.BytesIO(raw), dtype=str, keep_default_na=False)
    except (UnicodeDecodeError, json.JSONDecodeError, pd.errors.ParserError) as e:
        raise Unprocessable(f"Could not parse {filename}: {e.__class__.__name__}: {str(e)[:200]}")
    raise Unprocessable("Unsupported file type; use .csv, .json or .jsonl")


def detect_mapping(df: pd.DataFrame, override: dict | None = None) -> dict:
    cols = {c.lower(): c for c in df.columns}
    mapping = {}
    for field, cands in FIELD_CANDIDATES.items():
        for c in cands:
            if c in cols:
                mapping[field] = cols[c]
                break
    if override:
        mapping.update({k: v for k, v in override.items() if v})
    return mapping


def preview(raw: bytes, filename: str, mapping_override: dict | None = None) -> dict:
    df = parse_file(raw, filename)
    if df.empty:
        raise Unprocessable("Dataset is empty")
    mapping = detect_mapping(df, mapping_override)
    errors = []
    if "text" not in mapping or mapping["text"] not in df.columns:
        errors.append(f"No text column found; expected one of {FIELD_CANDIDATES['text']} (or provide a mapping)")
    info = {
        "file_name": filename, "sha256": hashlib.sha256(raw).hexdigest(), "n_rows": len(df),
        "columns": [{"name": c, "dtype": str(df[c].dtype),
                     "missing": int((df[c].isna() | (df[c].astype(str).str.strip() == "")).sum())} for c in df.columns],
        "mapping": mapping, "errors": errors,
    }
    if not errors:
        texts = df[mapping["text"]].astype(str).map(normalize)
        info["n_empty_text"] = int((texts == "").sum())
        info["n_duplicate_text"] = int(texts[texts != ""].duplicated().sum())
        if "posted_at" in mapping:
            parsed = pd.to_datetime(df[mapping["posted_at"]], errors="coerce", utc=True)
            info["n_bad_timestamps"] = int(parsed.isna().sum())
            if parsed.notna().any():
                info["time_range"] = [parsed.min().isoformat(), parsed.max().isoformat()]
        else:
            info["warnings"] = ["No timestamp column: detection timing cannot be related to slots."]
    info["sample"] = json.loads(df.head(5).to_json(orient="records", default_handler=str))
    return info


def import_dataset(db: Session, org_id: int, user: User | None, raw: bytes, filename: str, name: str,
                   source_type: str, description: str = "", mapping_override: dict | None = None,
                   is_synthetic: bool = False) -> LeakDataset:
    info = preview(raw, filename, mapping_override)
    if info["errors"]:
        raise Unprocessable("Dataset failed validation", info["errors"])
    df = parse_file(raw, filename)
    m = info["mapping"]
    ds = LeakDataset(org_id=org_id, name=name, source_type=source_type, description=description, file_name=filename,
                     file_sha256=info["sha256"], imported_by=user.id if user else None, n_records=0,
                     column_mapping=m, is_synthetic=is_synthetic)
    db.add(ds)
    db.flush()
    seen: set[str] = set()
    n_ok = n_rej = n_dup = 0
    for i, row in df.iterrows():
        text = str(row.get(m["text"], "") or "").strip()[:MAX_TEXT]
        norm = normalize(text)
        if not norm:
            n_rej += 1
            continue
        if norm in seen:
            n_dup += 1
            continue
        seen.add(norm)
        posted = None
        if "posted_at" in m and str(row.get(m["posted_at"], "")).strip():
            ts = pd.to_datetime(row[m["posted_at"]], errors="coerce", utc=True)
            posted = None if pd.isna(ts) else ts.tz_convert(None).to_pydatetime()
        meta = {k: (v if isinstance(v, (str, int, float, bool)) or v is None else str(v))
                for k, v in row.items() if k not in m.values()}
        db.add(LeakRecord(
            dataset_id=ds.id, external_id=str(row.get(m.get("external_id", ""), f"row-{i}")),
            channel=str(row.get(m.get("channel", ""), "unknown"))[:120],
            channel_type=str(row.get(m.get("channel_type", ""), "unspecified"))[:40],
            posted_at=posted, text=text, normalized_text=norm, meta=meta or None,
        ))
        n_ok += 1
    ds.n_records, ds.n_rejected, ds.n_duplicates = n_ok, n_rej, n_dup
    audit.record(db, user, "leaks.dataset_imported", "leak_dataset", ds.id,
                 f"Imported '{name}' ({n_ok} records, {n_rej} rejected, {n_dup} duplicates)",
                 {"sha256": info["sha256"], "file": filename})
    return ds


def _unused(_: datetime) -> None:  # keep datetime import for type hints in callers
    return None
