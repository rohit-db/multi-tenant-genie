"""Edge gateway FastAPI app.

Run locally with:

    uvicorn edge.app:app --reload --port 9000

It owns no UI of its own (the SPA stays served by the Databricks App). It is a
thin, transparent reverse proxy that injects the edge SP bearer and shuttles
the app session cookie through. See ``docs/edge-gateway.md``.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from edge.broker import broker
from edge.config import CONFIG
from edge import proxy

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("edge")


@asynccontextmanager
async def lifespan(app: FastAPI):
    missing = CONFIG.missing()
    if missing:
        logger.warning(
            "Edge starting with missing config: %s — proxied requests will "
            "fail until these are set in edge/.env.",
            ", ".join(missing),
        )
    else:
        logger.info(
            "Edge front door -> %s (workspace OIDC %s, SP %s)",
            CONFIG.upstream,
            CONFIG.workspace_host,
            CONFIG.sp_client_id,
        )
    yield
    await proxy.aclose()


app = FastAPI(title="Multi-Tenant Genie — Edge Gateway", lifespan=lifespan)


@app.get("/__edge/health")
async def health() -> JSONResponse:
    """Edge's own health — does NOT touch upstream. Reports config readiness
    and whether the edge SP token can be minted.
    """
    missing = CONFIG.missing()
    token_ok, token_err = False, None
    if not missing:
        try:
            broker.bearer()
            token_ok = True
        except Exception as e:  # noqa: BLE001
            token_err = str(e)
    return JSONResponse(
        {
            "status": "healthy" if (not missing and token_ok) else "degraded",
            "upstream": CONFIG.upstream,
            "workspace_host": CONFIG.workspace_host,
            "sp_client_id": CONFIG.sp_client_id or None,
            "missing_config": missing,
            "edge_sp_token_mintable": token_ok,
            "edge_sp_token_error": token_err,
        }
    )


@app.api_route(
    "/{full_path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
)
async def gateway(request: Request, full_path: str) -> Response:
    return await proxy.proxy(request)
