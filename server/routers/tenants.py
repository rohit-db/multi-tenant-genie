"""Tenant SP lifecycle HTTP surface.

Thin adapter over ``services.tenant_service`` — request/response models,
operator auth, and a one-line call into the service per endpoint. The
shared SP manager lives as a process-wide singleton in
``services.runtime`` and is reached only through the service layer.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from server.lib.auth import require_operator
from server.services import tenant_service

router = APIRouter()


class Tenant(BaseModel):
    tenant_id: str
    tenant_name: str
    sp_app_id: str
    sp_display_name: str
    status: str
    created_at: datetime
    updated_at: datetime


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


class BulkOnboardRequest(BaseModel):
    tenants: list[OnboardRequest]


class BulkOnboardResponse(BaseModel):
    job_id: str


class HistoryRow(BaseModel):
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


def _to_tenant(t: Any) -> Tenant:
    return Tenant(
        tenant_id=t.tenant_id,
        tenant_name=t.tenant_name,
        sp_app_id=t.sp_app_id,
        sp_display_name=t.sp_display_name,
        status=t.status,
        created_at=t.created_at,
        updated_at=t.updated_at,
    )


@router.get('', response_model=list[Tenant])
async def list_tenants() -> list[Tenant]:
    try:
        return [_to_tenant(t) for t in tenant_service.list_tenants()]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post('/onboard', response_model=OnboardResponse, dependencies=[Depends(require_operator)])
async def onboard(req: OnboardRequest) -> OnboardResponse:
    try:
        result = tenant_service.onboard(req.tenant_id, req.tenant_name)
        return OnboardResponse(
            tenant=_to_tenant(result.tenant),
            client_id=result.client_id,
            client_secret=result.client_secret,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post('/bulk', response_model=BulkOnboardResponse, dependencies=[Depends(require_operator)])
async def bulk_onboard(req: BulkOnboardRequest) -> BulkOnboardResponse:
    if not req.tenants:
        raise HTTPException(status_code=400, detail="tenants list is empty")
    from server.routers.jobs import runner
    job_id = runner().submit([
        {"tenant_id": t.tenant_id, "tenant_name": t.tenant_name}
        for t in req.tenants
    ])
    return BulkOnboardResponse(job_id=job_id)


@router.post('/{tenant_id}/rotate', response_model=RotateResponse, dependencies=[Depends(require_operator)])
async def rotate(tenant_id: str) -> RotateResponse:
    try:
        new_secret = tenant_service.rotate(tenant_id)
        return RotateResponse(tenant_id=tenant_id, new_client_secret=new_secret)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post('/{tenant_id}/deactivate', dependencies=[Depends(require_operator)])
async def deactivate(tenant_id: str) -> dict[str, Any]:
    try:
        tenant_service.deactivate(tenant_id)
        return {'ok': True, 'tenant_id': tenant_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post('/{tenant_id}/reactivate', response_model=RotateResponse, dependencies=[Depends(require_operator)])
async def reactivate(tenant_id: str) -> RotateResponse:
    try:
        new_secret = tenant_service.reactivate(tenant_id)
        return RotateResponse(tenant_id=tenant_id, new_client_secret=new_secret)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete('/{tenant_id}', dependencies=[Depends(require_operator)])
async def delete(tenant_id: str) -> dict[str, Any]:
    try:
        tenant_service.delete(tenant_id)
        return {'ok': True, 'tenant_id': tenant_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get('/{tenant_id}/history', response_model=list[HistoryRow], dependencies=[Depends(require_operator)])
async def history(tenant_id: str, limit: int = 50) -> list[HistoryRow]:
    try:
        rows = tenant_service.history(tenant_id, limit=limit)
        return [HistoryRow(**r.__dict__) for r in rows]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post('/grants/backfill', dependencies=[Depends(require_operator)])
async def backfill_grants() -> dict[str, Any]:
    """Re-apply data + Genie + dashboard grants to all active tenants.

    Use after publishing (or republishing) the AI/BI dashboard so existing
    tenant SPs get CAN_RUN on it. Idempotent.
    """
    return tenant_service.backfill_grants()
