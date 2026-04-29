"""Isolation verifier — proves each tenant SP sees only its own rows.

Executes a SQL query as each tenant via the Statement Execution API,
collects distinct tenant_ids visible from the bookings table, and
asserts the only visible tenant_id is the SP's own. Used by:
- POST /api/verify (returns per-tenant pass/fail)
- scripts/verify_isolation.py (the CLI release-gate flavor)

The ``executor`` is a small interface (a `run_as(token, sql)` callable)
so we can mock it in tests without standing up a warehouse.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Optional, Protocol

import requests

from server.lib.config import CONFIG
from server.lib.token_minter import TokenMinter


@dataclass
class TenantVerifyResult:
    tenant_id: str
    tenant_name: str
    passed: bool
    distinct_tenant_ids: list[str]
    visible_row_count: Optional[int] = None
    error: Optional[str] = None


class Executor(Protocol):
    """Runs SQL with a bearer token. Mockable in tests."""

    def run_as(self, token: str, sql: str) -> list[list[Any]]: ...


class HttpExecutor:
    """Default executor: hits /api/2.0/sql/statements directly with the token."""

    def __init__(self, host: str, warehouse_id: str):
        self.host = host.rstrip("/")
        self.warehouse_id = warehouse_id

    def run_as(self, token: str, sql: str) -> list[list[Any]]:
        r = requests.post(
            f"{self.host}/api/2.0/sql/statements",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "warehouse_id": self.warehouse_id,
                "statement": sql,
                "wait_timeout": "30s",
            },
            timeout=60,
        )
        r.raise_for_status()
        body = r.json()
        statement_id = body["statement_id"]
        while body.get("status", {}).get("state") in ("PENDING", "RUNNING"):
            time.sleep(0.5)
            rr = requests.get(
                f"{self.host}/api/2.0/sql/statements/{statement_id}",
                headers={"Authorization": f"Bearer {token}"},
                timeout=30,
            )
            rr.raise_for_status()
            body = rr.json()
        if body.get("status", {}).get("state") != "SUCCEEDED":
            raise RuntimeError(f"SQL failed: {body}")
        return (body.get("result") or {}).get("data_array") or []


def verify_tenant(
    *,
    executor: Executor,
    tenant,  # SPManager.Tenant or compatible — has tenant_id, sp_app_id, etc.
    secret: Optional[str],
) -> TenantVerifyResult:
    """Verify a single tenant. Never raises — failures are captured in the result."""
    if not secret:
        return TenantVerifyResult(
            tenant_id=tenant.tenant_id,
            tenant_name=tenant.tenant_name,
            passed=False,
            distinct_tenant_ids=[],
            error=f"no credential available for tenant {tenant.tenant_id}",
        )
    minter = TokenMinter()
    try:
        token = minter.get_token(tenant.sp_app_id, secret)
    except Exception as e:
        return TenantVerifyResult(
            tenant_id=tenant.tenant_id,
            tenant_name=tenant.tenant_name,
            passed=False,
            distinct_tenant_ids=[],
            error=f"token mint failed: {e}",
        )
    try:
        distinct = executor.run_as(
            token, f"SELECT DISTINCT tenant_id FROM {CONFIG.fq_bookings}"
        )
        visible_ids = sorted({str(r[0]) for r in distinct if r and r[0] is not None})
        passed = visible_ids == [tenant.tenant_id]
        return TenantVerifyResult(
            tenant_id=tenant.tenant_id,
            tenant_name=tenant.tenant_name,
            passed=passed,
            distinct_tenant_ids=visible_ids,
        )
    except Exception as e:
        return TenantVerifyResult(
            tenant_id=tenant.tenant_id,
            tenant_name=tenant.tenant_name,
            passed=False,
            distinct_tenant_ids=[],
            error=str(e),
        )


def verify_all(
    *,
    executor: Executor,
    tenants: list,
    credentials: dict[str, Optional[str]],
) -> list[TenantVerifyResult]:
    """Verify every active tenant. ``credentials`` maps sp_app_id → secret."""
    results: list[TenantVerifyResult] = []
    for t in tenants:
        if getattr(t, "status", "active") != "active":
            continue
        results.append(
            verify_tenant(
                executor=executor,
                tenant=t,
                secret=credentials.get(t.sp_app_id),
            )
        )
    return results
