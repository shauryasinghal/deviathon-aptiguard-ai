"""Test configuration: an isolated, freshly migrated and seeded SQLite database per test session."""
import os
import sys
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="aptiguard-test-")
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP}/test.db"
os.environ["APP_ENV"] = "test"
os.environ["LOG_LEVEL"] = "WARNING"
os.environ["LLM_PROVIDER"] = "none"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

DEMO_PASSWORD = "AptiGuard-Demo-2026"


@pytest.fixture(scope="session")
def seeded():
    from alembic import command
    from alembic.config import Config

    backend = Path(__file__).resolve().parents[1]
    cfg = Config(str(backend / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend / "alembic"))
    command.upgrade(cfg, "head")
    from app.db.session import SessionLocal
    from app.demo.seed import seed_demo

    with SessionLocal() as db:
        out = seed_demo(db)
    return out


@pytest.fixture(scope="session")
def client(seeded):
    from fastapi.testclient import TestClient

    from app.main import app

    return TestClient(app)


@pytest.fixture(scope="session")
def auth(client):
    cache = {}

    def _h(role: str) -> dict:
        if role not in cache:
            email = "candidate1" if role == "candidate" else role
            r = client.post("/api/v1/auth/login", json={"email": f"{email}@aptiguard.demo", "password": DEMO_PASSWORD})
            assert r.status_code == 200, r.text
            cache[role] = {"Authorization": f"Bearer {r.json()['access_token']}"}
        return cache[role]

    return _h


@pytest.fixture()
def db(seeded):
    from app.db.session import SessionLocal

    with SessionLocal() as s:
        yield s
