"""Tenant SP lifecycle endpoints (wraps src/lib/sp_manager)."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from src.lib.config import CONFIG  # noqa: E402
from src.lib.sp_manager import SPManager  # noqa: E402

router = APIRouter()
_mgr_singleton: SPManager | None = None


def _mgr() -> SPManager:
    global _mgr_singleton
    if _mgr_singleton is None:
        _mgr_singleton = SPManager()
    return _mgr_singleton


def _secrets_path() -> Path:
    return _REPO / '.demo-secrets.env'


def _load_secrets() -> dict[str, str]:
    p = _secrets_path()
    if not p.exists():
        return {}
    out: dict[str, str] = {}
    for line in p.read_text().splitlines():
        if '=' in line:
            k, v = line.split('=', 1)
            out[k.strip()] = v.strip()
    return out


def _save_secrets(secrets: dict[str, str]) -> None:
    _secrets_path().write_text(
        '\n'.join(f'{k}={v}' for k, v in secrets.items()) + '\n'
    )


def _secret_key(tenant_id: str) -> str:
    return f'MT_GENIE_SECRET_{tenant_id.upper()}'


class Tenant(BaseModel):
    tenant_id: str
    tenant_name: str
    sp_app_id: str
    sp_display_name: str
    status: str
    created_at: datetime
    updated_at: datetime
    has_local_secret: bool = False


class OnboardRequest(BaseModel):
    tenant_id: str
    tenant_name: str


class OnboardResponse(BaseModel):
    tenant: Tenant
    client_id: str
    client_secret: str


class RotateResponse(BaseModel):
    tenant_id: str
    new_client_secret: str


class AuditRow(BaseModel):
    event_time: datetime | None
    actor: str | None
    tenant_id: str | None
    action: str | None
    sp_app_id: str | None
    status: str | None
    detail: str | None


@router.get('', response_model=list[Tenant])
async def list_tenants() -> list[Tenant]:
    try:
        secrets = _load_secrets()
        out: list[Tenant] = []
        for t in _mgr().list_tenants():
            out.append(
                Tenant(
                    tenant_id=t.tenant_id,
                    tenant_name=t.tenant_name,
                    sp_app_id=t.sp_app_id,
                    sp_display_name=t.sp_display_name,
                    status=t.status,
                    created_at=t.created_at,
                    updated_at=t.updated_at,
                    has_local_secret=_secret_key(t.tenant_id) in secrets,
                )
            )
        return out
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post('/onboard', response_model=OnboardResponse)
async def onboard(req: OnboardRequest) -> OnboardResponse:
    try:
        tenant_id = req.tenant_id.strip().lower()
        tenant_name = req.tenant_name.strip()
        if not tenant_id or not tenant_name:
            raise ValueError('tenant_id and tenant_name are required')
        result = _mgr().onboard_tenant(tenant_id, tenant_name)
        _mgr().grant_data_access([tenant_id])
        _mgr().grant_genie_access([tenant_id])
        secrets = _load_secrets()
        secrets[_secret_key(tenant_id)] = result.client_secret
        _save_secrets(secrets)
        return OnboardResponse(
            tenant=Tenant(
                tenant_id=result.tenant.tenant_id,
                tenant_name=result.tenant.tenant_name,
                sp_app_id=result.tenant.sp_app_id,
                sp_display_name=result.tenant.sp_display_name,
                status=result.tenant.status,
                created_at=result.tenant.created_at,
                updated_at=result.tenant.updated_at,
                has_local_secret=True,
            ),
            client_id=result.client_id,
            client_secret=result.client_secret,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post('/{tenant_id}/rotate', response_model=RotateResponse)
async def rotate(tenant_id: str) -> RotateResponse:
    try:
        new_secret = _mgr().rotate_secret(tenant_id)
        secrets = _load_secrets()
        secrets[_secret_key(tenant_id)] = new_secret
        _save_secrets(secrets)
        return RotateResponse(tenant_id=tenant_id, new_client_secret=new_secret)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post('/{tenant_id}/deactivate')
async def deactivate(tenant_id: str) -> dict[str, Any]:
    try:
        _mgr().deactivate_tenant(tenant_id)
        secrets = _load_secrets()
        secrets.pop(_secret_key(tenant_id), None)
        _save_secrets(secrets)
        return {'ok': True, 'tenant_id': tenant_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get('/audit', response_model=list[AuditRow])
async def audit(limit: int = 50) -> list[AuditRow]:
    try:
        rows = _mgr()._execute_sql(
            f"""SELECT event_time, actor, tenant_id, action, sp_app_id, status, detail
                FROM {CONFIG.fq_audit}
                ORDER BY event_time DESC
                LIMIT {int(limit)}"""
        )
        out: list[AuditRow] = []
        for r in rows:
            out.append(
                AuditRow(
                    event_time=_parse_ts(r[0]),
                    actor=r[1],
                    tenant_id=r[2],
                    action=r[3],
                    sp_app_id=r[4],
                    status=r[5],
                    detail=r[6],
                )
            )
        return out
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get('/mapping')
async def mapping() -> list[dict[str, Any]]:
    try:
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


def _parse_ts(v: Any) -> datetime | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v
    try:
        return datetime.fromisoformat(str(v).replace('Z', '+00:00'))
    except Exception:
        return None


def _parse_bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    return str(v).lower() in ('true', '1', 't')
