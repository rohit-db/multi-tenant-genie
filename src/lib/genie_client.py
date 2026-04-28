"""Tenant-scoped Genie Conversation API client.

Calls Genie as the tenant's Service Principal, using a token fetched by
:class:`TokenMinter`. The rest of the isolation story lives in Unity
Catalog: the SP's identity flows into ``session_user()``, which the row
filter uses to join against the mapping table.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

import requests

from .config import CONFIG
from .token_minter import TokenMinter

logger = logging.getLogger(__name__)


@dataclass
class GenieResponse:
    question: str
    answer_text: str | None = None
    sql: str | None = None
    rows: list[list] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)
    latency_ms: int = 0
    conversation_id: str | None = None
    message_id: str | None = None
    status: str = "COMPLETED"
    raw: dict[str, Any] = field(default_factory=dict)


class GenieClient:
    """Minimal Genie Conversation API wrapper."""

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
        token = self.minter.get_token(client_id, client_secret)
        headers = {"Authorization": f"Bearer {token}"}
        started = time.time()

        # Start or continue conversation
        if conversation_id:
            start = requests.post(
                f"{self.host}/api/2.0/genie/spaces/{space_id}/conversations/"
                f"{conversation_id}/messages",
                headers=headers,
                json={"content": question},
                timeout=30,
            )
        else:
            start = requests.post(
                f"{self.host}/api/2.0/genie/spaces/{space_id}/start-conversation",
                headers=headers,
                json={"content": question},
                timeout=30,
            )
        start.raise_for_status()
        body = start.json()
        conversation_id = body.get("conversation_id") or conversation_id
        message = body.get("message") or body
        message_id = message["id"]

        # Poll for completion
        deadline = started + timeout_s
        while True:
            if time.time() > deadline:
                raise TimeoutError("Genie did not return within timeout")
            r = requests.get(
                f"{self.host}/api/2.0/genie/spaces/{space_id}/conversations/"
                f"{conversation_id}/messages/{message_id}",
                headers=headers,
                timeout=30,
            )
            r.raise_for_status()
            msg = r.json()
            status = msg.get("status")
            if status in ("COMPLETED", "FAILED", "CANCELLED"):
                break
            time.sleep(poll_interval)

        rows: list[list] = []
        columns: list[str] = []
        sql: str | None = None
        answer_text: str | None = None
        final_status = msg.get("status", "UNKNOWN")

        for attachment in msg.get("attachments", []) or []:
            if "query" in attachment:
                q = attachment["query"]
                sql = q.get("query")
                # Fetch result
                attachment_id = attachment.get("attachment_id") or attachment.get("id")
                if attachment_id:
                    rr = requests.get(
                        f"{self.host}/api/2.0/genie/spaces/{space_id}/conversations/"
                        f"{conversation_id}/messages/{message_id}/attachments/"
                        f"{attachment_id}/query-result",
                        headers=headers,
                        timeout=60,
                    )
                    if rr.status_code == 200:
                        qr = rr.json()
                        sr = (qr.get("statement_response") or {})
                        manifest = sr.get("manifest") or {}
                        columns = [c["name"] for c in manifest.get("schema", {}).get("columns", [])]
                        data = (sr.get("result") or {}).get("data_array") or []
                        rows = data
            if "text" in attachment:
                answer_text = attachment["text"].get("content") or answer_text

        if final_status != "COMPLETED" and not answer_text:
            err = msg.get("error")
            if isinstance(err, dict):
                answer_text = (
                    err.get("message")
                    or err.get("error_message")
                    or err.get("text")
                    or str(err)
                )
            elif isinstance(err, str):
                answer_text = err
            if not answer_text:
                answer_text = f"Genie returned status {final_status}"

        return GenieResponse(
            question=question,
            answer_text=answer_text,
            sql=sql,
            rows=rows,
            columns=columns,
            latency_ms=int((time.time() - started) * 1000),
            conversation_id=conversation_id,
            message_id=message_id,
            status=final_status,
            raw=msg,
        )

    # -------------------------------------------------- whoami / sanity check
    def whoami(self, *, client_id: str, client_secret: str) -> dict:
        """Call /api/2.0/preview/scim/v2/Me to prove which SP we're acting as."""
        token = self.minter.get_token(client_id, client_secret)
        r = requests.get(
            f"{self.host}/api/2.0/preview/scim/v2/Me",
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
        r.raise_for_status()
        return r.json()
