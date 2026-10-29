from __future__ import annotations

from fastapi import UploadFile

from app.core.config import get_settings
from app.core.errors import AppError, Unprocessable

ALLOWED = (".csv", ".json", ".jsonl", ".ndjson")


async def read_upload(file: UploadFile) -> tuple[bytes, str]:
    """Read an upload with a hard size cap and extension allow-list. Files are processed in memory only."""
    name = (file.filename or "").rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    if not name.lower().endswith(ALLOWED):
        raise Unprocessable(f"Unsupported file type; allowed: {', '.join(ALLOWED)}")
    limit = get_settings().max_upload_mb * 1024 * 1024
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise AppError(f"File exceeds {get_settings().max_upload_mb} MB limit", status_code=413, code="payload_too_large")
    if not data.strip():
        raise Unprocessable("Uploaded file is empty")
    return data, name
