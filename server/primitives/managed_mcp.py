"""Tenant-scoped Genie client over the Databricks **managed MCP** server.

Drop-in alternative transport for :class:`server.primitives.genie.GenieClient`.
Instead of hand-rolling the Genie Conversation REST API, this talks to the
managed MCP server at ``/api/2.0/mcp/genie/{space_id}`` using the
``databricks-mcp`` client.

The isolation story is **unchanged**: we still present the tenant Service
Principal's OAuth token, so ``session_user()`` inside the warehouse resolves to
the SP and the Unity Catalog row filter trims to that tenant's rows. Managed
MCP only ever enforces the permissions of the token it is handed — it is a
transport + reasoning layer, not an isolation mechanism.

Notes on the live contract (probed against a real workspace):
- The single-space server exposes **dynamically named** tools:
  ``query_space_<space_id>`` and ``poll_response_<space_id>``. We discover them
  by prefix rather than hardcoding names.
- ``query_space`` takes ``{"query": str, "conversation_id"?: str}`` and returns
  ``{"content": {...}, "conversationId", "messageId", "status"}``. Status starts
  at ``ASKING_AI``; poll ``poll_response`` with ``conversation_id`` +
  ``message_id`` until ``COMPLETED`` / ``FAILED`` / ``CANCELLED``.
- Result rows arrive as typed value objects
  (``data_array: [{"values": [{"string_value": ...}]}]``) which we flatten.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

from databricks.sdk import WorkspaceClient

from server.lib.config import CONFIG
from .genie import GenieResponse
from .identity import TokenMinter

logger = logging.getLogger(__name__)

_TERMINAL = {"COMPLETED", "FAILED", "CANCELLED"}


class GenieMCPClient:
    """Genie client that speaks managed MCP, as the tenant SP."""

    def __init__(self, minter: TokenMinter | None = None, host: str | None = None):
        self.host = (host or CONFIG.host).rstrip("/")
        self.minter = minter or TokenMinter(self.host)

    def ask(
        self,
        *,
        space_id: str,
        question: str,
        client_id: str,
        client_secret: str,
        conversation_id: str | None = None,
        poll_interval: float = 1.5,
        timeout_s: int = 120,
    ) -> GenieResponse:
        started = time.time()

        # Present the tenant SP token to the MCP server. session_user() == SP.
        token = self.minter.get_token(client_id, client_secret)
        # auth_type="pat" forces token-only auth. Critical inside Databricks
        # Apps, where ambient DATABRICKS_CLIENT_ID/SECRET (the *app* SP) would
        # otherwise collide with this explicit *tenant* token and the SDK
        # raises "more than one authorization method configured".
        ws = WorkspaceClient(host=self.host, token=token, auth_type="pat")
        server_url = f"{self.host}/api/2.0/mcp/genie/{space_id}"

        # Imported lazily so the REST-only path has no hard dep on databricks-mcp.
        from databricks_mcp import DatabricksMCPClient

        client = DatabricksMCPClient(server_url=server_url, workspace_client=ws)

        try:
            tools = client.list_tools()
        except BaseException as e:  # noqa: BLE001
            real = _unwrap_exc(e)
            raise RuntimeError(f"MCP list_tools failed at {server_url}: {real}") from real
        query_tool = _find_tool(tools, "query_space")
        poll_tool = _find_tool(tools, "poll_response")
        if not query_tool:
            raise RuntimeError(
                f"Genie MCP server exposed no query_space tool at {server_url}; "
                f"got {[t.name for t in tools]}"
            )

        # Start (or continue) the conversation.
        args: dict[str, Any] = {"query": question}
        if conversation_id:
            args["conversation_id"] = conversation_id
        body = _call_json(client, query_tool, args)

        conversation_id = body.get("conversationId") or conversation_id
        message_id = body.get("messageId")
        status = body.get("status") or "UNKNOWN"

        # Poll to completion.
        deadline = started + timeout_s
        while status not in _TERMINAL:
            if time.time() > deadline:
                raise TimeoutError("Genie (MCP) did not return within timeout")
            if not (poll_tool and conversation_id and message_id):
                break
            time.sleep(poll_interval)
            body = _call_json(
                client,
                poll_tool,
                {"conversation_id": conversation_id, "message_id": message_id},
            )
            status = body.get("status") or status
            conversation_id = body.get("conversationId") or conversation_id
            message_id = body.get("messageId") or message_id

        answer_text, sql, columns, rows = _parse_content(body.get("content") or {})

        if status != "COMPLETED" and not answer_text:
            answer_text = f"Genie returned status {status}"

        return GenieResponse(
            question=question,
            answer_text=answer_text,
            sql=sql,
            rows=rows,
            columns=columns,
            latency_ms=int((time.time() - started) * 1000),
            conversation_id=conversation_id,
            message_id=message_id,
            status=status,
            raw=body,
            transport="mcp",
            deep_link=f"{self.host}/genie/rooms/{space_id}",
        )


# --------------------------------------------------------------------------- #
# Helpers (module-level so they're unit-testable without a live server)
# --------------------------------------------------------------------------- #

def _find_tool(tools: list, prefix: str) -> str | None:
    for t in tools:
        if t.name.startswith(prefix):
            return t.name
    return None


def _unwrap_exc(e: BaseException) -> BaseException:
    """anyio surfaces failures as ``ExceptionGroup`` ("unhandled errors in a
    TaskGroup"). Drill into the group so callers see the real cause
    (permission denied, timeout, etc.) instead of an opaque wrapper."""
    seen = set()
    while True:
        excs = getattr(e, "exceptions", None)
        if not excs or id(e) in seen:
            return e
        seen.add(id(e))
        e = excs[0]


def _mcp_call(client, tool_name: str, args: dict[str, Any]):
    try:
        return client.call_tool(tool_name, args)
    except BaseException as e:  # noqa: BLE001 — unwrap & re-raise with a clear msg
        real = _unwrap_exc(e)
        raise RuntimeError(f"MCP tool '{tool_name}' failed: {real}") from real


def _call_json(client, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Call an MCP tool and parse its text content as JSON."""
    resp = _mcp_call(client, tool_name, args)
    text = "".join(getattr(c, "text", "") for c in (resp.content or []))
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return {"status": "FAILED", "content": {"textAttachments": [text]}}
    return parsed if isinstance(parsed, dict) else {"content": {}}


def _parse_content(
    content: dict[str, Any],
) -> tuple[str | None, str | None, list[str], list[list]]:
    """Normalize an MCP Genie ``content`` block into our response fields."""
    text_attachments = content.get("textAttachments") or []
    answer_text = "\n\n".join(t for t in text_attachments if t) or None

    sql: str | None = None
    columns: list[str] = []
    rows: list[list] = []

    for qa in content.get("queryAttachments") or []:
        if sql is None:
            sql = qa.get("query")
        sr = qa.get("statement_response") or {}
        manifest = sr.get("manifest") or {}
        schema = manifest.get("schema") or {}
        if not columns:
            columns = [c.get("name", "") for c in schema.get("columns", []) or []]
        result = sr.get("result") or {}
        for raw_row in result.get("data_array") or []:
            rows.append(_flatten_row(raw_row))

    return answer_text, sql, columns, rows


def _flatten_row(raw_row: Any) -> list:
    """data_array rows may be typed-value dicts or plain lists."""
    if isinstance(raw_row, dict) and "values" in raw_row:
        out: list = []
        for cell in raw_row.get("values") or []:
            if isinstance(cell, dict):
                # Pick whichever typed value is present.
                val = (
                    cell.get("string_value")
                    if "string_value" in cell
                    else next(iter(cell.values()), None)
                )
                out.append(val)
            else:
                out.append(cell)
        return out
    if isinstance(raw_row, list):
        return raw_row
    return [raw_row]
