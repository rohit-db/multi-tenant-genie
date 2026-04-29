"""Postgres connection + idempotent migration runner.

In production (Databricks Apps), the Lakebase resource block injects
``DATABASE_URL`` as an env var. In local dev, ``docker-compose up -d``
provides a Postgres on :5432 and the developer points ``DATABASE_URL``
at it (default in ``.env.local``).

Migrations live under ``sql/lakebase/`` as ``V<NNN>__<name>.sql`` files
and are applied in lexicographic order. Applied versions are tracked in
the ``schema_migrations`` table; rerunning is a no-op.
"""
from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import psycopg

logger = logging.getLogger(__name__)


def database_url() -> str:
    """Return the DATABASE_URL env var, raising if unset."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set. In local dev, run "
            "`docker compose up -d` and `export DATABASE_URL=postgresql://postgres:postgres@localhost:5432/mtg`."
        )
    return url


@contextmanager
def get_connection() -> Iterator[psycopg.Connection]:
    """Yield a psycopg connection. Caller must commit or rollback."""
    conn = psycopg.connect(database_url())
    try:
        yield conn
    finally:
        conn.close()


def apply_migrations(migrations_dir: Path | str) -> None:
    """Apply every V*.sql in ``migrations_dir`` not yet recorded.

    Idempotent: re-running is a no-op once all files are recorded.
    """
    mig_dir = Path(migrations_dir)
    files = sorted(p for p in mig_dir.glob("V*.sql"))
    with psycopg.connect(database_url(), autocommit=True) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "  version TEXT PRIMARY KEY, "
            "  applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()"
            ")"
        )
        applied = {
            r[0]
            for r in conn.execute("SELECT version FROM schema_migrations").fetchall()
        }
        for f in files:
            if f.name in applied:
                continue
            logger.info("Applying migration %s", f.name)
            sql = f.read_text()
            conn.execute(sql)
            conn.execute(
                "INSERT INTO schema_migrations (version) VALUES (%s)",
                (f.name,),
            )
