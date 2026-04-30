"""Postgres connection + idempotent migration runner.

Two modes:

* **Databricks Apps (production)** — Apps injects ``PGHOST``/``PGPORT``/
  ``PGDATABASE``/``PGUSER`` from a bound Lakebase resource. Lakebase auth
  is OAuth — the password is a fresh OAuth token from the workspace's
  service principal, minted at connect time.

* **Local dev** — ``DATABASE_URL`` points at a Postgres container
  (typically ``postgresql://postgres:postgres@localhost:5432/mtg``).

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
from urllib.parse import quote_plus

import psycopg

logger = logging.getLogger(__name__)


def _databricks_oauth_token() -> str:
    """Mint a fresh OAuth token from the workspace SP for Lakebase auth."""
    from databricks.sdk import WorkspaceClient

    w = WorkspaceClient()
    auth = w.config.authenticate()
    if auth and "Authorization" in auth:
        return auth["Authorization"].replace("Bearer ", "")
    raise RuntimeError(
        "Could not get OAuth token from WorkspaceClient. Apps mode requires "
        "the app SP's identity to be available."
    )


def database_url() -> str:
    """Return a Postgres connection URL.

    Apps mode (PGHOST set): builds a URL with PG* env vars + a fresh OAuth
    token as the password. Token is minted on every call — fine for the
    request load this app handles; for higher load, cache + refresh.

    Local-dev mode (DATABASE_URL set): returns it as-is.
    """
    pg_host = os.environ.get("PGHOST")
    if pg_host:
        token = _databricks_oauth_token()
        pg_port = os.environ.get("PGPORT", "5432")
        pg_db = os.environ.get("PGDATABASE", "mtg")
        pg_user = os.environ.get("PGUSER", "")
        return (
            f"postgresql://{quote_plus(pg_user)}:{quote_plus(token)}"
            f"@{pg_host}:{pg_port}/{pg_db}?sslmode=require"
        )

    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "Neither PGHOST (Apps mode) nor DATABASE_URL (local-dev mode) is set. "
            "In local dev, run `docker compose up -d` and "
            "`export DATABASE_URL=postgresql://postgres:postgres@localhost:5432/mtg`."
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
