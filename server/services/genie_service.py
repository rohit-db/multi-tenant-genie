"""Ask-as-tenant orchestration: transport selection, the 6-step ask flow,
the sweep-safe variant, and direct SQL execution.

This is the use-case layer for the Genie experience. It owns *how* a question
becomes a tenant-scoped answer (resolve tenant -> mint SP token -> call Genie
over REST or Managed MCP -> audit), while the router above it only deals with
HTTP and the primitives below it only know one Databricks capability each.
"""
from __future__ import annotations

import os
import threading
import time

from pydantic import BaseModel

from server.lib.config import CONFIG
from server.lib.inspector import Inspector
from server.primitives.genie import GenieClient
from server.primitives.managed_mcp import GenieMCPClient
from server.services import runtime

# One client per transport, sharing the process-wide token minter so the REST
# and MCP paths reuse the same ~55-min token cache.
_client = GenieClient(runtime.minter())
_mcp_client = GenieMCPClient(runtime.minter())

# Genie rate-limits concurrent conversations (HTTP 429). The isolation sweep
# fans out one conversation per tenant, so throttle how many hit Genie at once.
_SWEEP_CONCURRENCY = int(os.getenv("MT_GENIE_SWEEP_CONCURRENCY", "3"))
_sweep_sem = threading.Semaphore(max(1, _SWEEP_CONCURRENCY))


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
    transport: str = "rest"
    deep_link: str | None = None
    inspector: dict | None = None


class RunSqlResponse(BaseModel):
    columns: list[str]
    rows: list[list]
    latency_ms: int


def resolve_transport(transport: str | None) -> str:
    """Per-request override falls back to the configured default."""
    t = (transport or CONFIG.transport or "rest").lower()
    return "mcp" if t == "mcp" else "rest"


def _genie_for(transport: str):
    return _mcp_client if transport == "mcp" else _client


def _lakebase_target() -> str:
    """Best-effort 'host:port/db' label for inspector code snippets."""
    host = os.environ.get("PGHOST", "localhost")
    port = os.environ.get("PGPORT", "5432")
    db = os.environ.get("PGDATABASE", "mtg")
    return f"{host}:{port}/{db}"


