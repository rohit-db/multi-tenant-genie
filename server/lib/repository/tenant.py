"""client_registry CRUD against Lakebase / local Postgres."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from server.lib import db


@dataclass(frozen=True)
class TenantRow:
    tenant_id: str
    display_name: str
    sp_app_id: str
    sp_display_name: str
    status: str
    genie_space_id: Optional[str]
    metadata: dict
    created_at: datetime
    updated_at: datetime


_COLS = (
    "tenant_id, display_name, sp_app_id, sp_display_name, status, "
    "genie_space_id, metadata, created_at, updated_at"
)


def _row(r) -> TenantRow:
    return TenantRow(
        tenant_id=r[0],
        display_name=r[1],
        sp_app_id=r[2],
        sp_display_name=r[3],
        status=r[4],
        genie_space_id=r[5],
        metadata=r[6] or {},
        created_at=r[7],
        updated_at=r[8],
    )


def insert(
    *,
    tenant_id: str,
    display_name: str,
    sp_app_id: str,
    sp_display_name: str,
    genie_space_id: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> None:
    with db.get_connection() as conn:
        conn.execute(
            "INSERT INTO client_registry "
            "(tenant_id, display_name, sp_app_id, sp_display_name, genie_space_id, metadata) "
            "VALUES (%s, %s, %s, %s, %s, %s::jsonb)",
            (
                tenant_id,
                display_name,
                sp_app_id,
                sp_display_name,
                genie_space_id,
                _json(metadata or {}),
            ),
        )
        conn.commit()


def get(tenant_id: str) -> Optional[TenantRow]:
    with db.get_connection() as conn:
        cur = conn.execute(
            f"SELECT {_COLS} FROM client_registry WHERE tenant_id = %s",
            (tenant_id,),
        )
        row = cur.fetchone()
        return _row(row) if row else None


def list_all() -> list[TenantRow]:
    with db.get_connection() as conn:
        cur = conn.execute(
            f"SELECT {_COLS} FROM client_registry ORDER BY created_at DESC"
        )
        return [_row(r) for r in cur.fetchall()]


def set_status(tenant_id: str, status: str) -> None:
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE client_registry SET status = %s, updated_at = NOW() "
            "WHERE tenant_id = %s",
            (status, tenant_id),
        )
        conn.commit()


def delete(tenant_id: str) -> None:
    with db.get_connection() as conn:
        conn.execute("DELETE FROM client_registry WHERE tenant_id = %s", (tenant_id,))
        conn.commit()


def _json(d: dict) -> str:
    import json
    return json.dumps(d)
