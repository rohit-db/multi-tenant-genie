"""Custom-agent endpoint — same multi-tenant pattern, applied beyond Genie."""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from server.agent.insights import run_insights, run_insights_mcp
from server.lib.config import CONFIG

router = APIRouter()
_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="agent-insights")


class InsightsRequest(BaseModel):
    tenant_id: str
    focus: str


class InsightsResponse(BaseModel):
    tenant_id: str
    focus: str
    model: str
    transport: str = "rest"
    reasoning: str | None = None
    tool_calls: list[dict[str, Any]]
    recommendation: str


@router.post('/insights', response_model=InsightsResponse)
async def insights(req: InsightsRequest, transport: str | None = None) -> InsightsResponse:
    if not req.focus.strip():
        raise HTTPException(status_code=400, detail="focus is required")
    t = (transport or CONFIG.transport or "rest").lower()
    runner = run_insights_mcp if t == "mcp" else run_insights
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            _pool, runner, req.tenant_id, req.focus
        )
        return InsightsResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
