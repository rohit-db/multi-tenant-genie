"""Genie HTTP surface: ask-as-tenant, isolation sweep, direct SQL, AI/BI embed.

Thin adapter — every endpoint parses the request, hands off to a service
(``services.genie_service`` / ``services.embed_service``) on the shared thread
pool, and maps exceptions to HTTP. All Databricks logic lives below this layer.
"""
from __future__ import annotations

import asyncio
import functools
import hashlib
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from server.lib.auth import current_user
from server.services import embed_service, genie_service, runtime
from server.services.embed_service import EmbedConfig
from server.services.genie_service import AskResponse, RunSqlResponse

router = APIRouter()

# Blocking service calls run here so the event loop stays free.
_pool = ThreadPoolExecutor(max_workers=8)


class AskRequest(BaseModel):
    tenant_id: str
    question: str
    conversation_id: str | None = None


class SweepRequest(BaseModel):
    question: str


class RunSqlRequest(BaseModel):
    tenant_id: str
    sql: str


@router.post('/ask', response_model=AskResponse)
async def ask(req: AskRequest, inspect: bool = False, transport: str | None = None) -> AskResponse:
    try:
        t = genie_service.resolve_transport(transport)
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            _pool,
            functools.partial(
                genie_service.ask,
                req.tenant_id, req.question, req.conversation_id,
                inspect=inspect, transport=t,
            ),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post('/sweep', response_model=list[AskResponse])
async def sweep(req: SweepRequest, transport: str | None = None) -> list[AskResponse]:
    try:
        t = genie_service.resolve_transport(transport)
        tenants = [t_ for t_ in runtime.manager().list_tenants() if t_.status == 'active']
        loop = asyncio.get_event_loop()
        futures = [
            loop.run_in_executor(_pool, genie_service.ask_safe, tn.tenant_id, req.question, t)
            for tn in tenants
        ]
        results: list[AskResponse] = []
        for f in asyncio.as_completed(futures):
            results.append(await f)
        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post('/sql', response_model=RunSqlResponse)
async def run_sql(req: RunSqlRequest) -> RunSqlResponse:
    try:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            _pool, genie_service.run_sql, req.tenant_id, req.sql
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get('/embed', response_model=EmbedConfig)
async def embed_config(tenant_id: str, user: dict = Depends(current_user)) -> EmbedConfig:
    # Opaque, non-PII, stable-per-(user,tenant) audit id.
    raw = f"{user.get('email', 'anon')}::{tenant_id}".encode()
    viewer_id = "v_" + hashlib.sha256(raw).hexdigest()[:24]
    try:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            _pool, embed_service.embed_config, tenant_id, viewer_id
        )
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
