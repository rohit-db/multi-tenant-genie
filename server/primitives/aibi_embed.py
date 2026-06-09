"""Mint scoped, browser-safe embed tokens for AI/BI (Lakeview) dashboards.

This implements the documented "embedding for external users" 3-step OAuth
exchange (https://docs.databricks.com/aws/en/dashboards/share/embedding/external-embed):

    1. Exchange the *tenant's* SP client_id/secret for a broadly-scoped
       ``all-apis`` OAuth token.
    2. Call the published dashboard's ``/tokeninfo`` endpoint with that token,
       passing the (non-PII) ``external_viewer_id`` and optional
       ``external_value`` so views are auditable / filterable.
    3. Re-POST to ``/oidc/v1/token`` echoing the tokeninfo fields to obtain a
       tightly-scoped token that is safe to hand to the browser SDK.

Crucially we mint with the *tenant's* SP credentials and publish the dashboard
WITHOUT embedded credentials (``embed_credentials=false``). That makes the
dashboard's warehouse queries execute as the tenant SP, so ``session_user()``
resolves to the SP and the existing Unity Catalog row filter applies unchanged
— the same isolation mechanism the Genie ask-path already proves.
"""
from __future__ import annotations

import base64
import json
import urllib.parse

import requests

_TIMEOUT = 30


def _basic_auth(client_id: str, client_secret: str) -> str:
    raw = f"{client_id}:{client_secret}".encode()
    return base64.b64encode(raw).decode()


def mint_embed_token(
    *,
    instance_url: str,
    client_id: str,
    client_secret: str,
    dashboard_id: str,
    external_viewer_id: str,
    external_value: str | None = None,
) -> str:
    """Return a scoped embed token for ``dashboard_id`` minted as the given SP.

    Raises ``requests.HTTPError`` on any failed leg of the exchange.
    """
    instance = instance_url.rstrip("/")
    basic = _basic_auth(client_id, client_secret)

    # 1) Broadly-scoped all-apis token for the SP.
    r1 = requests.post(
        f"{instance}/oidc/v1/token",
        headers={
            "Authorization": f"Basic {basic}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={"grant_type": "client_credentials", "scope": "all-apis"},
        timeout=_TIMEOUT,
    )
    r1.raise_for_status()
    oidc_token = r1.json()["access_token"]

    # 2) Token info scoped to this published dashboard + viewer.
    params = {"external_viewer_id": external_viewer_id}
    if external_value is not None:
        params["external_value"] = external_value
    token_info_url = (
        f"{instance}/api/2.0/lakeview/dashboards/{dashboard_id}/published/tokeninfo"
        f"?{urllib.parse.urlencode(params)}"
    )
    r2 = requests.get(
        token_info_url,
        headers={"Authorization": f"Bearer {oidc_token}"},
        timeout=_TIMEOUT,
    )
    r2.raise_for_status()
    token_info = r2.json()

    # 3) Re-issue as a tightly-scoped, browser-safe token.
    body = dict(token_info)
    authorization_details = body.pop("authorization_details", None)
    body["grant_type"] = "client_credentials"
    body["authorization_details"] = json.dumps(authorization_details)

    r3 = requests.post(
        f"{instance}/oidc/v1/token",
        headers={
            "Authorization": f"Basic {basic}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data=body,
        timeout=_TIMEOUT,
    )
    r3.raise_for_status()
    return r3.json()["access_token"]
