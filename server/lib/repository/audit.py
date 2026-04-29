"""audit_log writes/reads against Lakebase."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from server.lib import db


@dataclass(frozen=True)
class AuditRow:
    id: int
    tenant_id: Optional[str]
    actor: Optional[str]
    action: str
    sp_app_id: Optional[str]
    question: Optional[str]
    status: str
    latency_ms: Optional[int]
    detail: Optional[str]
    created_at: datetime


_COLS = (
    "id, tenant_id, actor, action, sp_app_id, question, status, "
    "latency_ms, detail, created_at"
)


def _row(r) -> AuditRow:
    return AuditRow(
        id=r[0],
        tenant_id=r[1],
        actor=r[2],
        action=r[3],
        sp_app_id=r[4],
        question=r[5],
        status=r[6],
        latency_ms=r[7],
        detail=r[8],
        created_at=r[9],
    )


def append(
    *,
    action: str,
    status: str,
    tenant_id: Optional[str] = None,
    actor: Optional[str] = None,
    sp_app_id: Optional[str] = None,
    question: Optional[str] = None,
    latency_ms: Optional[int] = None,
    detail: Optional[str] = None,
) -> None:
    with db.get_connection() as conn:
        conn.execute(
            "INSERT INTO audit_log "
            "(tenant_id, actor, action, sp_app_id, question, status, latency_ms, detail) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (tenant_id, actor, action, sp_app_id, question, status, latency_ms, detail),
        )
        conn.commit()


def list_recent(limit: int = 50) -> list[AuditRow]:
    with db.get_connection() as conn:
        cur = conn.execute(
            f"SELECT {_COLS} FROM audit_log ORDER BY created_at DESC LIMIT %s",
            (limit,),
        )
        return [_row(r) for r in cur.fetchall()]


def history_for_tenant(tenant_id: str, limit: int = 50) -> list[AuditRow]:
    with db.get_connection() as conn:
        cur = conn.execute(
            f"SELECT {_COLS} FROM audit_log WHERE tenant_id = %s "
            "ORDER BY created_at DESC LIMIT %s",
            (tenant_id, limit),
        )
        return [_row(r) for r in cur.fetchall()]
