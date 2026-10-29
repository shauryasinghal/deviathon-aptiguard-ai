"""Test configuration: an isolated, freshly migrated and seeded SQLite database per test session."""
import os
import sys
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="aptiguard-test-")
# Default: a throw-away SQLite file. Set TEST_DATABASE_URL to run the same suite against another engine
# (e.g. PostgreSQL); the database name must end in "_test" because its schema is dropped and rebuilt.
_TEST_URL = os.environ.get("TEST_DATABASE_URL")
if _TEST_URL:
    _dbname = _TEST_URL.rsplit("/", 1)[-1].split("?")[0]
    if not _dbname.endswith("_test"):
        raise SystemExit(f"TEST_DATABASE_URL database name must end with '_test' (got '{_dbname}'); refusing to wipe it")
os.environ["DATABASE_URL"] = _TEST_URL or f"sqlite:///{_TMP}/test.db"
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
    if _TEST_URL and _TEST_URL.startswith("postgresql"):
        from sqlalchemy import create_engine, text

        eng = create_engine(_TEST_URL)
        with eng.begin() as c:  # disposable *_test database: start from an empty schema every session
            c.execute(text("DROP SCHEMA public CASCADE"))
            c.execute(text("CREATE SCHEMA public"))
        eng.dispose()
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
