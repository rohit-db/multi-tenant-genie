"""Endpoint test for POST /api/genie/ask?inspect=true."""
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


@dataclass
class _FakeGenieResponse:
    question: str
    answer_text: str | None
    sql: str | None
    rows: list[list]
    columns: list[str]
    latency_ms: int
    conversation_id: str | None
    message_id: str | None
    status: str
    raw: dict


@pytest.fixture
def client(monkeypatch):
    from server import app as app_module
    from server.services import genie_service, runtime

    fake_mgr = MagicMock()
    fake_mgr.list_tenants.return_value = [
        _FakeTenant("acme", "Acme", "sp-acme", "mt-acme"),
    ]
    monkeypatch.setattr(runtime, "manager", lambda: fake_mgr)

    fake_genie_response = _FakeGenieResponse(
        question="how many bookings",
        answer_text="187 bookings",
        sql="SELECT COUNT(*) FROM bookings",
        rows=[[187]], columns=["count"],
        latency_ms=2113,
        conversation_id="conv-1", message_id="msg-1",
        status="COMPLETED", raw={},
    )

    def fake_ask(*, space_id, question, client_id, client_secret, conversation_id, timeout_s):
        return fake_genie_response

    monkeypatch.setattr(genie_service._client, "ask", fake_ask)
    monkeypatch.setattr(
        runtime, "secret_for_sp", lambda sp_app_id: "secret-acme"
    )

    return TestClient(app_module.app)


def test_ask_without_inspect_omits_inspector(client):
    r = client.post("/api/genie/ask", json={
        "tenant_id": "acme", "question": "how many bookings"
    })
    assert r.status_code == 200
    body = r.json()
    assert body.get("inspector") is None


def test_ask_with_inspect_returns_six_steps(client):
    r = client.post("/api/genie/ask?inspect=true", json={
        "tenant_id": "acme", "question": "how many bookings"
    })
    assert r.status_code == 200
    body = r.json()
    assert body["inspector"] is not None
    steps = body["inspector"]["steps"]
    names = [s["name"] for s in steps]
    assert names == [
        "Authenticate", "Resolve tenant", "Mint token",
        "Apply row filter", "Ask Genie", "Audit",
    ]
    apply_filter = next(s for s in steps if s["name"] == "Apply row filter")
    assert "tenant_id" in (apply_filter["summary"] or "")
