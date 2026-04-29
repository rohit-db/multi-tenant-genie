"""Tests for server.lib.repository.audit — audit_log writes/reads.

Requires `docker compose up -d` (Postgres on :5432). Skipped otherwise.
"""
import pytest
import psycopg

from server.lib import db
from server.lib.repository import audit as audit_repo

LOCAL_DB = "postgresql://postgres:postgres@localhost:5432/mtg"


def _can_connect() -> bool:
    try:
        with psycopg.connect(LOCAL_DB, connect_timeout=2):
            return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _can_connect(), reason="Local Postgres not running")


@pytest.fixture
def fresh_db(monkeypatch):
    with psycopg.connect(LOCAL_DB, autocommit=True) as conn:
        conn.execute("DROP SCHEMA public CASCADE")
        conn.execute("CREATE SCHEMA public")
    monkeypatch.setenv("DATABASE_URL", LOCAL_DB)
    db.apply_migrations("sql/lakebase")
    yield


def test_append_and_read(fresh_db):
    audit_repo.append(
        tenant_id="acme",
        action="query",
        question="how many bookings",
        status="completed",
        latency_ms=1200,
    )
    rows = audit_repo.list_recent(limit=10)
    assert len(rows) == 1
    r = rows[0]
    assert r.tenant_id == "acme"
    assert r.action == "query"
    assert r.latency_ms == 1200


def test_per_tenant_history(fresh_db):
    for tid in ("a", "b", "a"):
        audit_repo.append(tenant_id=tid, action="query", status="completed")
    rows = audit_repo.history_for_tenant("a", limit=10)
    assert len(rows) == 2
    assert all(r.tenant_id == "a" for r in rows)


def test_recent_orders_newest_first(fresh_db):
    audit_repo.append(tenant_id="a", action="query", status="completed")
    audit_repo.append(tenant_id="b", action="query", status="completed")
    rows = audit_repo.list_recent(limit=10)
    assert rows[0].tenant_id == "b"
    assert rows[1].tenant_id == "a"
