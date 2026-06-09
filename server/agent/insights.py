"""A small custom agent — demonstrates the multi-tenant pattern beyond Genie.

The pattern is the same one Genie uses: a tool call (here, a SQL query) is
issued through the tenant's Service Principal token. UC's row filter is
deterministic and SQL-level, so it doesn't care whether the caller is
Genie, this proxy, or a custom LangGraph-style agent — every query is
transparently scoped to the tenant.

This is a simple 3-step pipeline:
    1. PLAN — LLM picks 2-3 SQL queries that would help answer the focus area
    2. EXECUTE — proxy runs each SQL as the tenant SP (same code path the
       dashboard widgets use)
    3. SYNTHESIZE — LLM produces an actionable recommendation grounded in
       the query results

Real-world agents can swap step 1 for an OpenAI Agents SDK / LangGraph
loop with multi-turn tool use; the isolation guarantee comes from the
SP token, not from the agent framework.

Hosting note: this code currently runs inside the multi-tenant-genie
proxy. The recommended pattern is to host the agent as its own Databricks
App and have the proxy POST to it with the tenant identity. The split is
a one-file lift — see docs/future-directions.md.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

from openai import OpenAI
from databricks.sdk import WorkspaceClient

from server.lib.config import CONFIG
from server.services.genie_service import run_sql as _run_sql_sync

logger = logging.getLogger(__name__)

_PLAN_MCP_SYSTEM = (
    "You are a data analyst agent that works ONLY by asking a Databricks Genie "
    "space natural-language questions. Given a focus area, decide on 2 or 3 "
    "specific natural-language questions to ask Genie that would help answer it. "
    "Return ONLY a JSON object — no prose, no markdown. Format:\n"
    '{\n'
    '  "reasoning": "one sentence on what you\'re looking for",\n'
    '  "questions": ["question 1", "question 2"]\n'
    "}\n"
    "Keep each question concrete and answerable from booking/customer data. "
    "Never ask more than 3 questions. Do NOT write SQL — Genie does that."
)

_DEFAULT_MODEL = "databricks-claude-sonnet-4"


def _llm_client() -> OpenAI:
    """OpenAI-compatible client for Databricks Foundation Models.

    Uses the app SP's identity (NOT the tenant's). The LLM call doesn't
    need tenant scoping — that happens inside each SQL tool call.
    """
    w = WorkspaceClient()
    auth = w.config.authenticate()
    if not auth or "Authorization" not in auth:
        raise RuntimeError("Could not get OAuth token for FM API")
    token = auth["Authorization"].replace("Bearer ", "")
    host = (CONFIG.host or "").rstrip("/")
    if not host:
        raise RuntimeError("MT_GENIE_HOST is not configured")
    return OpenAI(api_key=token, base_url=f"{host}/serving-endpoints")


def _model() -> str:
    return os.environ.get("AGENT_MODEL", _DEFAULT_MODEL)


def _schema_hint() -> str:
    return (
        f"Catalog/schema: {CONFIG.catalog}.{CONFIG.schema}\n"
        f"Tables (use fully-qualified names):\n"
        f"  {CONFIG.fq_bookings}(booking_id, tenant_id, traveler_name, "
        f"origin, destination, route, supplier, cabin_class, "
        f"amount_usd, booked_at)\n"
        f"  {CONFIG.fq_customers}(tenant_id, customer_segment, industry, "
        f"headquartered_in, active_travelers)\n"
        f"\n"
        f"A row filter is applied — every query is automatically scoped "
        f"to this tenant's rows. You don't need (and shouldn't add) a "
        f"WHERE tenant_id = '...' clause."
    )


_PLAN_SYSTEM = (
    "You are a data analyst agent. Given a focus area, decide on 2 or 3 "
    "specific Spark SQL queries (SELECT only) that would help answer it. "
    "Return ONLY a JSON object — no prose, no markdown. Format:\n"
    '{\n'
    '  "reasoning": "one sentence on what you\'re looking for",\n'
    '  "queries": [\n'
    '    {"name": "human-readable name", "sql": "SELECT ..."},\n'
    '    ...\n'
    '  ]\n'
    "}\n"
    "Keep queries simple and aggregate-focused. Always use fully-qualified "
    "table names. Never write more than 3 queries. Never use INSERT, UPDATE, "
    "DELETE, CREATE, DROP, ALTER, or MERGE."
)

_SYNTH_SYSTEM = (
    "You are a data analyst. Given the focus area and the results of "
    "queries, write a 2-3 sentence actionable recommendation. Cite "
    "specific numbers from the data. Be direct."
)


def run_insights(tenant_id: str, focus: str) -> dict[str, Any]:
    """Run the insights agent end-to-end for a tenant.

    Returns a dict with the LLM's reasoning, each tool call (SQL +
    columns + rows), and the final recommendation.
    """
    client = _llm_client()
    model = _model()

    # Step 1: PLAN — ask the LLM what to look at
    plan_resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": _PLAN_SYSTEM},
            {
                "role": "user",
                "content": f"{_schema_hint()}\n\nFocus area: {focus}",
            },
        ],
        max_tokens=800,
        temperature=0.2,
    )
    plan_raw = (plan_resp.choices[0].message.content or "").strip()
    plan = _parse_plan_json(plan_raw)
    queries = plan.get("queries", [])[:3]  # hard cap at 3 tool calls

    # Step 2: EXECUTE — run each SQL as the tenant SP
    tool_calls: list[dict[str, Any]] = []
    for q in queries:
        name = str(q.get("name", "query"))
        sql = str(q.get("sql", "")).strip().rstrip(";")
        if not sql or not _looks_safe(sql):
            tool_calls.append(
                {"name": name, "sql": sql, "error": "rejected (unsafe)"}
            )
            continue
        try:
            result = _run_sql_sync(tenant_id, sql)
            tool_calls.append(
                {
                    "name": name,
                    "sql": sql,
                    "columns": result.columns,
                    "rows": [list(r) for r in result.rows[:20]],
                    "row_count": len(result.rows),
                    "latency_ms": result.latency_ms,
                }
            )
        except Exception as e:
            tool_calls.append({"name": name, "sql": sql, "error": str(e)})

    # Step 3: SYNTHESIZE — LLM produces the recommendation
    synth_resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": _SYNTH_SYSTEM},
            {
                "role": "user",
                "content": (
                    f"Focus area: {focus}\n\n"
                    f"Tool call results (JSON):\n"
                    f"{json.dumps(tool_calls, default=str)[:8000]}\n\n"
                    f"Recommendation:"
                ),
            },
        ],
        max_tokens=400,
        temperature=0.4,
    )
    recommendation = (synth_resp.choices[0].message.content or "").strip()

    return {
        "tenant_id": tenant_id,
        "focus": focus,
        "model": model,
        "reasoning": plan.get("reasoning"),
        "tool_calls": tool_calls,
        "recommendation": recommendation,
    }


def run_insights_mcp(tenant_id: str, focus: str) -> dict[str, Any]:
    """MCP variant: the agent orchestrates the Genie **managed MCP** server.

    Same 3 steps, but every tool call is a natural-language question routed
    through ``/api/2.0/mcp/genie/{space_id}`` as the tenant SP. Genie writes
    and runs the SQL; the UC row filter scopes results to the tenant because
    ``session_user()`` is the SP. "Databricks + Genie MCP is all you need."
    """
    from server.primitives.managed_mcp import GenieMCPClient
    from server.services import runtime

    tenants = [t for t in runtime.manager().list_tenants() if t.tenant_id == tenant_id]
    if not tenants:
        raise ValueError(f"Tenant {tenant_id} not found")
    tenant = tenants[0]
    secret = runtime.secret_for_sp(tenant.sp_app_id)
    if not secret:
        raise ValueError(f"No credential stored for tenant {tenant_id}")

    client = _llm_client()
    model = _model()
    space_id = CONFIG.genie_space_id

    # Step 1: PLAN — LLM picks natural-language questions for Genie
    plan_resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": _PLAN_MCP_SYSTEM},
            {"role": "user", "content": f"Focus area: {focus}"},
        ],
        max_tokens=600,
        temperature=0.2,
    )
    plan = _parse_plan_json((plan_resp.choices[0].message.content or "").strip())
    questions = plan.get("questions", plan.get("queries", []))[:3]

    # Step 2: EXECUTE — ask Genie over MCP, as the tenant SP
    mcp = GenieMCPClient()
    tool_calls: list[dict[str, Any]] = []
    conversation_id: str | None = None
    for q in questions:
        question = q if isinstance(q, str) else str(q.get("sql") or q.get("name") or q)
        try:
            r = mcp.ask(
                space_id=space_id, question=question,
                client_id=tenant.sp_app_id, client_secret=secret,
                conversation_id=conversation_id, timeout_s=120,
            )
            conversation_id = r.conversation_id or conversation_id
            tool_calls.append({
                "name": question,
                "sql": r.sql,
                "columns": r.columns,
                "rows": [list(x) for x in r.rows[:20]],
                "row_count": len(r.rows),
                "answer": r.answer_text,
                "latency_ms": r.latency_ms,
                "deep_link": r.deep_link,
            })
        except Exception as e:
            tool_calls.append({"name": question, "error": str(e)})

    # Step 3: SYNTHESIZE
    synth_resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": _SYNTH_SYSTEM},
            {"role": "user", "content": (
                f"Focus area: {focus}\n\n"
                f"Genie answers (JSON):\n{json.dumps(tool_calls, default=str)[:8000]}\n\n"
                f"Recommendation:"
            )},
        ],
        max_tokens=400,
        temperature=0.4,
    )
    recommendation = (synth_resp.choices[0].message.content or "").strip()

    return {
        "tenant_id": tenant_id,
        "focus": focus,
        "model": model,
        "transport": "mcp",
        "reasoning": plan.get("reasoning"),
        "tool_calls": tool_calls,
        "recommendation": recommendation,
    }


def _parse_plan_json(raw: str) -> dict[str, Any]:
    """Best-effort JSON parse — strip code fences if present."""
    s = raw.strip()
    if s.startswith("```"):
        s = s.strip("`")
        if s.lower().startswith("json"):
            s = s[4:]
        s = s.strip()
    try:
        return json.loads(s)
    except Exception as e:
        logger.warning("Plan JSON parse failed: %s\n---\n%s", e, raw)
        return {"reasoning": "(model returned non-JSON)", "queries": []}


_FORBIDDEN_WORDS = {
    "insert", "update", "delete", "merge",
    "create", "drop", "alter", "truncate",
    "grant", "revoke",
}


def _looks_safe(sql: str) -> bool:
    """Reject anything that looks like a write or DDL.

    The row filter would block cross-tenant reads anyway, but this keeps
    the agent from running plausibly-bad SQL the LLM might emit.
    """
    lowered = sql.lower()
    if not lowered.lstrip().startswith(("select", "with")):
        return False
    # Cheap word-boundary check
    for word in _FORBIDDEN_WORDS:
        if f" {word} " in f" {lowered} " or f" {word};" in lowered:
            return False
    return True
