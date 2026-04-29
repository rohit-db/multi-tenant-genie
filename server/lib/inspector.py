"""Six-step request-flow inspector — accumulates per-step records and
emits a JSON-serializable payload for the UI's `Inspector` component.

Usage in the proxy code path:

    insp = Inspector()
    with insp.step("Authenticate") as step:
        step.summary = "..."
        step.code_snippet = "..."
        # ... do the work ...
    insp.add_static_step("Apply row filter", summary="...", code_snippet="...")
    payload = insp.build()
    return AskResponse(..., inspector=payload)
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class StepRecord:
    n: int
    name: str
    summary: Optional[str] = None
    code_snippet: Optional[str] = None
    payload_in: Optional[dict] = None
    payload_out: Optional[dict] = None
    duration_ms: int = 0
    error: Optional[str] = None


class _StepContext:
    def __init__(self, inspector: "Inspector", record: StepRecord):
        self.inspector = inspector
        self.record = record
        self._start: float = 0.0

    def __enter__(self) -> StepRecord:
        self._start = time.perf_counter()
        return self.record

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.record.duration_ms = int((time.perf_counter() - self._start) * 1000)
        if exc is not None:
            self.record.error = str(exc)
        # Don't suppress — we want the caller to see the original exception.
        return False


class Inspector:
    """Accumulator for the six-step inspector payload."""

    def __init__(self) -> None:
        self.request_id: str = uuid.uuid4().hex
        self._steps: list[StepRecord] = []

    def step(self, name: str) -> _StepContext:
        record = StepRecord(n=len(self._steps) + 1, name=name)
        self._steps.append(record)
        return _StepContext(self, record)

    def add_static_step(
        self,
        name: str,
        *,
        summary: Optional[str] = None,
        code_snippet: Optional[str] = None,
    ) -> None:
        """Record a step that doesn't have a runtime block (e.g. row filter)."""
        self._steps.append(StepRecord(
            n=len(self._steps) + 1,
            name=name,
            summary=summary,
            code_snippet=code_snippet,
            duration_ms=0,
        ))

    def build(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "steps": [
                {
                    "n": s.n,
                    "name": s.name,
                    "summary": s.summary,
                    "code_snippet": s.code_snippet,
                    "payload_in": s.payload_in,
                    "payload_out": s.payload_out,
                    "duration_ms": s.duration_ms,
                    "error": s.error,
                }
                for s in self._steps
            ],
        }
