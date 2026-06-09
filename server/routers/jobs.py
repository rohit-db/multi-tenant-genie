"""Job-status polling endpoint for the in-process bulk onboard runner."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from server.jobs.bulk_onboard import JobRunner

router = APIRouter()

_runner: JobRunner | None = None


def runner() -> JobRunner:
    """Lazy singleton — first caller wires it up to the SPManager."""
    global _runner
    if _runner is None:
        from server.services import runtime
        _runner = JobRunner(runtime.manager())
    return _runner


def _reset_for_tests() -> None:
    """Test helper: drop the singleton so the next call rebuilds it
    against whatever _mgr() now returns (e.g., a monkeypatched mock)."""
    global _runner
    _runner = None


class JobStatusResponse(BaseModel):
    job_id: str
    state: str
    total: int
    processed: int
    errors: list[dict[str, Any]]
    results: list[dict[str, Any]]


@router.get('/{job_id}', response_model=JobStatusResponse)
async def get_job(job_id: str) -> JobStatusResponse:
    s = runner().get_status(job_id)
    if s is None:
        raise HTTPException(status_code=404, detail=f"job_id {job_id} not found")
    return JobStatusResponse(
        job_id=s.job_id,
        state=s.state,
        total=s.total,
        processed=s.processed,
        errors=s.errors,
        results=s.results,
    )
