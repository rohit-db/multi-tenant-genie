"""Genie ask-as-tenant + isolation-sweep endpoints."""

from __future__ import annotations

import asyncio
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from src.lib.config import CONFIG  # noqa: E402
from src.lib.genie_client import GenieClient  # noqa: E402
from src.lib.sp_manager import SPManager  # noqa: E402
from src.lib.token_minter import TokenMinter  # noqa: E402

from .tenants import _load_secrets, _mgr, _secret_key  # noqa: E402

router = APIRouter()

_minter = TokenMinter()
_client = GenieClient(_minter)
_pool = ThreadPoolExecutor(max_workers=8)


class AskRequest(BaseModel):
    tenant_id: str
    question: str
    conversation_id: str | None = None


class AskResponse(BaseModel):
    tenant_id: str
    tenant_name: str
    sp_app_id: str
    question: str
    answer_text: str | None
    sql: str | None
    columns: list[str]
    rows: list[list]
    latency_ms: int
    conversation_id: str | None
    message_id: str | None
    status: str


class SweepRequest(BaseModel):
    question: str


def _get_secret(tenant_id: str) -> str | None:
    return _load_secrets().get(_secret_key(tenant_id))


def _ask_sync(tenant_id: str, question: str, conversation_id: str | None = None) -> AskResponse:
    secret = _get_secret(tenant_id)
    tenants = [t for t in _mgr().list_tenants() if t.tenant_id == tenant_id]
    if not tenants:
        raise ValueError(f'Tenant {tenant_id} not found')
    tenant = tenants[0]
    if not secret:
        raise ValueError(
            f'No local secret for tenant {tenant_id}. Rotate on the Admin '
            'tab to regenerate.'
        )
    resp = _client.ask(
        space_id=CONFIG.genie_space_id,
        question=question,
        client_id=tenant.sp_app_id,
        client_secret=secret,
        conversation_id=conversation_id,
        timeout_s=120,
    )
    # Best-effort audit log; never fail the request if logging fails.
    try:
        _mgr()._audit(
            'query',
            tenant.tenant_id,
            tenant.sp_app_id,
            question=resp.question,
            latency_ms=resp.latency_ms,
            status='ok' if resp.status == 'COMPLETED' else 'error',
            detail=None if resp.status == 'COMPLETED' else f'genie_status={resp.status}',
        )
    except Exception:
        pass
    return AskResponse(
        tenant_id=tenant.tenant_id,
        tenant_name=tenant.tenant_name,
        sp_app_id=tenant.sp_app_id,
        question=resp.question,
        answer_text=resp.answer_text,
        sql=resp.sql,
        columns=resp.columns,
        rows=resp.rows,
        latency_ms=resp.latency_ms,
        conversation_id=resp.conversation_id,
        message_id=resp.message_id,
        status=resp.status,
    )


def _ask_safe(tenant_id: str, question: str) -> AskResponse:
    """Sweep-friendly variant: never raises. Returns a FAILED stub on error."""
    try:
        return _ask_sync(tenant_id, question)
    except Exception as e:
        tenant_name = tenant_id
        sp_app_id = ''
        try:
            for t in _mgr().list_tenants():
                if t.tenant_id == tenant_id:
                    tenant_name = t.tenant_name
                    sp_app_id = t.sp_app_id
                    break
        except Exception:
            pass
        return AskResponse(
            tenant_id=tenant_id,
            tenant_name=tenant_name,
            sp_app_id=sp_app_id,
            question=question,
            answer_text=f'Error: {e}',
            sql=None,
            columns=[],
            rows=[],
            latency_ms=0,
            conversation_id=None,
            message_id=None,
            status='FAILED',
        )


@router.post('/ask', response_model=AskResponse)
async def ask(req: AskRequest) -> AskResponse:
    try:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            _pool, _ask_sync, req.tenant_id, req.question, req.conversation_id
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post('/sweep', response_model=list[AskResponse])
async def sweep(req: SweepRequest) -> list[AskResponse]:
    try:
        tenants = [t for t in _mgr().list_tenants() if t.status == 'active']
        loop = asyncio.get_event_loop()
        futures = [
            loop.run_in_executor(_pool, _ask_safe, t.tenant_id, req.question)
            for t in tenants
        ]
        results: list[AskResponse] = []
        for f in asyncio.as_completed(futures):
            results.append(await f)
        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
