"""Tests for server.lib.inspector — six-step request inspector."""
from __future__ import annotations

import time

from server.lib.inspector import Inspector


def test_records_six_steps_in_order():
    insp = Inspector()
    with insp.step("Authenticate") as step:
        step.summary = "API key matched tenant_id=acme"
        step.code_snippet = "tenants = list_tenants()"
    with insp.step("Resolve tenant") as step:
        step.summary = "Lakebase lookup OK"
    with insp.step("Mint token") as step:
        step.summary = "Cache hit"
    insp.add_static_step(
        "Apply row filter",
        summary="Filter resolves to tenant_id='acme'",
        code_snippet="CREATE OR REPLACE FUNCTION tenant_row_filter(...)",
    )
    with insp.step("Ask Genie") as step:
        step.summary = "Genie returned 1 row"
        time.sleep(0.01)  # ensure non-zero duration
    with insp.step("Audit") as step:
        step.summary = "audit_log row written"

    payload = insp.build()
    names = [s["name"] for s in payload["steps"]]
    assert names == [
        "Authenticate", "Resolve tenant", "Mint token",
        "Apply row filter", "Ask Genie", "Audit",
    ]
    # Every step has the keys downstream UI expects
    for s in payload["steps"]:
        assert {"n", "name", "duration_ms", "summary"}.issubset(s.keys())
    # The static step is duration_ms=0
    apply_step = next(s for s in payload["steps"] if s["name"] == "Apply row filter")
    assert apply_step["duration_ms"] == 0
    # Ask Genie picked up real duration
    ask_step = next(s for s in payload["steps"] if s["name"] == "Ask Genie")
    assert ask_step["duration_ms"] >= 5  # at least a few ms


def test_request_id_is_unique_per_inspector():
    a = Inspector()
    b = Inspector()
    assert a.request_id != b.request_id


def test_step_records_payloads_when_set():
    insp = Inspector()
    with insp.step("Mint token") as step:
        step.payload_in = {"client_id": "sp-acme"}
        step.payload_out = {"expires_in": 3600}
    payload = insp.build()
    step = payload["steps"][0]
    assert step["payload_in"] == {"client_id": "sp-acme"}
    assert step["payload_out"] == {"expires_in": 3600}


def test_step_capturing_exception_marks_step_error():
    insp = Inspector()
    try:
        with insp.step("Ask Genie"):
            raise RuntimeError("genie unreachable")
    except RuntimeError:
        pass
    payload = insp.build()
    step = payload["steps"][0]
    assert step["error"] == "genie unreachable"
