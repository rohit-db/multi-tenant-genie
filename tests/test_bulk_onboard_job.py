"""Tests for server.jobs.bulk_onboard — in-process job runner."""
from __future__ import annotations

import time
from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest

from server.jobs import bulk_onboard


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


def _make_fake_mgr(*, fail_on: set[str] | None = None):
    """Build a MagicMock that mimics SPManager.onboard_tenant."""
    fail_on = fail_on or set()
    mgr = MagicMock()

    def onboard(tenant_id, tenant_name):
        time.sleep(0.01)  # simulate work; lets progress polling observe states
        if tenant_id in fail_on:
            raise RuntimeError(f"forced failure for {tenant_id}")
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

    mgr.onboard_tenant.side_effect = onboard
    mgr.grant_data_access.return_value = None
    mgr.grant_genie_access.return_value = None
    return mgr


def test_submit_returns_job_id():
    runner = bulk_onboard.JobRunner(_make_fake_mgr(), max_workers=2)
    job_id = runner.submit([
        {"tenant_id": "a", "tenant_name": "A"},
        {"tenant_id": "b", "tenant_name": "B"},
    ])
    assert isinstance(job_id, str) and len(job_id) > 0


def test_status_progresses_to_completed():
    runner = bulk_onboard.JobRunner(_make_fake_mgr(), max_workers=2)
    job_id = runner.submit([
        {"tenant_id": "a", "tenant_name": "A"},
        {"tenant_id": "b", "tenant_name": "B"},
    ])
    deadline = time.time() + 5.0
    while time.time() < deadline:
        status = runner.get_status(job_id)
        if status.state == "completed":
            break
        time.sleep(0.05)
    status = runner.get_status(job_id)
    assert status.state == "completed"
    assert status.processed == 2
    assert status.total == 2
    assert len(status.errors) == 0


def test_partial_failure_recorded_in_errors():
    runner = bulk_onboard.JobRunner(_make_fake_mgr(fail_on={"b"}), max_workers=2)
    job_id = runner.submit([
        {"tenant_id": "a", "tenant_name": "A"},
        {"tenant_id": "b", "tenant_name": "B"},
        {"tenant_id": "c", "tenant_name": "C"},
    ])
    deadline = time.time() + 5.0
    while time.time() < deadline:
        if runner.get_status(job_id).state == "completed":
            break
        time.sleep(0.05)
    status = runner.get_status(job_id)
    assert status.state == "completed"
    assert status.processed == 3
    assert len(status.errors) == 1
    assert status.errors[0]["tenant_id"] == "b"
    assert "forced failure" in status.errors[0]["error"]


def test_results_carry_secret_for_successes():
    runner = bulk_onboard.JobRunner(_make_fake_mgr(), max_workers=2)
    job_id = runner.submit([{"tenant_id": "a", "tenant_name": "A"}])
    deadline = time.time() + 3.0
    while time.time() < deadline:
        if runner.get_status(job_id).state == "completed":
            break
        time.sleep(0.05)
    status = runner.get_status(job_id)
    results = status.results
    assert len(results) == 1
    assert results[0]["tenant_id"] == "a"
    assert results[0]["client_secret"] == "secret-a"
    assert results[0]["sp_app_id"] == "sp-a"


def test_unknown_job_id_returns_none():
    runner = bulk_onboard.JobRunner(_make_fake_mgr(), max_workers=2)
    assert runner.get_status("nope") is None
