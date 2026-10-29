"""Reset the local database to the deterministic SYNTHETIC demo state (seed 107).

Usage (from repo root):  backend/.venv/bin/python scripts/seed_demo.py
Runs Alembic migrations first, then the full demo pipeline (bank → responses → calibration → leak import →
leak detection → next-drive assembly). Safe to re-run; it wipes and recreates demo data.
"""
import json
import subprocess
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

from app.core.config import get_settings  # noqa: E402


def main() -> None:
    url = get_settings().database_url
    if url.startswith("sqlite:///"):
        Path(url.replace("sqlite:///", "")).parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND, check=True)
    from app.db.session import SessionLocal
    from app.demo.seed import seed_demo

    t0 = time.perf_counter()
    with SessionLocal() as db:
        out = seed_demo(db)
    out = {k: v for k, v in out.items() if not k.startswith("_") and k != "check"}
    print(json.dumps(out, indent=2, default=str))
    print(f"Seeded in {time.perf_counter() - t0:.1f}s")


if __name__ == "__main__":
    main()
