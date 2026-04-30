"""Service Principal lifecycle for the multi-tenant Genie reference.

Each public method performs one lifecycle operation AND updates the UC
mapping table so UC row filters reflect the change immediately.

Design notes
------------
* Uses workspace-level SPs (the proxy may not have account-admin
  privileges). In prod, account-level SPs are preferred so the same
  identity works across workspaces. The API surface is identical.
* One OAuth secret per SP. For real zero-downtime rotation, create a
  second secret, roll callers to it, then delete the first. `rotate()`
  below demonstrates the overlap pattern.
* SP credentials are stored in Lakebase ``sp_credentials``, AES-GCM
  encrypted at rest. The legacy Databricks secret-scope path is no
  longer used.
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
        from server.lib.repository import tenant as tenant_repo
        rows = tenant_repo.list_all()
        if not include_deactivated:
            rows = [r for r in rows if r.status != "deactivated"]
        return [
            Tenant(
                tenant_id=r.tenant_id,
                tenant_name=r.display_name,
                sp_app_id=r.sp_app_id,
                sp_display_name=r.sp_display_name,
                status=r.status,
                created_at=r.created_at,
                updated_at=r.updated_at,
            )
            for r in rows
        ]

    def onboard_tenant(self, tenant_id: str, tenant_name: str) -> OnboardResult:
        """Create SP, mint secret, register in Lakebase + UC mapping. Roll back on any failure."""
        from server.lib.repository import (
            tenant as tenant_repo,
            credential as cred_repo,
            mapping as mapping_repo,
        )

        display = f"{CONFIG.sp_display_prefix}-{tenant_id}"
        logger.info("Creating SP %s", display)
        sp = self.w.service_principals.create(display_name=display, active=True)
        sp_app_id = sp.application_id
        sp_db_id = sp.id

        try:
            secret = self.w.service_principal_secrets_proxy.create(
                service_principal_id=sp_db_id
            )
            client_secret = secret.secret

            # 1. UC mapping (row-filter join target)
            mapping_repo.insert_mapping(self.w, self.warehouse_id, sp_app_id, tenant_id)

            # 2. Lakebase: tenant + credential
            tenant_repo.insert(
                tenant_id=tenant_id,
                display_name=tenant_name,
                sp_app_id=sp_app_id,
                sp_display_name=display,
            )
            cred_repo.put(sp_app_id, client_secret)
        except Exception:
            # Roll back: delete UC mapping (if it was inserted), delete Lakebase rows, delete SP
            try:
                mapping_repo.delete_mapping(self.w, self.warehouse_id, sp_app_id)
            except Exception:
                pass
            try:
                tenant_repo.delete(tenant_id)
            except Exception:
                pass
            try:
                cred_repo.delete(sp_app_id)
            except Exception:
                pass
            try:
                self.w.service_principals.delete(id=sp_db_id)
            except Exception:
                pass
            raise

        self._audit("onboard", tenant_id, sp_app_id, detail=f"sp_db_id={sp_db_id}")

        now = datetime.now(timezone.utc)
        return OnboardResult(
            tenant=Tenant(
                tenant_id=tenant_id, tenant_name=tenant_name,
                sp_app_id=sp_app_id, sp_display_name=display,
                status="active", created_at=now, updated_at=now,
            ),
            client_id=sp_app_id,
            client_secret=client_secret,
        )

    def rotate_secret(self, tenant_id: str) -> str:
        """Create a fresh OAuth secret, persist it in Lakebase, and remove the old one.

        Returns the new client_secret. Uses the Databricks 5-secrets-per-SP
        allowance to demonstrate zero-downtime overlap: the new secret is
        usable immediately; old secret is deleted only after the new one is
        saved, so any in-flight token exchange keeps working.
        """
        from server.lib.repository import credential as cred_repo
        tenant = self._fetch_tenant(tenant_id)
        sp_db_id = self._sp_db_id(tenant.sp_app_id)

        existing = list(self.w.service_principal_secrets_proxy.list(
            service_principal_id=sp_db_id
        ))
        fresh = self.w.service_principal_secrets_proxy.create(service_principal_id=sp_db_id)

        cred_repo.put(tenant.sp_app_id, fresh.secret)

        for s in existing:
            try:
                self.w.service_principal_secrets_proxy.delete(
                    service_principal_id=sp_db_id,
                    secret_id=s.id,
                )
            except Exception as e:
                logger.warning("Could not delete old secret %s: %s", s.id, e)

        from server.lib.repository import tenant as tenant_repo
        tenant_repo.set_status(tenant_id, "active")
        self._audit("rotate", tenant_id, tenant.sp_app_id)
        return fresh.secret

    def deactivate_tenant(self, tenant_id: str) -> None:
        """Disable the SP, flip mapping off, mark tenant deactivated."""
        from server.lib.repository import (
            tenant as tenant_repo, credential as cred_repo, mapping as mapping_repo
        )
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
        for s in self.w.service_principal_secrets_proxy.list(service_principal_id=sp_db_id):
            self.w.service_principal_secrets_proxy.delete(
                service_principal_id=sp_db_id, secret_id=s.id
            )

        cred_repo.delete(tenant.sp_app_id)
        mapping_repo.deactivate_mapping(self.w, self.warehouse_id, tenant.sp_app_id)
        tenant_repo.set_status(tenant_id, "deactivated")
        self._audit("deactivate", tenant_id, tenant.sp_app_id)

    def reactivate_tenant(self, tenant_id: str) -> str:
        """Re-enable a previously deactivated tenant. Returns the new client secret.

        Reactivation is not a no-op — deactivation deletes the SP secret and
        drops the credential row. We mint a fresh secret, store it, flip the SP
        back to active, re-enable the mapping, and update status. Caller must
        distribute the new secret to whoever was using the old one.
        """
        from server.lib.repository import (
            tenant as tenant_repo, credential as cred_repo, mapping as mapping_repo
        )
        tenant = self._fetch_tenant(tenant_id)
        sp_db_id = self._sp_db_id(tenant.sp_app_id)

        # Re-enable the SP
        self.w.service_principals.update(
            id=sp_db_id, active=True,
            application_id=tenant.sp_app_id, display_name=tenant.sp_display_name,
        )
        # Mint fresh OAuth secret
        fresh = self.w.service_principal_secrets_proxy.create(
            service_principal_id=sp_db_id
        )
        cred_repo.put(tenant.sp_app_id, fresh.secret)
        mapping_repo.activate_mapping(self.w, self.warehouse_id, tenant.sp_app_id)
        tenant_repo.set_status(tenant_id, "active")
        self._audit("reactivate", tenant_id, tenant.sp_app_id)
        return fresh.secret

    def delete_tenant(self, tenant_id: str) -> None:
        """Hard delete: remove SP, mapping row, credential row, registry row.

        Best-effort across the four resources — each cleanup is wrapped in
        its own try block so a partial failure on one doesn't leave the
        others orphaned. Final state: tenant_id no longer exists anywhere.
        """
        from server.lib.repository import (
            tenant as tenant_repo, credential as cred_repo, mapping as mapping_repo
        )
        tenant = self._fetch_tenant(tenant_id)
        sp_app_id = tenant.sp_app_id

        # 1. Delete SP (also removes its OAuth secrets)
        try:
            sp_db_id = self._sp_db_id(sp_app_id)
            self.w.service_principals.delete(id=sp_db_id)
        except Exception as e:
            logger.warning("Could not delete SP %s: %s", sp_app_id, e)

        # 2. Drop UC mapping row
        try:
            mapping_repo.delete_mapping(self.w, self.warehouse_id, sp_app_id)
        except Exception as e:
            logger.warning("Could not delete UC mapping for %s: %s", sp_app_id, e)

        # 3. Drop Lakebase credential row
        try:
            cred_repo.delete(sp_app_id)
        except Exception as e:
            logger.warning("Could not delete credential for %s: %s", sp_app_id, e)

        # 4. Drop Lakebase tenant row
        tenant_repo.delete(tenant_id)
        self._audit("delete", tenant_id, sp_app_id)

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
        from server.lib.repository import tenant as tenant_repo
        r = tenant_repo.get(tenant_id)
        if not r:
            raise LookupError(f"Tenant {tenant_id} not found")
        return Tenant(
            tenant_id=r.tenant_id,
            tenant_name=r.display_name,
            sp_app_id=r.sp_app_id,
            sp_display_name=r.sp_display_name,
            status=r.status,
            created_at=r.created_at,
            updated_at=r.updated_at,
        )

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
        from server.lib.repository import audit as audit_repo
        actor = "unknown"
        try:
            actor = self.w.current_user.me().user_name or "unknown"
        except Exception:
            pass
        audit_repo.append(
            action=action, status=status, tenant_id=tenant_id, actor=actor,
            sp_app_id=sp_app_id, question=question, latency_ms=latency_ms, detail=detail,
        )


def _parse_ts(v) -> datetime:
    if isinstance(v, datetime):
        return v
    # Databricks SQL returns ISO strings
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except Exception:
        return datetime.now(timezone.utc)
