"""Tests for server.lib.verifier — isolation verification logic.

The verifier executes SQL as each tenant's SP and asserts cross-tenant
isolation. Tests mock the SQL execution layer to focus on the assertion
logic, not the warehouse plumbing.
"""
from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import pytest

from server.lib import verifier


@dataclass
class _FakeTenant:
    tenant_id: str
    tenant_name: str
    sp_app_id: str
    sp_display_name: str
    status: str = "active"
    created_at: object = None
    updated_at: object = None


@pytest.fixture(autouse=True)
def fake_token_minter(monkeypatch):
    """Replace TokenMinter so tests don't hit the OAuth endpoint."""
    fake = MagicMock()
    fake_instance = MagicMock()
    fake_instance.get_token.return_value = "fake-bearer-token"
    fake.return_value = fake_instance
    monkeypatch.setattr(verifier, "TokenMinter", fake)
    return fake_instance


def test_verify_one_passes_when_only_own_rows_visible():
    fake_executor = MagicMock()
    fake_executor.run_as.return_value = [["acme"]]
    result = verifier.verify_tenant(
        executor=fake_executor,
        tenant=_FakeTenant("acme", "Acme", "sp-acme", "mt-acme"),
        secret="secret-acme",
    )
    assert result.passed is True
    assert result.distinct_tenant_ids == ["acme"]


def test_verify_one_fails_when_other_tenant_visible():
    fake_executor = MagicMock()
    fake_executor.run_as.return_value = [["acme"], ["globex"]]
    result = verifier.verify_tenant(
        executor=fake_executor,
        tenant=_FakeTenant("acme", "Acme", "sp-acme", "mt-acme"),
        secret="secret-acme",
    )
    assert result.passed is False
    assert "globex" in result.distinct_tenant_ids


def test_verify_one_fails_when_no_credential():
    fake_executor = MagicMock()
    result = verifier.verify_tenant(
        executor=fake_executor,
        tenant=_FakeTenant("acme", "Acme", "sp-acme", "mt-acme"),
        secret=None,
    )
    assert result.passed is False
    assert "no credential" in (result.error or "").lower()
    fake_executor.run_as.assert_not_called()


def test_verify_all_runs_per_active_tenant():
    fake_executor = MagicMock()
    fake_executor.run_as.return_value = [["acme"]]
    fake_credentials = {"sp-acme": "secret-acme", "sp-globex": "secret-globex"}
    tenants = [
        _FakeTenant("acme", "Acme", "sp-acme", "mt-acme"),
        _FakeTenant("globex", "Globex", "sp-globex", "mt-globex"),
        _FakeTenant("zombie", "Zombie", "sp-zombie", "mt-zombie", status="deactivated"),
    ]
    results = verifier.verify_all(
        executor=fake_executor,
        tenants=tenants,
        credentials=fake_credentials,
    )
    assert len(results) == 2
    assert {r.tenant_id for r in results} == {"acme", "globex"}
