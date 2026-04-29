"""Genie ask-as-tenant + isolation-sweep endpoints."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from server.lib.config import CONFIG
from server.lib.genie_client import GenieClient
from server.lib.sp_manager import SPManager
from server.lib.inspector import Inspector
from server.lib.token_minter import TokenMinter

from server.routers import tenants as _tenants_mod


def _mgr():
    return _tenants_mod._mgr()

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
    inspector: dict | None = None


class SweepRequest(BaseModel):
    question: str


def _get_secret_for_sp(sp_app_id: str) -> str | None:
    from server.lib.repository import credential as cred_repo
    return cred_repo.get(sp_app_id)


def _ask_sync(
    tenant_id: str,
    question: str,
    conversation_id: str | None = None,
    *,
    inspect: bool = False,
) -> AskResponse:
    insp = Inspector() if inspect else None

    # Step 1: Authenticate (resolve which tenant the request belongs to)
    if insp is not None:
        with insp.step("Authenticate") as step:
            tenants = [t for t in _mgr().list_tenants() if t.tenant_id == tenant_id]
            if not tenants:
                raise ValueError(f'Tenant {tenant_id} not found')
            tenant = tenants[0]
            step.summary = f"Tenant resolved → {tenant.tenant_id} (sp_app_id={tenant.sp_app_id[:12]}…)"
            step.code_snippet = "tenants = mgr.list_tenants()  # reads client_registry"
    else:
        tenants = [t for t in _mgr().list_tenants() if t.tenant_id == tenant_id]
        if not tenants:
            raise ValueError(f'Tenant {tenant_id} not found')
        tenant = tenants[0]

    # Step 2: Resolve tenant (Lakebase lookup → genie_space_id)
    if insp is not None:
        with insp.step("Resolve tenant") as step:
            space_id = CONFIG.genie_space_id  # per-tenant override is Phase-2-future
            step.summary = f"genie_space_id={space_id[:12]}… (workspace global)"
            step.code_snippet = "tenant_repo.get(tenant_id)  # → client_registry row"
    else:
        space_id = CONFIG.genie_space_id

    # Step 3: Mint token
    if insp is not None:
        with insp.step("Mint token") as step:
            secret = _get_secret_for_sp(tenant.sp_app_id)
            if not secret:
                raise ValueError(
                    f"No credential stored for tenant {tenant_id}. "
                    "Rotate on the Admin tab to regenerate."
                )
            step.summary = "OAuth M2M token (cache-aware)"
            step.code_snippet = (
                "minter.get_token(client_id, client_secret)  # /oidc/v1/token"
            )
    else:
        secret = _get_secret_for_sp(tenant.sp_app_id)
        if not secret:
            raise ValueError(
                f"No credential stored for tenant {tenant_id}. "
                "Rotate on the Admin tab to regenerate."
            )

    # Step 4: Apply row filter (static — runs in-warehouse, not in proxy)
    if insp is not None:
        insp.add_static_step(
            "Apply row filter",
            summary=(
                f"Filter resolves for sp_app_id={tenant.sp_app_id[:12]}… "
                f"→ tenant_id='{tenant.tenant_id}'"
            ),
            code_snippet=(
                "CREATE OR REPLACE FUNCTION tenant_row_filter(tenant_id STRING)\n"
                "RETURN EXISTS (\n"
                "  SELECT 1 FROM sp_tenant_mapping\n"
                "  WHERE sp_app_id = session_user() AND active\n"
                "    AND m.tenant_id = tenant_row_filter.tenant_id\n"
                ");"
            ),
        )

    # Step 5: Ask Genie
    if insp is not None:
        with insp.step("Ask Genie") as step:
            resp = _client.ask(
                space_id=space_id, question=question,
                client_id=tenant.sp_app_id, client_secret=secret,
                conversation_id=conversation_id, timeout_s=120,
            )
            step.summary = (
                f"Genie status={resp.status}; rows={len(resp.rows)}; "
                f"cols={len(resp.columns)}"
            )
            step.code_snippet = (
                "POST /api/2.0/genie/spaces/{space_id}/start-conversation"
            )
    else:
        resp = _client.ask(
            space_id=space_id, question=question,
            client_id=tenant.sp_app_id, client_secret=secret,
            conversation_id=conversation_id, timeout_s=120,
        )

    # Step 6: Audit (best-effort)
    if insp is not None:
        with insp.step("Audit") as step:
            try:
                _mgr()._audit(
                    'query', tenant.tenant_id, tenant.sp_app_id,
                    question=resp.question, latency_ms=resp.latency_ms,
                    status='ok' if resp.status == 'COMPLETED' else 'error',
                    detail=None if resp.status == 'COMPLETED' else f'genie_status={resp.status}',
                )
                step.summary = "audit_log row written"
                step.code_snippet = "audit_repo.append(action='query', ...)"
            except Exception as e:
                step.summary = f"audit failed (non-fatal): {e}"
    else:
        try:
            _mgr()._audit(
                'query', tenant.tenant_id, tenant.sp_app_id,
                question=resp.question, latency_ms=resp.latency_ms,
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
        inspector=insp.build() if insp is not None else None,
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
async def ask(req: AskRequest, inspect: bool = False) -> AskResponse:
    try:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            _pool, _ask_sync_with_inspect, req.tenant_id, req.question, req.conversation_id, inspect,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _ask_sync_with_inspect(tenant_id: str, question: str, conversation_id: str | None, inspect: bool) -> AskResponse:
    """Wrapper because run_in_executor doesn't take kwargs."""
    return _ask_sync(tenant_id, question, conversation_id, inspect=inspect)


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