def ask(
    tenant_id: str,
    question: str,
    conversation_id: str | None = None,
    *,
    inspect: bool = False,
    transport: str = "rest",
) -> AskResponse:
    insp = Inspector() if inspect else None
    lakebase = _lakebase_target() if insp is not None else None
    workspace_host = CONFIG.host or "<workspace>"
    genie = _genie_for(transport)

    # Step 1: Authenticate — resolve tenant from Lakebase client_registry
    if insp is not None:
        with insp.step("Authenticate") as step:
            tenants = [t for t in runtime.manager().list_tenants() if t.tenant_id == tenant_id]
            if not tenants:
                raise ValueError(f'Tenant {tenant_id} not found')
            tenant = tenants[0]
            step.summary = (
                f"Tenant '{tenant.tenant_id}' found in client_registry "
                f"({tenant.status}, sp_app_id={tenant.sp_app_id[:12]}…)"
            )
            step.code_snippet = (
                "-- Lakebase: " + lakebase + "\n"
                "SELECT tenant_id, display_name, sp_app_id, sp_display_name,\n"
                "       status, genie_space_id, metadata,\n"
                "       created_at, updated_at\n"
                "FROM client_registry\n"
                "ORDER BY created_at DESC;"
            )
            step.payload_in = {"tenant_id": tenant_id}
            step.payload_out = {
                "tenant_id": tenant.tenant_id,
                "display_name": tenant.tenant_name,
                "sp_app_id": tenant.sp_app_id,
                "status": tenant.status,
            }
    else:
        tenants = [t for t in runtime.manager().list_tenants() if t.tenant_id == tenant_id]
        if not tenants:
            raise ValueError(f'Tenant {tenant_id} not found')
        tenant = tenants[0]

    # Step 2: Resolve tenant — pick the Genie space for this tenant
    if insp is not None:
        with insp.step("Resolve tenant") as step:
            space_id = CONFIG.genie_space_id  # per-tenant override is Phase-2-future
            step.summary = (
                f"genie_space_id={space_id[:12]}… (workspace global; per-tenant "
                f"override unset)"
            )
            step.code_snippet = (
                "# Per-tenant override:\n"
                "space_id = tenant.genie_space_id or CONFIG.genie_space_id\n"
                "# (no extra query — row already fetched in step 1)"
            )
            step.payload_out = {
                "genie_space_id_override": None,
                "genie_space_id_resolved": space_id,
            }
    else:
        space_id = CONFIG.genie_space_id

    # Step 3: Mint token — OAuth M2M against /oidc/v1/token
    if insp is not None:
        with insp.step("Mint token") as step:
            secret = runtime.secret_for_sp(tenant.sp_app_id)
            if not secret:
                raise ValueError(
                    f"No credential stored for tenant {tenant_id}. "
                    "Rotate on the Admin tab to regenerate."
                )
            step.summary = (
                f"Exchange tenant SP client_id+secret at "
                f"{workspace_host.replace('https://', '')}/oidc/v1/token "
                "(cache-aware, ~55min TTL)"
            )
            step.code_snippet = (
                f"POST {workspace_host}/oidc/v1/token\n"
                "Authorization: Basic <base64(client_id:client_secret)>\n"
                "Content-Type: application/x-www-form-urlencoded\n\n"
                "grant_type=client_credentials&scope=all-apis"
            )
            step.payload_in = {
                "client_id": tenant.sp_app_id,
                "client_secret": "<from sp_credentials, AES-GCM decrypted>",
            }
            step.payload_out = {
                "access_token": "<JWT>",
                "expires_in": "~3300 (TTL)",
            }
    else:
        secret = runtime.secret_for_sp(tenant.sp_app_id)
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
                f"In-warehouse: when this SP queries bookings/customers, UC "
                f"runs tenant_row_filter(tenant_id) joining sp_tenant_mapping "
                f"on session_user()={tenant.sp_app_id[:12]}… → keeps only "
                f"rows where tenant_id='{tenant.tenant_id}'."
            ),
            code_snippet=(
                f"-- UC: {CONFIG.catalog}.{CONFIG.schema}.tenant_row_filter\n"
                f"-- Function deployed once at setup, applied to every\n"
                f"-- governed table via ALTER TABLE … SET ROW FILTER.\n"
                "CREATE OR REPLACE FUNCTION tenant_row_filter(tenant_id STRING)\n"
                "RETURN\n"
                f"  is_account_group_member('{CONFIG.admin_group}')\n"
                "  OR EXISTS (\n"
                "    SELECT 1\n"
                "    FROM sp_tenant_mapping m\n"
                "    WHERE m.sp_app_id = session_user()\n"
                "      AND m.active = true\n"
                "      AND m.tenant_id = tenant_row_filter.tenant_id\n"
                "  );"
            ),
        )

    # Step 5: Ask Genie — REST Conversation API or managed MCP, same SP token.
    step_name = "Ask Genie (MCP)" if transport == "mcp" else "Ask Genie"
    if insp is not None:
        with insp.step(step_name) as step:
            resp = genie.ask(
                space_id=space_id, question=question,
                client_id=tenant.sp_app_id, client_secret=secret,
                conversation_id=conversation_id, timeout_s=120,
            )
            step.summary = (
                f"[{transport}] Genie status={resp.status}; rows={len(resp.rows)}; "
                f"cols={len(resp.columns)}; latency={resp.latency_ms} ms"
            )
            if transport == "mcp":
                step.code_snippet = (
                    f"# Managed MCP server (same tenant SP token from step 3)\n"
                    f"server = {workspace_host}/api/2.0/mcp/genie/{space_id}\n"
                    "client = DatabricksMCPClient(server_url=server,\n"
                    "             workspace_client=WorkspaceClient(token=<sp-jwt>))\n"
                    f"client.call_tool('query_space_{space_id[:8]}…',\n"
                    f"                 {{'query': '{question[:60]}{'…' if len(question) > 60 else ''}'}})\n"
                    "# poll_response_… until COMPLETED. UC row filter still\n"
                    "# trims to this tenant because session_user() == the SP."
                )
            else:
                step.code_snippet = (
                    f"POST {workspace_host}/api/2.0/genie/spaces/{space_id}/start-conversation\n"
                    "Authorization: Bearer <jwt-from-step-3>\n\n"
                    "{\n"
                    f'  "content": "{question[:80]}{"…" if len(question) > 80 else ""}"\n'
                    "}\n"
                    "# Genie generates SQL → warehouse executes → row filter\n"
                    "# trims to this tenant's rows → response returns."
                )
            step.payload_in = {
                "transport": transport,
                "space_id": space_id,
                "content": question,
                "conversation_id": conversation_id,
            }
            step.payload_out = {
                "status": resp.status,
                "row_count": len(resp.rows),
                "column_count": len(resp.columns),
                "sql": resp.sql,
                "deep_link": getattr(resp, "deep_link", None),
            }
    else:
        resp = genie.ask(
            space_id=space_id, question=question,
            client_id=tenant.sp_app_id, client_secret=secret,
            conversation_id=conversation_id, timeout_s=120,
        )

    # Step 6: Audit (best-effort) — INSERT into audit_log
    if insp is not None:
        with insp.step("Audit") as step:
            audit_status = 'ok' if resp.status == 'COMPLETED' else 'error'
            try:
                runtime.manager()._audit(
                    'query', tenant.tenant_id, tenant.sp_app_id,
                    question=resp.question, latency_ms=resp.latency_ms,
                    status=audit_status,
                    detail=None if resp.status == 'COMPLETED' else f'genie_status={resp.status}',
                )
                step.summary = (
                    f"audit_log row appended (action=query, status={audit_status}, "
                    f"latency_ms={resp.latency_ms})"
                )
                step.code_snippet = (
                    "-- Lakebase: " + lakebase + "\n"
                    "INSERT INTO audit_log\n"
                    "  (tenant_id, actor, action, sp_app_id, question,\n"
                    "   status, latency_ms, detail)\n"
                    "VALUES\n"
                    "  (%s, %s, 'query', %s, %s,\n"
                    "   %s, %s, %s);"
                )
                step.payload_in = {
                    "tenant_id": tenant.tenant_id,
                    "action": "query",
                    "status": audit_status,
                    "latency_ms": resp.latency_ms,
                }
            except Exception as e:
                step.summary = f"audit failed (non-fatal): {e}"
                step.code_snippet = "-- Lakebase: " + lakebase
    else:
        try:
            runtime.manager()._audit(
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
        transport=getattr(resp, "transport", transport),
        deep_link=getattr(resp, "deep_link", None),
        inspector=insp.build() if insp is not None else None,
    )


