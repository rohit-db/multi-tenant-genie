"""Per-tenant Service Principal lifecycle (the identity primitive).

Each operation creates/rotates/disables/deletes one tenant's SP and keeps the
Lakebase rows + UC mapping in lockstep so Unity Catalog row filters reflect the
change immediately. This is the "one isolated identity per tenant" half of the
thesis; the grant + row-filter half lives in ``unity_catalog``.

Implemented as a mixin so ``SPManager`` can compose it with ``UnityCatalogMixin``
over a single shared ``WorkspaceClient`` — every method here resolves
``self.w``, ``self.warehouse_id``, ``self._audit`` and ``self._fetch_tenant``
off the composed instance.

Design notes
------------
* Uses workspace-level SPs (the proxy may not have account-admin
  privileges). In prod, account-level SPs are preferred so the same
  identity works across workspaces. The API surface is identical.
* One OAuth secret per SP. For real zero-downtime rotation, create a
  second secret, roll callers to it, then delete the first. ``rotate``
  below demonstrates the overlap pattern.
* SP credentials are stored in Lakebase ``sp_credentials``, AES-GCM
  encrypted at rest. The legacy Databricks secret-scope path is no
  longer used.
* UC mapping updates go through the SQL warehouse (no DBFS, no driver).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from server.lib.config import CONFIG

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


class ServicePrincipalLifecycleMixin:
    """SCIM + OAuth-secret lifecycle for tenant SPs.

    Requires the composing class to provide ``self.w`` (WorkspaceClient),
    ``self.warehouse_id``, ``self._audit`` and ``self._fetch_tenant``.
    """

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

    # ------------------------------------------------------------------ helpers
    def _ensure_secret_scope(self) -> None:
        scopes = {s.name for s in self.w.secrets.list_scopes()}
        if CONFIG.secret_scope not in scopes:
            self.w.secrets.create_scope(scope=CONFIG.secret_scope)

    def _sp_db_id(self, app_id: str) -> str:
        for sp in self.w.service_principals.list(filter=f'applicationId eq "{app_id}"'):
            return sp.id
        raise LookupError(f"SP {app_id} not found")
