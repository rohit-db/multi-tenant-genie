"""Shared configuration for the multi-tenant Genie reference.

In production (Databricks Apps), every value below comes from env vars
that the app.yaml resource block injects. In local dev, point ``MT_GENIE_*``
at your workspace via ``.env.local`` (bootstrap.sh writes one for you).
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    profile: str
    host: str
    catalog: str
    schema: str
    secret_scope: str
    genie_space_id: str
    warehouse_name: str
    sp_display_prefix: str
    admin_group: str
    transport: str  # "rest" (default) | "mcp" — Genie transport selection
    dashboard_id: str  # published AI/BI (Lakeview) dashboard for external embedding
    workspace_id: str  # numeric workspace id, required by @databricks/aibi-client

    def genie_mcp_url(self, space_id: str | None = None) -> str:
        """Managed MCP server URL for a Genie Space.

        Points at the single-space Genie MCP server. Isolation is unchanged:
        callers still present the tenant SP's OAuth token, so ``session_user()``
        resolves to the SP and the UC row filter applies.
        """
        sid = space_id or self.genie_space_id
        return f"{self.host.rstrip('/')}/api/2.0/mcp/genie/{sid}"

    def functions_mcp_url(self, catalog: str | None = None, schema: str | None = None) -> str:
        """Managed MCP server URL for Unity Catalog functions in a schema."""
        return (
            f"{self.host.rstrip('/')}/api/2.0/mcp/functions/"
            f"{catalog or self.catalog}/{schema or self.schema}"
        )

    def sql_mcp_url(self) -> str:
        """Managed MCP server URL for the Databricks SQL server."""
        return f"{self.host.rstrip('/')}/api/2.0/mcp/sql"

    @property
    def fq_tenants(self) -> str:
        return f"{self.catalog}.{self.schema}.tenants"

    @property
    def fq_mapping(self) -> str:
        return f"{self.catalog}.{self.schema}.sp_tenant_mapping"

    @property
    def fq_bookings(self) -> str:
        return f"{self.catalog}.{self.schema}.bookings"

    @property
    def fq_customers(self) -> str:
        return f"{self.catalog}.{self.schema}.customers"

    @property
    def fq_audit(self) -> str:
        return f"{self.catalog}.{self.schema}.audit_log"

    @property
    def fq_row_filter(self) -> str:
        return f"{self.catalog}.{self.schema}.tenant_row_filter"


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


CONFIG = Config(
    profile=_env("MT_GENIE_PROFILE"),
    host=_env("MT_GENIE_HOST"),
    catalog=_env("MT_GENIE_CATALOG"),
    schema=_env("MT_GENIE_SCHEMA", "mt_genie_demo"),
    secret_scope=_env("MT_GENIE_SECRET_SCOPE", "multi-tenant-genie"),
    genie_space_id=_env("MT_GENIE_SPACE_ID"),
    warehouse_name=_env("MT_GENIE_WAREHOUSE_NAME", "Serverless Starter Warehouse"),
    sp_display_prefix=_env("MT_GENIE_SP_PREFIX", "mt-genie"),
    admin_group=_env("MT_GENIE_ADMIN_GROUP", "admins"),
    transport=_env("MT_GENIE_TRANSPORT", "rest").lower(),
    dashboard_id=_env("MT_GENIE_DASHBOARD_ID"),
    # Databricks Apps inject DATABRICKS_WORKSPACE_ID; allow an explicit override.
    workspace_id=_env("MT_GENIE_WORKSPACE_ID") or _env("DATABRICKS_WORKSPACE_ID"),
)