def ask_safe(tenant_id: str, question: str, transport: str = "rest") -> AskResponse:
    """Sweep-friendly variant: never raises. Returns a FAILED stub on error.

    Throttled by ``_sweep_sem`` and retried on Genie's HTTP 429 so a parallel
    fan-out across tenants doesn't trip the rate limiter.
    """
    try:
        with _sweep_sem:
            last_exc: Exception | None = None
            for attempt in range(3):
                try:
                    return ask(tenant_id, question, transport=transport)
                except Exception as e:  # noqa: BLE001
                    last_exc = e
                    if "429" in str(e) or "Too Many Requests" in str(e):
                        time.sleep(2 * (attempt + 1))
                        continue
                    raise
            raise last_exc  # type: ignore[misc]
    except Exception as e:
        tenant_name = tenant_id
        sp_app_id = ''
        try:
            for t in runtime.manager().list_tenants():
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


def run_sql(tenant_id: str, sql: str) -> RunSqlResponse:
    """Execute SQL directly as the tenant SP — deterministic dashboard widgets.

    The SQL goes through the warehouse using the tenant's OAuth token, so the
    UC row filter applies the same way it does for Genie. Genie isn't in the
    loop here.
    """
    import requests

    started = time.time()

    tenants = [t for t in runtime.manager().list_tenants() if t.tenant_id == tenant_id]
    if not tenants:
        raise ValueError(f'Tenant {tenant_id} not found')
    tenant = tenants[0]

    secret = runtime.secret_for_sp(tenant.sp_app_id)
    if not secret:
        raise ValueError(
            f'No credential stored for tenant {tenant_id}. '
            'Rotate on the Admin tab to regenerate.'
        )

    token = runtime.minter().get_token(tenant.sp_app_id, secret)
    host = (CONFIG.host or '').rstrip('/')
    warehouse_id = runtime.manager().warehouse_id

    r = requests.post(
        f'{host}/api/2.0/sql/statements',
        headers={'Authorization': f'Bearer {token}'},
        json={
            'warehouse_id': warehouse_id,
            'statement': sql,
            'wait_timeout': '30s',
        },
        timeout=60,
    )
    r.raise_for_status()
    body = r.json()

    statement_id = body.get('statement_id')
    while body.get('status', {}).get('state') in ('PENDING', 'RUNNING'):
        time.sleep(0.5)
        rr = requests.get(
            f'{host}/api/2.0/sql/statements/{statement_id}',
            headers={'Authorization': f'Bearer {token}'},
            timeout=30,
        )
        rr.raise_for_status()
        body = rr.json()

    state = body.get('status', {}).get('state')
    if state != 'SUCCEEDED':
        err = body.get('status', {}).get('error', {})
        raise RuntimeError(f'SQL failed ({state}): {err.get("message", str(err))}')

    manifest = body.get('manifest') or {}
    schema = manifest.get('schema') or {}
    columns = [c.get('name', '') for c in schema.get('columns', []) or []]
    result = body.get('result') or {}
    rows = result.get('data_array') or []

    return RunSqlResponse(
        columns=columns,
        rows=rows,
        latency_ms=int((time.time() - started) * 1000),
    )
