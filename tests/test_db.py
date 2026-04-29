"""Tests for server.lib.db — connection + migration runner.

Requires `docker compose up -d` (Postgres on :5432). Skipped otherwise.
"""
import os
import pytest
import psycopg

from server.lib import db

LOCAL_DB = "postgresql://postgres:postgres@localhost:5432/mtg"


def _can_connect() -> bool:
    try:
        with psycopg.connect(LOCAL_DB, connect_timeout=2):
            return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _can_connect(),
    reason="Local Postgres not running — bring up docker-compose to run db tests",
)


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    """Reset the public schema before each test."""
    with psycopg.connect(LOCAL_DB, autocommit=True) as conn:
        conn.execute("DROP SCHEMA public CASCADE")
        conn.execute("CREATE SCHEMA public")
    monkeypatch.setenv("DATABASE_URL", LOCAL_DB)
    yield


def test_get_connection_returns_open_connection(fresh_db):
    with db.get_connection() as conn:
        assert not conn.closed
        cur = conn.execute("SELECT 1")
        assert cur.fetchone()[0] == 1


def test_apply_migrations_creates_schema_objects(fresh_db, tmp_path):
    # Write a tiny migration to a temp directory and point the runner at it
    mig_dir = tmp_path / "migrations"
    mig_dir.mkdir()
    (mig_dir / "V001__a.sql").write_text(
        "CREATE TABLE thing (id SERIAL PRIMARY KEY, name TEXT NOT NULL);"
    )
    (mig_dir / "V002__b.sql").write_text(
        "ALTER TABLE thing ADD COLUMN extra TEXT;"
    )
    db.apply_migrations(mig_dir)
    with db.get_connection() as conn:
        cols = [r[0] for r in conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'thing' ORDER BY ordinal_position"
        ).fetchall()]
        assert cols == ["id", "name", "extra"]


def test_apply_migrations_is_idempotent(fresh_db, tmp_path):
    mig_dir = tmp_path / "migrations"
    mig_dir.mkdir()
    (mig_dir / "V001__a.sql").write_text(
        "CREATE TABLE thing (id SERIAL PRIMARY KEY);"
    )
    db.apply_migrations(mig_dir)
    db.apply_migrations(mig_dir)  # Second run must not error
    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall()
        assert [r[0] for r in rows] == ["V001__a.sql"]
