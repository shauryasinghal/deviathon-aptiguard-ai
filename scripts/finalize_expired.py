"""Finalise (score and close) attempts whose deadline has passed. Safe to run repeatedly and alongside the API.

    backend/.venv/bin/python scripts/finalize_expired.py

The API also does this itself every EXPIRY_SWEEP_SECONDS (default 60; 0 disables) and whenever the attempt is touched.
Use this script from cron/systemd or a one-shot container if you run the API with the sweeper disabled.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
if Path("/srv/backend").exists():  # inside the container image
    sys.path.insert(0, "/srv/backend")

from app.db.session import SessionLocal  # noqa: E402
from app.services.assessment import finalize_expired  # noqa: E402


def main() -> int:
    total = 0
    with SessionLocal() as db:
        while True:
            n = finalize_expired(db)
            total += n
            if n == 0:
                break
    print(f"Finalised {total} expired attempt(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
