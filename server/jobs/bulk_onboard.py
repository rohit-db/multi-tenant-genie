"""In-process bulk-onboard job runner.

Exposes :class:`JobRunner` — submit a list of tenant specs, get back a
``job_id``, then poll ``get_status(job_id)`` for progress. Each onboard
runs on a worker thread; errors are captured per row, never raised at
the job-runner level.

This is intentionally minimal — for production-scale (10K+ tenants),
swap to a Databricks Job. The interface is small enough that the
swap is localized.
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class JobStatus:
    job_id: str
    state: str  # 'running' | 'completed'
    total: int
    processed: int
    errors: list[dict[str, Any]] = field(default_factory=list)
    results: list[dict[str, Any]] = field(default_factory=list)
    started_at: float = 0.0
    finished_at: Optional[float] = None


class JobRunner:
    """Thread-pool-backed bulk onboard runner.

    Not safe across multiple FastAPI worker processes. Single-process
    deployments only — which matches a Databricks App with one replica.
    """

    def __init__(self, mgr, max_workers: int = 5):
        self._mgr = mgr
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="bulk-onboard")
        self._lock = threading.Lock()
        self._jobs: dict[str, JobStatus] = {}

    def submit(self, tenants: list[dict[str, str]]) -> str:
        """Kick off onboarding for ``tenants``. Returns a job_id immediately."""
        job_id = uuid.uuid4().hex
        status = JobStatus(
            job_id=job_id,
            state="running",
            total=len(tenants),
            processed=0,
            started_at=time.time(),
        )
        with self._lock:
            self._jobs[job_id] = status

        def _run():
            futures = [
                self._pool.submit(self._onboard_one, t)
                for t in tenants
            ]
            for fut in futures:
                row = fut.result()  # never raises — _onboard_one captures
                with self._lock:
                    if row["ok"]:
                        status.results.append({
                            "tenant_id": row["tenant_id"],
                            "tenant_name": row["tenant_name"],
                            "sp_app_id": row["sp_app_id"],
                            "client_secret": row["client_secret"],
                        })
                    else:
                        status.errors.append({
                            "tenant_id": row["tenant_id"],
                            "error": row["error"],
                        })
                    status.processed += 1
            with self._lock:
                status.state = "completed"
                status.finished_at = time.time()

        # Run the orchestration on its own thread so submit() returns instantly.
        threading.Thread(target=_run, daemon=True, name=f"bulk-job-{job_id}").start()
        return job_id

    def get_status(self, job_id: str) -> Optional[JobStatus]:
        with self._lock:
            return self._jobs.get(job_id)

    # ---------------------------------------------------------------- internal
    def _onboard_one(self, t: dict[str, str]) -> dict[str, Any]:
        tenant_id = t["tenant_id"].strip().lower()
        tenant_name = t["tenant_name"].strip()
        try:
            result = self._mgr.onboard_tenant(tenant_id, tenant_name)
            try:
                self._mgr.grant_data_access([tenant_id])
            except Exception as e:
                logger.warning("grant_data_access(%s) failed: %s", tenant_id, e)
            try:
                self._mgr.grant_genie_access([tenant_id])
            except Exception as e:
                logger.warning("grant_genie_access(%s) failed: %s", tenant_id, e)
            try:
                self._mgr.grant_dashboard_access([tenant_id])
            except Exception as e:
                logger.warning("grant_dashboard_access(%s) failed: %s", tenant_id, e)
            return {
                "ok": True,
                "tenant_id": tenant_id,
                "tenant_name": tenant_name,
                "sp_app_id": result.tenant.sp_app_id,
                "client_secret": result.client_secret,
            }
        except Exception as e:
            return {
                "ok": False,
                "tenant_id": tenant_id,
                "tenant_name": tenant_name,
                "error": str(e),
            }
