"""Endpoint tests for reactivate + delete."""
from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient


@dataclass
class _FakeTenant:
    tenant_id: str
    tenant_name: str
    sp_app_id: str
    sp_display_name: str
    status: str = "active"
    created_at: object = None
    updated_at: object = None


@pytest.fixture
def client(monkeypatch):
    from server import app as app_module
    from server.services import runtime

    fake_mgr = MagicMock()
    fake_mgr.reactivate_tenant.return_value = "fresh-secret-xyz"
    fake_mgr.delete_tenant.return_value = None
    fake_mgr.list_tenants.return_value = [
        _FakeTenant(tenant_id="acme", tenant_name="Acme", sp_app_id="sp-acme", sp_display_name="mt-acme"),
    ]

    monkeypatch.setattr(runtime, "manager", lambda: fake_mgr)
    return TestClient(app_module.app), fake_mgr


def test_reactivate_returns_new_secret(client):
    c, fake_mgr = client
    r = c.post("/api/tenants/acme/reactivate")
    assert r.status_code == 200
    body = r.json()
    assert body["tenant_id"] == "acme"
    assert body["new_client_secret"] == "fresh-secret-xyz"
    fake_mgr.reactivate_tenant.assert_called_once_with("acme")


def test_delete_removes_tenant(client):
    c, fake_mgr = client
    r = c.delete("/api/tenants/acme")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "tenant_id": "acme"}
    fake_mgr.delete_tenant.assert_called_once_with("acme")


def test_reactivate_propagates_lookup_error(client):
    c, fake_mgr = client
    fake_mgr.reactivate_tenant.side_effect = LookupError("not found")
    r = c.post("/api/tenants/nope/reactivate")
    assert r.status_code == 500
    assert "not found" in r.json()["detail"]


def test_history_returns_per_tenant_rows(client):
    from datetime import datetime, timezone
    from dataclasses import dataclass
    from unittest.mock import patch

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

    c, _ = client
    fake_rows = [
        _FakeAuditRow(
            id=3, tenant_id="acme", actor="rohit", action="query",
            sp_app_id="sp-acme", question="hello", status="completed",
            latency_ms=900, detail=None,
            created_at=datetime(2026, 4, 29, 9, 5, tzinfo=timezone.utc),
        ),
    ]
    with patch(
        "server.services.tenant_service.audit_repo.history_for_tenant",
        return_value=fake_rows,
    ) as mocked:
        r = c.get("/api/tenants/acme/history?limit=10")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["tenant_id"] == "acme"
    assert body[0]["action"] == "query"
    mocked.assert_called_once_with("acme", limit=10)
