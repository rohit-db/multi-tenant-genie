"""Endpoint test for POST /api/verify."""
from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock, patch

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
    fake_mgr.list_tenants.return_value = [
        _FakeTenant("acme", "Acme", "sp-acme", "mt-acme"),
        _FakeTenant("globex", "Globex", "sp-globex", "mt-globex"),
    ]
    fake_mgr.warehouse_id = "wh-test-1"

    monkeypatch.setattr(runtime, "manager", lambda: fake_mgr)
    return TestClient(app_module.app)


def test_verify_returns_results_per_tenant(client):
    from server.primitives.unity_catalog import TenantVerifyResult

    fake_results = [
        TenantVerifyResult(
            tenant_id="acme", tenant_name="Acme",
            passed=True, distinct_tenant_ids=["acme"],
        ),
        TenantVerifyResult(
            tenant_id="globex", tenant_name="Globex",
            passed=False, distinct_tenant_ids=["acme", "globex"],
        ),
    ]
    with patch("server.routers.verify.verifier.verify_all", return_value=fake_results), \
         patch("server.routers.verify._collect_credentials", return_value={"sp-acme": "s1", "sp-globex": "s2"}):
        r = client.post("/api/verify")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 2
    assert body[0]["tenant_id"] == "acme"
    assert body[0]["passed"] is True
    assert body[1]["tenant_id"] == "globex"
    assert body[1]["passed"] is False
    assert "globex" in body[1]["distinct_tenant_ids"]
