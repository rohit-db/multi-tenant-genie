# server/routers/verify.py
"""POST /api/verify — runs the isolation verifier across active tenants."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from server.lib import verifier
from server.lib.config import CONFIG
from server.lib.repository import credential as cred_repo
from server.routers import tenants as _tenants_mod

router = APIRouter()


def _mgr():
    return _tenants_mod._mgr()


class VerifyResultRow(BaseModel):
    tenant_id: str
    tenant_name: str
    passed: bool
    distinct_tenant_ids: list[str]
    visible_row_count: Optional[int] = None
    error: Optional[str] = None


def _collect_credentials(tenants) -> dict[str, Optional[str]]:
    return {t.sp_app_id: cred_repo.get(t.sp_app_id) for t in tenants}


@router.post('', response_model=list[VerifyResultRow])
async def run_verify() -> list[VerifyResultRow]:
    try:
        tenants = [t for t in _mgr().list_tenants() if t.status == "active"]
        credentials = _collect_credentials(tenants)
        executor = verifier.HttpExecutor(
            host=CONFIG.host, warehouse_id=_mgr().warehouse_id
        )
        results = verifier.verify_all(
            executor=executor, tenants=tenants, credentials=credentials,
        )
        return [
            VerifyResultRow(
                tenant_id=r.tenant_id,
                tenant_name=r.tenant_name,
                passed=r.passed,
                distinct_tenant_ids=r.distinct_tenant_ids,
                visible_row_count=r.visible_row_count,
                error=r.error,
            )
            for r in results
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
