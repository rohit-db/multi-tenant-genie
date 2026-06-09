"""Unit tests for the managed-MCP Genie transport.

No live workspace: we mock ``DatabricksMCPClient`` and the token minter, and
feed in the real payload shapes captured from the live server (dynamic tool
names, ASKING_AI → COMPLETED, typed-value data_array).
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest import mock

import pytest

from server.primitives import managed_mcp as mc
from server.primitives.managed_mcp import (
    GenieMCPClient,
    _find_tool,
    _flatten_row,
    _parse_content,
)

SPACE = "01f1548548a6155ea15accf34b1bc5e6"
QTOOL = f"query_space_{SPACE}"
PTOOL = f"poll_response_{SPACE}"


def _tool(name: str):
    return SimpleNamespace(name=name, description="", inputSchema={})


def _content(text: str):
    return SimpleNamespace(content=[SimpleNamespace(text=text)])


# --------------------------------------------------------------------------- #
# pure helpers
# --------------------------------------------------------------------------- #

def test_find_tool_by_prefix():
    tools = [_tool(QTOOL), _tool(PTOOL)]
    assert _find_tool(tools, "query_space") == QTOOL
    assert _find_tool(tools, "poll_response") == PTOOL
    assert _find_tool(tools, "nope") is None


def test_flatten_row_typed_values():
    raw = {"values": [{"string_value": "1193"}, {"string_value": "acme"}]}
    assert _flatten_row(raw) == ["1193", "acme"]


def test_flatten_row_plain_list_and_scalar():
    assert _flatten_row([1, 2, 3]) == [1, 2, 3]
    assert _flatten_row("x") == ["x"]


def test_parse_content_extracts_answer_sql_rows():
    content = {
        "textAttachments": ["There are **410 bookings**."],
        "queryAttachments": [
            {
                "query": "SELECT COUNT(*) AS total FROM bookings",
                "statement_response": {
                    "manifest": {"schema": {"columns": [{"name": "total"}]}},
                    "result": {"data_array": [{"values": [{"string_value": "410"}]}]},
                },
            }
        ],
    }
    answer, sql, cols, rows = _parse_content(content)
    assert "410 bookings" in answer
    assert sql == "SELECT COUNT(*) AS total FROM bookings"
    assert cols == ["total"]
    assert rows == [["410"]]


# --------------------------------------------------------------------------- #
# end-to-end ask() with mocked MCP client + minter
# --------------------------------------------------------------------------- #

@pytest.fixture
def patched(monkeypatch):
    """Patch the token minter and DatabricksMCPClient used inside ask()."""
    fake_mcp = mock.MagicMock()
    fake_mcp.list_tools.return_value = [_tool(QTOOL), _tool(PTOOL)]

    ask_payload = {
        "content": {"textAttachments": ["processing"], "queryAttachments": []},
        "conversationId": "conv1",
        "messageId": "msg1",
        "status": "ASKING_AI",
    }
    done_payload = {
        "content": {
            "textAttachments": ["There are **410 bookings**."],
            "queryAttachments": [
                {
                    "query": "SELECT COUNT(*) FROM bookings",
                    "statement_response": {
                        "manifest": {"schema": {"columns": [{"name": "c"}]}},
                        "result": {"data_array": [{"values": [{"string_value": "410"}]}]},
                    },
                }
            ],
        },
        "conversationId": "conv1",
        "messageId": "msg1",
        "status": "COMPLETED",
    }

    def call_tool(name, args):
        if name.startswith("query_space"):
            return _content(json.dumps(ask_payload))
        return _content(json.dumps(done_payload))

    fake_mcp.call_tool.side_effect = call_tool

    # Patch the lazily-imported symbol and the WorkspaceClient + minter.
    monkeypatch.setattr(
        "databricks_mcp.DatabricksMCPClient", lambda **kw: fake_mcp, raising=False
    )
    monkeypatch.setattr(mc, "WorkspaceClient", lambda **kw: object())
    return fake_mcp


def test_ask_polls_to_completion(patched):
    client = GenieMCPClient(host="https://example.cloud.databricks.com")
    client.minter = mock.MagicMock()
    client.minter.get_token.return_value = "tok"

    resp = client.ask(
        space_id=SPACE, question="how many bookings?",
        client_id="cid", client_secret="sec", poll_interval=0,
    )

    assert resp.status == "COMPLETED"
    assert resp.transport == "mcp"
    assert resp.sql == "SELECT COUNT(*) FROM bookings"
    assert resp.rows == [["410"]]
    assert resp.columns == ["c"]
    assert "410 bookings" in resp.answer_text
    assert resp.conversation_id == "conv1"
    assert resp.deep_link.endswith(f"/genie/rooms/{SPACE}")
    # query_space + at least one poll_response
    assert patched.call_tool.call_count >= 2


def test_ask_continues_conversation(patched):
    client = GenieMCPClient(host="https://example.cloud.databricks.com")
    client.minter = mock.MagicMock()
    client.minter.get_token.return_value = "tok"

    client.ask(
        space_id=SPACE, question="follow up",
        client_id="cid", client_secret="sec",
        conversation_id="prev-conv", poll_interval=0,
    )
    # First call is the query_space tool; conversation_id must be forwarded.
    first_name, first_args = patched.call_tool.call_args_list[0].args
    assert first_name.startswith("query_space")
    assert first_args["conversation_id"] == "prev-conv"
    assert first_args["query"] == "follow up"
