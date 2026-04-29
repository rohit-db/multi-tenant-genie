"""Audit log + UC mapping read endpoints."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from server.lib.config import CONFIG
from server.lib.repository import audit as audit_repo

router = APIRouter()


class AuditRow(BaseModel):
    id: int
    tenant_id: str | None
    actor: str | None
    action: str
    sp_app_id: str | None
    question: str | None
    status: str
    latency_ms: int | None
    detail: str | None
    created_at: datetime


@router.get('', response_model=list[AuditRow])
async def list_audit(limit: int = 50) -> list[AuditRow]:
    try:
        rows = audit_repo.list_recent(limit=limit)
        return [AuditRow(**r.__dict__) for r in rows]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get('/mapping')
async def list_mapping() -> list[dict[str, Any]]:
    try:
        from server.routers.tenants import _mgr
        rows = _mgr()._execute_sql(
            f"""SELECT sp_app_id, tenant_id, active FROM {CONFIG.fq_mapping}
                ORDER BY tenant_id"""
        )
        return [
            {'sp_app_id': r[0], 'tenant_id': r[1], 'active': _parse_bool(r[2])}
            for r in rows
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _parse_bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    return str(v).lower() in ('true', '1', 't')
