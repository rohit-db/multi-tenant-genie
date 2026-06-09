"""Tenant lifecycle orchestration over the SP manager primitive.

Each function is a complete use case — "onboard a tenant" means create the SP
*and* apply the data/Genie/dashboard grants *and* keep the token cache honest.
The router above only maps these to HTTP; ``SPManager`` below only knows the
individual Databricks operations.
"""
from __future__ import annotations

from typing import Any

from server.lib.repository import audit as audit_repo
from server.services import runtime


def list_tenants() -> list[Any]:
    """All tenants from the Lakebase client_registry (manager domain objects)."""
    return runtime.manager().list_tenants()


def _sp_app_id_for(tenant_id: str) -> str:
    for t in runtime.manager().list_tenants():
        if t.tenant_id == tenant_id:
            return t.sp_app_id
    return ''


def onboard(tenant_id: str, tenant_name: str) -> Any:
    """Create the per-tenant SP and apply every grant it needs.

    Returns the manager's onboard result (``.tenant``, ``.client_id``,
    ``.client_secret``). Dashboard grants are best-effort because the AI/BI
    dashboard may not be published on first run — ``backfill_grants`` repairs it.
    """
    tenant_id = tenant_id.strip().lower()
    tenant_name = tenant_name.strip()
    if not tenant_id or not tenant_name:
        raise ValueError('tenant_id and tenant_name are required')

    mgr = runtime.manager()
    result = mgr.onboard_tenant(tenant_id, tenant_name)
    mgr.grant_data_access([tenant_id])
    mgr.grant_genie_access([tenant_id])
    try:
        mgr.grant_dashboard_access([tenant_id])
    except Exception:
        # Dashboard may not be published yet on first run; backfill later.
        pass
    return result


def rotate(tenant_id: str) -> str:
    """Issue a fresh client secret and drop the cached token for the SP."""
    new_secret = runtime.manager().rotate_secret(tenant_id)
    runtime.invalidate_minter(_sp_app_id_for(tenant_id))
    return new_secret


def deactivate(tenant_id: str) -> None:
    """Disable the SP (deletes its secret) and drop any cached token."""
    sp_app_id = _sp_app_id_for(tenant_id)
    runtime.manager().deactivate_tenant(tenant_id)
    runtime.invalidate_minter(sp_app_id)


def reactivate(tenant_id: str) -> str:
    """Re-enable the SP with a fresh secret and drop any cached token."""
    new_secret = runtime.manager().reactivate_tenant(tenant_id)
    runtime.invalidate_minter(_sp_app_id_for(tenant_id))
    return new_secret


def delete(tenant_id: str) -> None:
    """Remove the SP entirely and drop any cached token."""
    sp_app_id = _sp_app_id_for(tenant_id)
    runtime.manager().delete_tenant(tenant_id)
    runtime.invalidate_minter(sp_app_id)


def history(tenant_id: str, limit: int = 50) -> list[Any]:
    """Recent audit_log rows for a tenant."""
    return audit_repo.history_for_tenant(tenant_id, limit=limit)


def backfill_grants() -> dict[str, Any]:
    """Re-apply data + Genie + dashboard grants to all active tenants.

    Use after publishing (or republishing) the AI/BI dashboard so existing
    tenant SPs get CAN_RUN on it. Idempotent.
    """
    mgr = runtime.manager()
    out: dict[str, Any] = {"data": "ok", "genie": "ok", "dashboard": "ok"}
    for name, fn in (
        ("data", mgr.grant_data_access),
        ("genie", mgr.grant_genie_access),
        ("dashboard", mgr.grant_dashboard_access),
    ):
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            out[name] = f"error: {e}"
    return out
