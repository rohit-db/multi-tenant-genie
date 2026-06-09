"""AI/BI dashboard embed-token orchestration.

Mints a scoped, browser-safe token for the published AI/BI dashboard using
the *tenant's* SP. Because the dashboard is published without embedded
credentials, its warehouse queries run as that SP, so ``session_user()`` ==
the SP and the existing UC row filter trims to the tenant — no per-tenant
dashboard copies, no app-asserted filter.
"""
from __future__ import annotations

from pydantic import BaseModel

from server.lib.config import CONFIG
from server.primitives.aibi_embed import mint_embed_token
from server.services import runtime


class EmbedConfig(BaseModel):
    instance_url: str
    workspace_id: str
    dashboard_id: str
    embed_token: str
    tenant_id: str


def embed_config(tenant_id: str, viewer_id: str) -> EmbedConfig:
    if not CONFIG.dashboard_id:
        raise ValueError(
            "No dashboard configured. Set MT_GENIE_DASHBOARD_ID to a published "
            "AI/BI dashboard (publish with embed_credentials=false)."
        )
    if not CONFIG.workspace_id:
        raise ValueError(
            "No workspace id configured. Set MT_GENIE_WORKSPACE_ID (or rely on "
            "DATABRICKS_WORKSPACE_ID injected by Databricks Apps)."
        )

    tenants = [t for t in runtime.manager().list_tenants() if t.tenant_id == tenant_id]
    if not tenants:
        raise ValueError(f"Tenant {tenant_id} not found")
    tenant = tenants[0]

    secret = runtime.secret_for_sp(tenant.sp_app_id)
    if not secret:
        raise ValueError(
            f"No credential stored for tenant {tenant_id}. "
            "Rotate on the Admin tab to regenerate."
        )

    token = mint_embed_token(
        instance_url=CONFIG.host,
        client_id=tenant.sp_app_id,
        client_secret=secret,
        dashboard_id=CONFIG.dashboard_id,
        external_viewer_id=viewer_id,
        # Defense-in-depth / audit only; isolation is enforced by the UC row
        # filter via session_user(), not by this value.
        external_value=tenant.tenant_id,
    )

    return EmbedConfig(
        instance_url=CONFIG.host.rstrip('/'),
        workspace_id=CONFIG.workspace_id,
        dashboard_id=CONFIG.dashboard_id,
        embed_token=token,
        tenant_id=tenant.tenant_id,
    )
