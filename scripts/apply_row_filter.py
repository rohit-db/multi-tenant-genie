"""(Re)attach the tenant row filter to the demo tables.

The row filter is the load-bearing isolation control: it keeps each tenant SP
scoped to its own rows regardless of whether queries arrive over the Genie REST
Conversation API or the managed MCP server. If a workspace drifts (filter
detached, function dropped), tenant SPs start seeing *all* rows — run this to
restore the guarantee.

Idempotent. Safe to run repeatedly.

Usage:
    . .venv/bin/activate
    python scripts/apply_row_filter.py
    # overrides:
    APPLY_PROFILE=<cli-profile> APPLY_CATALOG=<your-catalog> \\
      APPLY_SCHEMA=mt_genie_demo ADMIN_GROUP=admins python scripts/apply_row_filter.py

Verify afterwards with scripts/spike_mcp_isolation.py (tenant SP should see
only its slice over both REST and MCP).
"""
from __future__ import annotations

import os
import time

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import StatementState

PROFILE = os.environ.get("APPLY_PROFILE") or os.environ.get("DATABRICKS_CONFIG_PROFILE", "DEFAULT")
CAT = os.environ.get("APPLY_CATALOG") or os.environ.get("MT_GENIE_CATALOG")
SCH = os.environ.get("APPLY_SCHEMA") or os.environ.get("MT_GENIE_SCHEMA", "mt_genie_demo")
if not CAT:
    raise SystemExit("Set APPLY_CATALOG (or MT_GENIE_CATALOG) to your Unity Catalog name.")
ADMIN_GROUP = os.environ.get("ADMIN_GROUP", "admins")
TABLES = ("bookings", "customers")

w = WorkspaceClient(profile=PROFILE)
wh = next(
    (x.id for x in w.warehouses.list() if str(x.state) == "State.RUNNING"),
    next(iter(w.warehouses.list())).id,
)


def sql(stmt: str):
    r = w.statement_execution.execute_statement(
        warehouse_id=wh, statement=stmt, wait_timeout="30s"
    )
    while r.status.state in (StatementState.PENDING, StatementState.RUNNING):
        time.sleep(0.5)
        r = w.statement_execution.get_statement(r.statement_id)
    if r.status.state != StatementState.SUCCEEDED:
        raise RuntimeError(f"FAILED: {stmt[:70]}... -> {r.status.error}")
    return r.result.data_array if r.result and r.result.data_array else []


def main() -> None:
    print(f"# {CAT}.{SCH} (admin_group='{ADMIN_GROUP}', profile={PROFILE})\n")

    print(f"recreating tenant_row_filter ...")
    sql(f"""CREATE OR REPLACE FUNCTION {CAT}.{SCH}.tenant_row_filter(tenant_id STRING)
RETURN
  is_account_group_member('{ADMIN_GROUP}')
  OR EXISTS (
    SELECT 1 FROM {CAT}.{SCH}.sp_tenant_mapping m
    WHERE m.sp_app_id = session_user() AND m.active = true
      AND m.tenant_id = tenant_row_filter.tenant_id
  )""")

    for tbl in TABLES:
        print(f"attaching row filter to {tbl} ...")
        sql(
            f"ALTER TABLE {CAT}.{SCH}.{tbl} "
            f"SET ROW FILTER {CAT}.{SCH}.tenant_row_filter ON (tenant_id)"
        )

    print("\ndone. Verify with: python scripts/spike_mcp_isolation.py")


if __name__ == "__main__":
    main()
