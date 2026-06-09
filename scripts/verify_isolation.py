"""End-to-end isolation test — no UI needed.

For each tenant SP:
    1. Mint an OAuth token via client_credentials.
    2. Confirm identity via /scim/v2/Me.
    3. Run SELECT COUNT(*) / SELECT DISTINCT tenant_id on the bookings
       table using the SQL Statement API with that token.
    4. Prove each SP sees only its own tenant's rows.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import requests

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from server.lib.config import CONFIG  # noqa: E402
from server.primitives.sp_manager import SPManager  # noqa: E402
from server.primitives.identity import TokenMinter  # noqa: E402


def _load_local_secrets() -> dict[str, str]:
    path = _REPO / ".demo-secrets.env"
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text().splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def run_sql_as(token: str, warehouse_id: str, sql: str) -> list[list]:
    host = CONFIG.host.rstrip("/")
    r = requests.post(
        f"{host}/api/2.0/sql/statements",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "warehouse_id": warehouse_id,
            "statement": sql,
            "wait_timeout": "30s",
        },
        timeout=60,
    )
    r.raise_for_status()
    body = r.json()
    statement_id = body["statement_id"]
    while body.get("status", {}).get("state") in ("PENDING", "RUNNING"):
        time.sleep(0.5)
        r = requests.get(
            f"{host}/api/2.0/sql/statements/{statement_id}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
        r.raise_for_status()
        body = r.json()
    state = body.get("status", {}).get("state")
    if state != "SUCCEEDED":
        raise RuntimeError(f"SQL failed: {body}")
    return (body.get("result") or {}).get("data_array") or []


def main() -> None:
    mgr = SPManager()
    secrets = _load_local_secrets()
    minter = TokenMinter()
    warehouse_id = mgr.warehouse_id

    print(f"Warehouse: {warehouse_id}\n")

    for tenant in mgr.list_tenants():
        secret_env = f"MT_GENIE_SECRET_{tenant.tenant_id.upper()}"
        secret = secrets.get(secret_env) or os.environ.get(secret_env)
        if not secret:
            print(f"!! no secret found for {tenant.tenant_id}")
            continue

        token = minter.get_token(tenant.sp_app_id, secret)

        # whoami
        me = requests.get(
            f"{CONFIG.host}/api/2.0/preview/scim/v2/Me",
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        ).json()

        # session_user()
        s_user = run_sql_as(token, warehouse_id, "SELECT session_user() AS u")

        # distinct tenant_ids visible
        distinct = run_sql_as(
            token,
            warehouse_id,
            f"SELECT DISTINCT tenant_id FROM {CONFIG.fq_bookings}",
        )

        # row count
        rowcount = run_sql_as(
            token, warehouse_id, f"SELECT COUNT(*) FROM {CONFIG.fq_bookings}"
        )

        print(f"== {tenant.tenant_name} ({tenant.tenant_id}) ==")
        print(f"   SCIM Me.display     : {me.get('displayName')}")
        print(f"   session_user()      : {s_user}")
        print(f"   distinct tenant_ids : {distinct}")
        print(f"   visible row count   : {rowcount}")
        print()


if __name__ == "__main__":
    main()
