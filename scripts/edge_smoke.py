#!/usr/bin/env python3
"""Prove the edge SP token clears the Databricks Apps OAuth proxy.

This is the one genuinely-unknown hop in the Firefly edge pattern: can a
*Service Principal* OAuth M2M token call a Databricks App and be admitted by
the Apps OAuth proxy (instead of bounced to interactive SSO)?

Run it before standing up the full edge:

    set -a; source edge/.env; set +a
    python scripts/edge_smoke.py

It (1) mints the edge SP token at <EDGE_WORKSPACE_HOST>/oidc/v1/token, then
(2) hits the upstream app with and without that bearer, and reports whether
the bearer is what flips the result from "redirected to SSO / 401" to "200".
"""
from __future__ import annotations

import os
import sys

import requests


def _need(name: str) -> str:
    val = (os.environ.get(name) or "").strip()
    if not val:
        print(f"✗ {name} is not set. `set -a; source edge/.env; set +a` first.", file=sys.stderr)
        sys.exit(2)
    return val


def _classify(resp: requests.Response) -> str:
    loc = resp.headers.get("location", "")
    if resp.status_code in (301, 302, 303, 307, 308):
        if "oidc" in loc or "oauth" in loc or "login" in loc:
            return "redirect-to-sso"
        return f"redirect ({loc[:60]})"
    if resp.status_code == 401:
        return "unauthorized"
    if resp.status_code == 200:
        return "ok"
    return f"http {resp.status_code}"


def main() -> int:
    upstream = _need("EDGE_UPSTREAM_URL").rstrip("/")
    workspace = (os.environ.get("EDGE_WORKSPACE_HOST") or os.environ.get("MT_GENIE_HOST") or "").strip().rstrip("/")
    client_id = _need("EDGE_SP_CLIENT_ID")
    client_secret = _need("EDGE_SP_CLIENT_SECRET")
    if not workspace:
        print("✗ EDGE_WORKSPACE_HOST (or MT_GENIE_HOST) is not set.", file=sys.stderr)
        return 2

    scope = (os.environ.get("EDGE_OAUTH_SCOPE") or "all-apis").strip()

    # Probe paths: /health is unauthenticated in the app; demo-accounts is an
    # unauthenticated API helper. Both still sit behind the Apps OAuth proxy.
    probe = upstream + "/health"

    print(f"▸ Upstream:  {upstream}")
    print(f"▸ Workspace: {workspace}")
    print(f"▸ Edge SP:   {client_id}")
    print()

    # 1) Baseline: no bearer. Expect the Apps OAuth proxy to bounce us.
    base = requests.get(probe, allow_redirects=False, timeout=30)
    print(f"  without bearer -> {_classify(base)} (status {base.status_code})")

    # 2) Mint the edge SP token.
    print(f"▸ Minting edge SP token at {workspace}/oidc/v1/token (scope={scope})...")
    tok = requests.post(
        f"{workspace}/oidc/v1/token",
        data={"grant_type": "client_credentials", "scope": scope},
        auth=(client_id, client_secret),
        timeout=30,
    )
    if tok.status_code != 200:
        print(f"✗ Token mint failed ({tok.status_code}): {tok.text[:300]}", file=sys.stderr)
        return 1
    token = tok.json()["access_token"]
    print("  ✓ token minted")

    # 3) With bearer. This is the moment of truth.
    auth = requests.get(
        probe,
        headers={"Authorization": f"Bearer {token}"},
        allow_redirects=False,
        timeout=30,
    )
    verdict = _classify(auth)
    print(f"  with bearer    -> {verdict} (status {auth.status_code})")
    print()

    if verdict == "ok":
        print("✓ The edge SP token CLEARS the Apps OAuth proxy. The edge pattern works.")
        print(f"  body: {auth.text[:160]}")
        return 0

    print("✗ The edge SP token did NOT clear the proxy.")
    print("  Check that the edge SP has CAN_USE on the app:")
    print("    databricks apps get <app> | jq .  # confirm app + permissions")
    print("    # grant CAN_USE to the SP via the Apps UI or permissions API")
    if auth.headers.get("location"):
        print(f"  location: {auth.headers['location'][:120]}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
