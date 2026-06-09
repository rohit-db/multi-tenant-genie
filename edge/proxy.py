"""Transparent reverse proxy with edge-SP bearer injection.

The browser only ever talks to the edge origin. For every request the edge:

  1. forwards method + path + query + body + cookies upstream to the
     Databricks App, unchanged;
  2. injects ``Authorization: Bearer <edge-sp-token>`` so the Apps OAuth
     proxy admits the request (the end user never sees Databricks SSO);
  3. relays the response back, rewriting ``Set-Cookie`` (drop ``Secure`` for
     local http, drop upstream ``Domain``) and any ``Location`` that points
     at the upstream host so redirects stay on the edge origin.

App identity is unchanged: the app's own ``mtg_session`` cookie rides through
in both directions, so login / tenant binding / the per-tenant SP data path
all keep working exactly as they do standalone. The edge bearer is purely the
"get past the front door" credential; the cookie is the "who is this user"
credential.
"""
from __future__ import annotations

import logging
from urllib.parse import urlsplit, urlunsplit

import httpx
from fastapi import Request
from fastapi.responses import Response

from edge.broker import broker
from edge.config import CONFIG

logger = logging.getLogger("edge.proxy")

# Hop-by-hop headers must not be forwarded (RFC 7230 §6.1). We also drop
# Host (httpx sets it from the upstream URL) and any inbound Authorization
# (the edge owns that header).
_HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade",
    "host", "content-length", "authorization",
}

# One shared async client; follow_redirects=False so we can rewrite Location
# and let the SPA / browser drive navigation.
_client = httpx.AsyncClient(timeout=httpx.Timeout(120.0), follow_redirects=False)


async def aclose() -> None:
    await _client.aclose()


def _filter_request_headers(headers) -> dict[str, str]:
    out = {}
    for k, v in headers.items():
        if k.lower() in _HOP_BY_HOP:
            continue
        out[k] = v
    return out


def _rewrite_set_cookie(value: str) -> str:
    """Drop attributes that break a cookie set over http://localhost via the
    edge: ``Secure`` (no https locally) and the upstream ``Domain``.
    """
    parts = [p.strip() for p in value.split(";")]
    kept = []
    for p in parts:
        low = p.lower()
        if CONFIG.rewrite_secure_cookies and low == "secure":
            continue
        if low.startswith("domain="):
            continue
        kept.append(p)
    return "; ".join(kept)


def _rewrite_location(value: str, edge_origin: str) -> str:
    """If the upstream redirects to its own host, swap it for the edge origin
    so the browser stays on the edge.
    """
    up = urlsplit(CONFIG.upstream)
    loc = urlsplit(value)
    if loc.scheme and loc.netloc and (loc.scheme, loc.netloc) == (up.scheme, up.netloc):
        edge = urlsplit(edge_origin)
        return urlunsplit((edge.scheme, edge.netloc, loc.path, loc.query, loc.fragment))
    return value


def _filter_response_headers(resp: httpx.Response, edge_origin: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for k, v in resp.headers.multi_items():
        low = k.lower()
        if low in _HOP_BY_HOP or low == "content-encoding":
            # content-encoding dropped: httpx already decoded resp.content.
            continue
        if low == "set-cookie":
            out.append((k, _rewrite_set_cookie(v)))
        elif low == "location":
            out.append((k, _rewrite_location(v, edge_origin)))
        else:
            out.append((k, v))
    return out


async def proxy(request: Request) -> Response:
    """Forward one request upstream with the edge SP bearer injected."""
    url = f"{CONFIG.upstream}{request.url.path}"
    if request.url.query:
        url = f"{url}?{request.url.query}"

    headers = _filter_request_headers(request.headers)
    try:
        headers["Authorization"] = f"Bearer {broker.bearer()}"
    except Exception as e:  # noqa: BLE001
        logger.error("Edge SP token mint failed: %s", e)
        return Response(
            content=f"edge: could not mint SP token: {e}",
            status_code=502,
            media_type="text/plain",
        )

    body = await request.body()

    try:
        upstream = await _client.request(
            request.method, url, headers=headers, content=body
        )
    except httpx.RequestError as e:
        logger.error("Upstream request failed: %s", e)
        return Response(
            content=f"edge: upstream unreachable: {e}",
            status_code=502,
            media_type="text/plain",
        )

    edge_origin = f"{request.url.scheme}://{request.headers.get('host', '')}"
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        headers=dict(_filter_response_headers(upstream, edge_origin)),
    )
