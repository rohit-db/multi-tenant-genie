"""Endpoint tests for GET /api/audit and GET /api/audit/mapping."""
from __future__ import annotations

from datetime import datetime, timezone
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@dataclass
class _FakeAuditRow:
    id: int
    tenant_id: str | None
    actor: str | None
    action: str
    sp_app_id: str | None
    question: str | None
    status: str
    latency_ms: int | None
    detail: str | None
    created_at: datetime


@pytest.fixture
def client(monkeypatch):
    from server import app as app_module
    from server.routers import tenants as tenants_router

    fake_mgr = MagicMock()
    fake_mgr._execute_sql.return_value = [
        ["sp-acme", "acme", "true"],
        ["sp-globex", "globex", "false"],
    ]
    monkeypatch.setattr(tenants_router, "_mgr", lambda: fake_mgr)
    return TestClient(app_module.app), fake_mgr


def test_audit_returns_lakebase_rows(client):
    c, _ = client
    fake_rows = [
        _FakeAuditRow(
            id=2, tenant_id="acme", actor="rohit", action="query",
            sp_app_id="sp-acme", question="hello", status="completed",
            latency_ms=1100, detail=None,
            created_at=datetime(2026, 4, 29, 9, 0, tzinfo=timezone.utc),
        ),
        _FakeAuditRow(
            id=1, tenant_id="globex", actor="rohit", action="onboard",
            sp_app_id="sp-globex", question=None, status="ok",
            latency_ms=None, detail=None,
            created_at=datetime(2026, 4, 29, 8, 55, tzinfo=timezone.utc),
        ),
    ]
    with patch("server.routers.audit.audit_repo.list_recent", return_value=fake_rows):
        r = c.get("/api/audit?limit=10")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 2
    assert body[0]["tenant_id"] == "acme"
    assert body[0]["action"] == "query"
    assert body[0]["latency_ms"] == 1100


def test_audit_default_limit(client):
    c, _ = client
    with patch("server.routers.audit.audit_repo.list_recent", return_value=[]) as mocked:
        r = c.get("/api/audit")
    assert r.status_code == 200
    mocked.assert_called_once_with(limit=50)


def test_mapping_returns_uc_rows(client):
    c, fake_mgr = client
    r = c.get("/api/audit/mapping")
    assert r.status_code == 200
    body = r.json()
    assert body == [
        {"sp_app_id": "sp-acme", "tenant_id": "acme", "active": True},
        {"sp_app_id": "sp-globex", "tenant_id": "globex", "active": False},
    ]
