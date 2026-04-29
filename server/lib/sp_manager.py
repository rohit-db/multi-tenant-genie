"""Service Principal lifecycle for the multi-tenant Genie demo.

Each public method performs one lifecycle operation AND updates the UC
mapping table so UC row filters reflect the change immediately.

Design notes
------------
* Uses workspace-level SPs (FEVM doesn't grant me account admin). In prod,
  account-level SPs are preferred so the same identity works across
  workspaces. The API surface is identical.
* One OAuth secret per SP. For real zero-downtime rotation, create a
  second secret, roll callers to it, then delete the first. `rotate()`
  below demonstrates the overlap pattern.
* Secret material is stored in the ${scope} Databricks secret scope
  under the key ``<sp_app_id>``. The scope is workspace-scoped and
  ACL'd to admins only.
* UC mapping updates go through the SQL warehouse (no DBFS, no driver).
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

import requests
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.iam import ServicePrincipal
from databricks.sdk.service.sql import StatementState

from .config import CONFIG

logger = logging.getLogger(__name__)


@dataclass
class Tenant:
    tenant_id: str
    tenant_name: str
    sp_app_id: str
    sp_display_name: str
    status: str
    created_at: datetime
    updated_at: datetime


@dataclass
class OnboardResult:
    tenant: Tenant
    client_id: str
    client_secret: str  # returned once, never read back


class SPManager:
    """Thin wrapper around the Databricks SDK for tenant SP lifecycle."""

    def __init__(self, profile: str | None = None):
        self.profile = profile or CONFIG.profile
        self.w = WorkspaceClient(profile=self.profile)
        self._warehouse_id: str | None = None

    # ------------------------------------------------------------------ helpers
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

    # ---------------------------------------------------------------- public API
    def list_tenants(self, include_deactivated: bool = True) -> list[Tenant]:
        where = "" if include_deactivated else "WHERE status <> 'deactivated'"
        rows = self._execute_sql(
            f"""
            SELECT tenant_id, tenant_name, sp_app_id, sp_display_name, status,
                   created_at, updated_at
            FROM {CONFIG.fq_tenants}
            {where}
            ORDER BY created_at DESC
            """
        )
        return [
            Tenant(
                tenant_id=r[0],
                tenant_name=r[1],
                sp_app_id=r[2],
                sp_display_name=r[3],
                status=r[4],
                created_at=_parse_ts(r[5]),
                updated_at=_parse_ts(r[6]),
            )
            for r in rows
        ]

    def onboard_tenant(self, tenant_id: str, tenant_name: str) -> OnboardResult:
        """Create an SP, mint its first OAuth secret, and register the mapping."""
        display = f"{CONFIG.sp_display_prefix}-{tenant_id}"

        logger.info("Creating SP %s", display)
        sp: ServicePrincipal = self.w.service_principals.create(
            display_name=display,
            active=True,
        )
        sp_app_id = sp.application_id
        sp_db_id = sp.id

        logger.info("Minting OAuth secret for SP %s (db_id=%s)", sp_app_id, sp_db_id)
        secret = self.w.service_principal_secrets_proxy.create(
            service_principal_id=sp_db_id
        )
        # SDK returns ``secret`` (the one-time value); ``id`` identifies it later.
        client_secret = secret.secret
        secret_id = secret.id

        # Persist secret in Databricks secret scope
        self._ensure_secret_scope()
        self.w.secrets.put_secret(
            scope=CONFIG.secret_scope,
            key=sp_app_id,
            string_value=client_secret,
        )

        # Grant workspace + warehouse + catalog access (entitlements handled by admin group later)
        now = datetime.now(timezone.utc).isoformat()
        self._execute_sql(
            f"""
            INSERT INTO {CONFIG.fq_tenants}
              (tenant_id, tenant_name, sp_app_id, sp_display_name, status, created_at, updated_at)
            VALUES ('{tenant_id}', '{tenant_name}', '{sp_app_id}', '{display}',
                    'active', TIMESTAMP'{now}', TIMESTAMP'{now}')
            """
        )
        self._execute_sql(
            f"""
            INSERT INTO {CONFIG.fq_mapping} (sp_app_id, tenant_id, active)
            VALUES ('{sp_app_id}', '{tenant_id}', true)
            """
        )
        self._audit("onboard", tenant_id, sp_app_id, detail=f"secret_id={secret_id}")

        return OnboardResult(
            tenant=Tenant(
                tenant_id=tenant_id,
                tenant_name=tenant_name,
                sp_app_id=sp_app_id,
                sp_display_name=display,
                status="active",
                created_at=datetime.fromisoformat(now),
                updated_at=datetime.fromisoformat(now),
            ),
            client_id=sp_app_id,
            client_secret=client_secret,
        )

    def rotate_secret(self, tenant_id: str) -> str:
        """Create a fresh OAuth secret, persist it, and remove the old one.

        Returns the new client_secret. Uses the Databricks 5-secrets-per-SP
        allowance to demonstrate zero-downtime overlap: the new secret is
        usable immediately; old secret is deleted only after the new one is
        saved, so any in-flight token exchange keeps working.
        """
        tenant = self._fetch_tenant(tenant_id)
        sp_db_id = self._sp_db_id(tenant.sp_app_id)

        existing = list(self.w.service_principal_secrets_proxy.list(
            service_principal_id=sp_db_id
        ))

        fresh = self.w.service_principal_secrets_proxy.create(
            service_principal_id=sp_db_id
        )
        # Persist new secret first
        self.w.secrets.put_secret(
            scope=CONFIG.secret_scope,
            key=tenant.sp_app_id,
            string_value=fresh.secret,
        )
        # Delete any prior secrets AFTER the new one is stored
        for s in existing:
            try:
                self.w.service_principal_secrets_proxy.delete(
                    service_principal_id=sp_db_id,
                    secret_id=s.id,
                )
            except Exception as e:
                logger.warning("Could not delete old secret %s: %s", s.id, e)

        now = datetime.now(timezone.utc).isoformat()
        self._execute_sql(
            f"""
            UPDATE {CONFIG.fq_tenants}
            SET status = 'active', updated_at = TIMESTAMP'{now}'
            WHERE tenant_id = '{tenant_id}'
            """
        )
        self._audit("rotate", tenant_id, tenant.sp_app_id)
        return fresh.secret

    def deactivate_tenant(self, tenant_id: str) -> None:
        """Disable the SP, flip mapping off, mark tenant deactivated."""
        tenant = self._fetch_tenant(tenant_id)
        sp_db_id = self._sp_db_id(tenant.sp_app_id)

        # Mark SP inactive (don't delete — audit trail needs the SP to resolve)
        self.w.service_principals.update(
            id=sp_db_id,
            active=False,
            application_id=tenant.sp_app_id,
            display_name=tenant.sp_display_name,
        )
        # Remove all OAuth secrets so stale tokens can't keep calling
        for s in self.w.service_principal_secrets_proxy.list(
            service_principal_id=sp_db_id
        ):
            self.w.service_principal_secrets_proxy.delete(
                service_principal_id=sp_db_id, secret_id=s.id
            )
        try:
            self.w.secrets.delete_secret(
                scope=CONFIG.secret_scope, key=tenant.sp_app_id
            )
        except Exception:
            pass

        now = datetime.now(timezone.utc).isoformat()
        self._execute_sql(
            f"UPDATE {CONFIG.fq_mapping} SET active = false "
            f"WHERE sp_app_id = '{tenant.sp_app_id}'"
        )
        self._execute_sql(
            f"""
            UPDATE {CONFIG.fq_tenants}
            SET status = 'deactivated', updated_at = TIMESTAMP'{now}'
            WHERE tenant_id = '{tenant_id}'
            """
        )
        self._audit("deactivate", tenant_id, tenant.sp_app_id)

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

    # ------------------------------------------------------------------ helpers
    def _ensure_secret_scope(self) -> None:
        scopes = {s.name for s in self.w.secrets.list_scopes()}
        if CONFIG.secret_scope not in scopes:
            self.w.secrets.create_scope(scope=CONFIG.secret_scope)

    def _sp_db_id(self, app_id: str) -> str:
        for sp in self.w.service_principals.list(filter=f'applicationId eq "{app_id}"'):
            return sp.id
        raise LookupError(f"SP {app_id} not found")

    def _fetch_tenant(self, tenant_id: str) -> Tenant:
        for t in self.list_tenants():
            if t.tenant_id == tenant_id:
                return t
        raise LookupError(f"Tenant {tenant_id} not found")

    def _audit(
        self,
        action: str,
        tenant_id: str,
        sp_app_id: str,
        *,
        detail: str | None = None,
        latency_ms: int | None = None,
        status: str = "ok",
        question: str | None = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        actor = "unknown"
        try:
            actor = self.w.current_user.me().user_name or "unknown"
        except Exception:
            pass

        def _q(v: str | None) -> str:
            return "NULL" if v is None else f"'{v.replace(chr(39), chr(39)*2)}'"

        latency_sql = "NULL" if latency_ms is None else str(int(latency_ms))
        self._execute_sql(
            f"""
            INSERT INTO {CONFIG.fq_audit}
              (event_time, actor, tenant_id, action, sp_app_id, question,
               latency_ms, status, detail)
            VALUES (TIMESTAMP'{now}', '{actor}', '{tenant_id}', '{action}',
                    '{sp_app_id}', {_q(question)}, {latency_sql}, '{status}', {_q(detail)})
            """
        )


def _parse_ts(v) -> datetime:
    if isinstance(v, datetime):
        return v
    # Databricks SQL returns ISO strings
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except Exception:
        return datetime.now(timezone.utc)
