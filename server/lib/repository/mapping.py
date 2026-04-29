"""sp_tenant_mapping in UC Delta (joined by the row filter)."""
from __future__ import annotations

import time

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import StatementState

from server.lib.config import CONFIG


def _execute(w: WorkspaceClient, warehouse_id: str, sql: str) -> None:
    """Execute a SQL statement and wait for completion.

    SQL string interpolation is safe here because callers pass sp_app_id and
    tenant_id from internal sources (Databricks SDK return values, not user input).
    """
    resp = w.statement_execution.execute_statement(
        warehouse_id=warehouse_id, statement=sql, wait_timeout="30s"
    )
    while resp.status.state in (StatementState.PENDING, StatementState.RUNNING):
        time.sleep(0.5)
        resp = w.statement_execution.get_statement(resp.statement_id)
    if resp.status.state != StatementState.SUCCEEDED:
        raise RuntimeError(f"UC statement failed: {resp.status.error}")


def insert_mapping(w: WorkspaceClient, warehouse_id: str, sp_app_id: str, tenant_id: str) -> None:
    """Insert a new SP-tenant mapping."""
    _execute(
        w, warehouse_id,
        f"INSERT INTO {CONFIG.fq_mapping} (sp_app_id, tenant_id, active) "
        f"VALUES ('{sp_app_id}', '{tenant_id}', true)",
    )


def deactivate_mapping(w: WorkspaceClient, warehouse_id: str, sp_app_id: str) -> None:
    """Deactivate a mapping (mark active = false)."""
    _execute(
        w, warehouse_id,
        f"UPDATE {CONFIG.fq_mapping} SET active = false WHERE sp_app_id = '{sp_app_id}'",
    )


def activate_mapping(w: WorkspaceClient, warehouse_id: str, sp_app_id: str) -> None:
    """Activate a mapping (mark active = true)."""
    _execute(
        w, warehouse_id,
        f"UPDATE {CONFIG.fq_mapping} SET active = true WHERE sp_app_id = '{sp_app_id}'",
    )


def delete_mapping(w: WorkspaceClient, warehouse_id: str, sp_app_id: str) -> None:
    """Delete a mapping entirely."""
    _execute(
        w, warehouse_id,
        f"DELETE FROM {CONFIG.fq_mapping} WHERE sp_app_id = '{sp_app_id}'",
    )
