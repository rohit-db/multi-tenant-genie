"""Shared configuration for the multi-tenant Genie demo.

All constants live here so scripts, the UI, and the POC doc stay in sync.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class DemoConfig:
    profile: str = "fe-vm-serverless-jsr0s9"
    host: str = "https://fevm-serverless-jsr0s9.cloud.databricks.com"
    catalog: str = "serverless_jsr0s9_catalog"
    schema: str = "mt_genie_demo"
    secret_scope: str = "mt-genie-demo"
    genie_space_name: str = "Multi-Tenant Bookings Demo"
    genie_space_id: str = "01f13e70745b1ce5b9cf8d9e6a46e23f"
    warehouse_name: str = "Serverless Starter Warehouse"
    sp_display_prefix: str = "mt-genie-demo"
    admin_group: str = "admins"

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


CONFIG = DemoConfig(
    profile=os.environ.get("MT_GENIE_PROFILE", DemoConfig.profile),
    catalog=os.environ.get("MT_GENIE_CATALOG", DemoConfig.catalog),
    schema=os.environ.get("MT_GENIE_SCHEMA", DemoConfig.schema),
    genie_space_id=os.environ.get("MT_GENIE_SPACE_ID", DemoConfig.genie_space_id),
)
