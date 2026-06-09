"""SPManager — composes the two tenant-isolation primitives.

``SPManager`` is the facade the services layer talks to. It owns nothing but
the shared ``WorkspaceClient`` and the tiny cross-cutting helpers (tenant
lookups + audit); the actual capabilities come from two mixins:

* :class:`~server.primitives.service_principals.ServicePrincipalLifecycleMixin`
  — create / rotate / deactivate / reactivate / delete the per-tenant SP.
* :class:`~server.primitives.unity_catalog.UnityCatalogMixin`
  — grant data / Genie / dashboard access and run warehouse SQL.

Splitting them keeps each "Databricks is all you need" capability in its own
file while preserving a single, behavior-identical public API.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from databricks.sdk import WorkspaceClient

from server.lib.config import CONFIG
from server.primitives.service_principals import (
    OnboardResult,
    ServicePrincipalLifecycleMixin,
    Tenant,
)
from server.primitives.unity_catalog import UnityCatalogMixin

logger = logging.getLogger(__name__)

__all__ = ["SPManager", "Tenant", "OnboardResult"]


class SPManager(ServicePrincipalLifecycleMixin, UnityCatalogMixin):
    """Thin wrapper around the Databricks SDK for tenant SP lifecycle + grants."""

    def __init__(self, profile: str | None = None):
        self.profile = profile or CONFIG.profile
        self.w = WorkspaceClient(profile=self.profile)
        self._warehouse_id: str | None = None

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

    # ------------------------------------------------------------------ helpers
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
