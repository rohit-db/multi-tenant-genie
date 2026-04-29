"""Endpoint tests for POST /api/tenants/bulk and GET /api/jobs/{id}."""
from __future__ import annotations

import time
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


@dataclass
class _FakeOnboardResult:
    tenant: _FakeTenant
    client_id: str
    client_secret: str


@pytest.fixture
def client(monkeypatch):
    from server import app as app_module
    from server.routers import tenants as tenants_router

    fake_mgr = MagicMock()

    def fake_onboard(tenant_id, tenant_name):
        sp_app = f"sp-{tenant_id}"
        return _FakeOnboardResult(
            tenant=_FakeTenant(
                tenant_id=tenant_id,
                tenant_name=tenant_name,
                sp_app_id=sp_app,
                sp_display_name=f"mt-genie-{tenant_id}",
            ),
            client_id=sp_app,
            client_secret=f"secret-{tenant_id}",
        )

    fake_mgr.onboard_tenant.side_effect = fake_onboard
    fake_mgr.grant_data_access.return_value = None
    fake_mgr.grant_genie_access.return_value = None

    monkeypatch.setattr(tenants_router, "_mgr", lambda: fake_mgr)

    # Reset job runner state per test
    from server.routers import jobs as jobs_router
    jobs_router._reset_for_tests()

    return TestClient(app_module.app)


def test_bulk_returns_job_id(client):
    r = client.post("/api/tenants/bulk", json={
        "tenants": [
            {"tenant_id": "a", "tenant_name": "A"},
            {"tenant_id": "b", "tenant_name": "B"},
        ]
    })
    assert r.status_code == 200
    assert "job_id" in r.json()


def test_status_endpoint_progresses(client):
    r = client.post("/api/tenants/bulk", json={
        "tenants": [
            {"tenant_id": "a", "tenant_name": "A"},
            {"tenant_id": "b", "tenant_name": "B"},
        ]
    })
    job_id = r.json()["job_id"]
    deadline = time.time() + 5.0
    final = None
    while time.time() < deadline:
        s = client.get(f"/api/jobs/{job_id}")
        assert s.status_code == 200
        body = s.json()
        if body["state"] == "completed":
            final = body
            break
        time.sleep(0.05)
    assert final is not None
    assert final["total"] == 2
    assert final["processed"] == 2


def test_unknown_job_id_returns_404(client):
    r = client.get("/api/jobs/does-not-exist")
    assert r.status_code == 404


def test_bulk_rejects_empty_list(client):
    r = client.post("/api/tenants/bulk", json={"tenants": []})
    assert r.status_code == 400
