"""Unity Catalog: grants, row-filter enforcement, and isolation proof.

This is the governance half of the thesis. Three concerns live here because
they are all "UC enforces tenant isolation through the SQL warehouse":

1. ``UnityCatalogMixin`` — grants each tenant SP exactly the access it needs
   (USE CATALOG/SCHEMA, SELECT on the governed tables, CAN_RUN on the Genie
   space and the AI/BI dashboard). The actual isolation is the row filter +
   ``sp_tenant_mapping`` table; these grants just let the SP reach the objects.
2. ``_execute_sql`` / ``warehouse_id`` — the shared SQL-warehouse access path
   the grants (and the SP mapping writes) run through.
3. ``verify_tenant`` / ``verify_all`` — the isolation *proof*: run a query as
   each tenant SP and assert it can only see its own ``tenant_id``.

Implemented as a mixin so ``SPManager`` composes it with the SP lifecycle over
one shared ``WorkspaceClient``.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Iterable, Optional, Protocol

import requests
from databricks.sdk.service.sql import StatementState

from server.lib.config import CONFIG
from server.primitives.identity import TokenMinter

logger = logging.getLogger(__name__)


class UnityCatalogMixin:
    """UC grants + the SQL-warehouse access path they run on.

    Requires the composing class to provide ``self.w`` (WorkspaceClient),
    ``self._warehouse_id`` (cache slot), ``self.list_tenants`` and
    ``self._fetch_tenant``.
    """

    @property
    def warehouse_id(self) -> str:
        if self._warehouse_id is None:
            for wh in self.w.warehouses.list():
                if wh.name == CONFIG.warehouse_name:
                    self._warehouse_id = wh.id
                    break
            if self._warehouse_id is None:
                # fall back to first running or any serverless warehouse
                for wh in self.w.warehouses.list():
                    self._warehouse_id = wh.id
                    break
        if self._warehouse_id is None:
            raise RuntimeError("No SQL warehouse available in this workspace")
        return self._warehouse_id

    def _execute_sql(self, sql: str, parameters: list[dict] | None = None) -> list[list]:
        resp = self.w.statement_execution.execute_statement(
            warehouse_id=self.warehouse_id,
            statement=sql,
            parameters=parameters,
            wait_timeout="30s",
        )
        # poll if still running
        statement_id = resp.statement_id
        while resp.status.state in (StatementState.PENDING, StatementState.RUNNING):
            time.sleep(0.5)
            resp = self.w.statement_execution.get_statement(statement_id)
        if resp.status.state != StatementState.SUCCEEDED:
            raise RuntimeError(f"SQL failed: {resp.status.error}")
        rows = []
        if resp.result and resp.result.data_array:
            rows = resp.result.data_array
        return rows

    def grant_genie_access(
        self, tenant_ids: Iterable[str] | None = None
    ) -> None:
        """Grant CAN_RUN on the demo Genie Space to each tenant's SP.

        Uses the workspace permissions API (genie object type). Idempotent —
        re-granting is fine. Falls through silently if ``CONFIG.genie_space_id``
        is unset (first-run before the space exists).
        """
        if not CONFIG.genie_space_id:
            logger.info("No genie_space_id configured — skipping Genie grant")
            return
        if tenant_ids is None:
            tenants = [t for t in self.list_tenants() if t.status == "active"]
        else:
            tenants = [self._fetch_tenant(tid) for tid in tenant_ids]

        acl = [
            {"service_principal_name": t.sp_app_id, "permission_level": "CAN_RUN"}
            for t in tenants
        ]
        token = self.w.config.oauth_token().access_token
        r = requests.patch(
            f"{CONFIG.host}/api/2.0/permissions/genie/{CONFIG.genie_space_id}",
            headers={"Authorization": f"Bearer {token}"},
            json={"access_control_list": acl},
            timeout=30,
        )
        if not r.ok:
            raise RuntimeError(f"Genie permissions grant failed: {r.status_code} {r.text}")

    def grant_dashboard_access(
        self, tenant_ids: Iterable[str] | None = None
    ) -> None:
        """Grant CAN_RUN on the published AI/BI dashboard to each tenant's SP.

        Required for external embedding: the dashboard is published without
        embedded credentials, so each viewing SP needs CAN_RUN on the dashboard
        (and SELECT on the base tables, handled by ``grant_data_access``). The
        row filter then trims to the tenant via ``session_user()``. Idempotent;
        no-ops if ``CONFIG.dashboard_id`` is unset.
        """
        if not CONFIG.dashboard_id:
            logger.info("No dashboard_id configured — skipping dashboard grant")
            return
        if tenant_ids is None:
            tenants = [t for t in self.list_tenants() if t.status == "active"]
        else:
            tenants = [self._fetch_tenant(tid) for tid in tenant_ids]

        acl = [
            {"service_principal_name": t.sp_app_id, "permission_level": "CAN_RUN"}
            for t in tenants
        ]
        if not acl:
            return
        token = self.w.config.oauth_token().access_token
        r = requests.patch(
            f"{CONFIG.host}/api/2.0/permissions/dashboards/{CONFIG.dashboard_id}",
            headers={"Authorization": f"Bearer {token}"},
            json={"access_control_list": acl},
            timeout=30,
        )
        if not r.ok:
            raise RuntimeError(
                f"Dashboard permissions grant failed: {r.status_code} {r.text}"
            )

    def grant_data_access(self, tenant_ids: Iterable[str] | None = None) -> None:
        """Ensure each tenant SP has SELECT on bookings / customers / mapping.

        The row filter + mapping table are the enforcement layer; the grants
        just allow the SP to reach the tables at all. Runs idempotently.
        """
        if tenant_ids is None:
            tenants = [t for t in self.list_tenants() if t.status == "active"]
        else:
            tenants = [self._fetch_tenant(tid) for tid in tenant_ids]

        for t in tenants:
            for obj in (
                f"CATALOG {CONFIG.catalog}",
                f"SCHEMA {CONFIG.catalog}.{CONFIG.schema}",
            ):
                self._execute_sql(
                    f"GRANT USE {obj.split()[0]} ON {obj} TO `{t.sp_app_id}`"
                )
            for tbl in (CONFIG.fq_bookings, CONFIG.fq_customers, CONFIG.fq_mapping):
                self._execute_sql(f"GRANT SELECT ON TABLE {tbl} TO `{t.sp_app_id}`")


# --------------------------------------------------------------------------- #
# Isolation proof — run a query as each tenant SP and assert it sees only its
# own rows. Used by POST /api/verify and scripts/verify_isolation.py. The
# ``Executor`` indirection keeps it mockable without standing up a warehouse.
# --------------------------------------------------------------------------- #


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
    tenant,  # Tenant or compatible — has tenant_id, sp_app_id, etc.
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
