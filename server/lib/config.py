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
    schema=_env("MT_GENIE_SCHEMA", "mt_genie"),
    secret_scope=_env("MT_GENIE_SECRET_SCOPE", "mt-genie"),
    genie_space_id=_env("MT_GENIE_SPACE_ID"),
    warehouse_name=_env("MT_GENIE_WAREHOUSE_NAME", "Serverless Starter Warehouse"),
    sp_display_prefix=_env("MT_GENIE_SP_PREFIX", "mt-genie"),
    admin_group=_env("MT_GENIE_ADMIN_GROUP", "admins"),
)
