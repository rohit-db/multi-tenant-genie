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
    from server.routers import tenants as tenants_router

    fake_mgr = MagicMock()
    fake_mgr.reactivate_tenant.return_value = "fresh-secret-xyz"
    fake_mgr.delete_tenant.return_value = None
    fake_mgr.list_tenants.return_value = [
        _FakeTenant(tenant_id="acme", tenant_name="Acme", sp_app_id="sp-acme", sp_display_name="mt-acme"),
    ]

    monkeypatch.setattr(tenants_router, "_mgr", lambda: fake_mgr)
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
