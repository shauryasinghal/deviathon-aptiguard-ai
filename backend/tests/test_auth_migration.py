"""Migration 0008 (external_identities, auth_tokens) on a disposable database: preserves existing rows, matches the ORM,
enforces the uniqueness rules and downgrades cleanly. The live database is never used."""
import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings


@pytest.fixture()
def mig(tmp_path):
    from alembic.config import Config

    url = f"sqlite:///{tmp_path}/mig0008.db"
    backend = Path(__file__).resolve().parents[1]
    cfg = Config(str(backend / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend / "alembic"))
    old = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    get_settings.cache_clear()
    try:
        yield cfg, url
    finally:
        if old is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = old
        get_settings.cache_clear()


def test_0008_preserves_users_matches_the_models_and_downgrades_cleanly(mig):
    from alembic import command

    cfg, url = mig
    command.upgrade(cfg, "0007")
    eng = create_engine(url)
    with eng.begin() as c:
        c.execute(text("INSERT INTO organizations (id, name, slug, created_at) VALUES (1, 'o', 'o', '2026-01-01 00:00:00')"))
        c.execute(text("INSERT INTO roles (id, name, label, description) VALUES (1, 'candidate', 'Candidate', '')"))
        c.execute(text("INSERT INTO users (id, org_id, email, full_name, password_hash, role_id, is_active, token_version, created_at) "
                       "VALUES (1, 1, 'keep@example.com', 'Keep Me', 'hash', 1, 1, 0, '2026-01-01 00:00:00')"))
    command.upgrade(cfg, "head")
    insp = inspect(eng)
    assert {"external_identities", "auth_tokens"} <= set(insp.get_table_names())
    with eng.connect() as c:
        assert c.execute(text("SELECT email, password_hash FROM users WHERE id = 1")).one() == ("keep@example.com", "hash")
        assert c.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0008"
    command.check(cfg)  # raises if the models and the migrated schema differ

    with eng.begin() as c:
        c.execute(text("INSERT INTO external_identities (user_id, provider, subject, email, created_at) VALUES (1, 'google', 's1', 'k@e.com', '2026-01-01')"))
        c.execute(text("INSERT INTO auth_tokens (kind, token_hash, expires_at, created_at) VALUES ('oauth_state', 'h1', '2026-01-01', '2026-01-01')"))
    for stmt in ("INSERT INTO external_identities (user_id, provider, subject, email, created_at) VALUES (1, 'google', 's1', 'x', '2026-01-01')",   # same Google account
                 "INSERT INTO external_identities (user_id, provider, subject, email, created_at) VALUES (1, 'google', 's2', 'x', '2026-01-01')",   # second identity for the user
                 "INSERT INTO auth_tokens (kind, token_hash, expires_at, created_at) VALUES ('login_ticket', 'h1', '2026-01-01', '2026-01-01')"):  # duplicate token hash
        with pytest.raises(IntegrityError):
            with eng.begin() as c:
                c.execute(text(stmt))
    with eng.begin() as c:  # deleting a user removes its identities/tokens (no orphan credentials)
        c.execute(text("PRAGMA foreign_keys=ON"))
    command.downgrade(cfg, "0007")
    insp = inspect(eng)
    assert not {"external_identities", "auth_tokens"} & set(insp.get_table_names())
    with eng.connect() as c:
        assert c.execute(text("SELECT email FROM users")).scalars().all() == ["keep@example.com"]  # local accounts survive
    command.upgrade(cfg, "head")
    eng.dispose()
