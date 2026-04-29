"""Tests for server.lib.repository.tenant — client_registry CRUD.

Requires `docker compose up -d` (Postgres on :5432). Skipped otherwise.
"""
import os
import pytest
import psycopg

from server.lib import db
from server.lib.repository import tenant as tenant_repo

LOCAL_DB = "postgresql://postgres:postgres@localhost:5432/mtg"


def _can_connect() -> bool:
    try:
        with psycopg.connect(LOCAL_DB, connect_timeout=2):
            return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _can_connect(), reason="Local Postgres not running"
)


@pytest.fixture
def fresh_db(monkeypatch):
    with psycopg.connect(LOCAL_DB, autocommit=True) as conn:
        conn.execute("DROP SCHEMA public CASCADE")
        conn.execute("CREATE SCHEMA public")
    monkeypatch.setenv("DATABASE_URL", LOCAL_DB)
    db.apply_migrations("sql/lakebase")
    yield


def test_insert_and_get(fresh_db):
    tenant_repo.insert(
        tenant_id="acme",
        display_name="Acme Industrial",
        sp_app_id="app-123",
        sp_display_name="mt-genie-acme",
    )
    t = tenant_repo.get("acme")
    assert t is not None
    assert t.tenant_id == "acme"
    assert t.display_name == "Acme Industrial"
    assert t.sp_app_id == "app-123"
    assert t.status == "active"
    assert t.genie_space_id is None


def test_get_missing_returns_none(fresh_db):
    assert tenant_repo.get("nope") is None


def test_list_returns_in_creation_order(fresh_db):
    tenant_repo.insert(tenant_id="a", display_name="A", sp_app_id="sp-a", sp_display_name="A")
    tenant_repo.insert(tenant_id="b", display_name="B", sp_app_id="sp-b", sp_display_name="B")
    rows = tenant_repo.list_all()
    ids = [r.tenant_id for r in rows]
    assert ids == ["b", "a"]  # newest first


def test_set_status(fresh_db):
    tenant_repo.insert(tenant_id="x", display_name="X", sp_app_id="sp-x", sp_display_name="X")
    tenant_repo.set_status("x", "deactivated")
    assert tenant_repo.get("x").status == "deactivated"


def test_delete_removes_row(fresh_db):
    tenant_repo.insert(tenant_id="y", display_name="Y", sp_app_id="sp-y", sp_display_name="Y")
    tenant_repo.delete("y")
    assert tenant_repo.get("y") is None


def test_insert_with_genie_space_override(fresh_db):
    tenant_repo.insert(
        tenant_id="z", display_name="Z", sp_app_id="sp-z", sp_display_name="Z",
        genie_space_id="space-42",
    )
    assert tenant_repo.get("z").genie_space_id == "space-42"
