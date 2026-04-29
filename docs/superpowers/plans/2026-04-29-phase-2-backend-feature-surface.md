# Phase 2 — Backend Feature Surface Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the new endpoints and supporting library code that the Phase 3 UI rebuild will consume — bulk onboarding (with in-process job runner), tenant lifecycle (rotate/deactivate/reactivate/hard-delete), per-tenant query history, isolation verifier, and the request-flow inspector payload on `/api/genie/ask`.

**Architecture:** Three layers, built bottom-up.
1. **SPManager additions** — `reactivate_tenant()` and `delete_tenant()` round out the lifecycle. Symmetric to existing `onboard_tenant`/`deactivate_tenant`.
2. **Server-side library code** — an in-process `JobRunner` for bulk onboarding (thread-pool, cancellable, progress-tracked); a `Verifier` that lifts `scripts/verify_isolation.py` into reusable code; an `Inspector` that accumulates per-step records (timing, code snippets, payloads) for the F2 hero feature.
3. **Routers** — split `tenants.py` so `/audit`, `/mapping`, `/jobs`, `/verify` are their own files; add the new endpoints; modify `/genie/ask` to optionally return an `inspector` block.

**Tech Stack:** Python 3.11, FastAPI, psycopg 3 (existing), Databricks SDK (existing), `concurrent.futures.ThreadPoolExecutor` for the job runner, `httpx`/`fastapi.testclient` for endpoint tests.

**Working tree assumed at start:** branch `generalize-and-scale` at the head of Phase 1 (`b428c87` or later). Clean working tree. Smoke test 3 PASSED, Postgres-backed tests SKIPPED. Note: Postgres-backed tests still skip without Docker; new tests follow the same `_can_connect()` pattern when they touch repos.

---

## Task 1: SPManager.reactivate_tenant + delete_tenant

Add the two missing lifecycle methods. `reactivate` is the inverse of `deactivate`: re-enable the SP, re-activate the mapping, mint a fresh secret, mark `client_registry.status = 'active'`. `delete_tenant` is hard delete: remove all four resources (SP, mapping row, registry row, credential row).

**Files:**
- Modify: `server/lib/sp_manager.py`

- [ ] **Step 1: Open `server/lib/sp_manager.py` and add the two methods**

After the existing `deactivate_tenant` method, add:

```python
def reactivate_tenant(self, tenant_id: str) -> str:
    """Re-enable a previously deactivated tenant. Returns the new client secret.

    Reactivation is not a no-op — deactivation deletes the SP secret and
    drops the credential row. We mint a fresh secret, store it, flip the SP
    back to active, re-enable the mapping, and update status. Caller must
    distribute the new secret to whoever was using the old one.
    """
    from server.lib.repository import (
        tenant as tenant_repo, credential as cred_repo, mapping as mapping_repo
    )
    tenant = self._fetch_tenant(tenant_id)
    sp_db_id = self._sp_db_id(tenant.sp_app_id)

    # Re-enable the SP
    self.w.service_principals.update(
        id=sp_db_id, active=True,
        application_id=tenant.sp_app_id, display_name=tenant.sp_display_name,
    )
    # Mint fresh OAuth secret
    fresh = self.w.service_principal_secrets_proxy.create(
        service_principal_id=sp_db_id
    )
    cred_repo.put(tenant.sp_app_id, fresh.secret)
    mapping_repo.activate_mapping(self.w, self.warehouse_id, tenant.sp_app_id)
    tenant_repo.set_status(tenant_id, "active")
    self._audit("reactivate", tenant_id, tenant.sp_app_id)
    return fresh.secret


def delete_tenant(self, tenant_id: str) -> None:
    """Hard delete: remove SP, mapping row, credential row, registry row.

    Best-effort across the four resources — each cleanup is wrapped in
    its own try block so a partial failure on one doesn't leave the
    others orphaned. Final state: tenant_id no longer exists anywhere.
    """
    from server.lib.repository import (
        tenant as tenant_repo, credential as cred_repo, mapping as mapping_repo
    )
    tenant = self._fetch_tenant(tenant_id)
    sp_app_id = tenant.sp_app_id

    # 1. Delete SP (also removes its OAuth secrets)
    try:
        sp_db_id = self._sp_db_id(sp_app_id)
        self.w.service_principals.delete(id=sp_db_id)
    except Exception as e:
        logger.warning("Could not delete SP %s: %s", sp_app_id, e)

    # 2. Drop UC mapping row
    try:
        mapping_repo.delete_mapping(self.w, self.warehouse_id, sp_app_id)
    except Exception as e:
        logger.warning("Could not delete UC mapping for %s: %s", sp_app_id, e)

    # 3. Drop Lakebase credential row
    try:
        cred_repo.delete(sp_app_id)
    except Exception as e:
        logger.warning("Could not delete credential for %s: %s", sp_app_id, e)

    # 4. Drop Lakebase tenant row
    tenant_repo.delete(tenant_id)
    self._audit("delete", tenant_id, sp_app_id)
```

- [ ] **Step 2: Run smoke test**

```bash
pytest tests/test_smoke.py -v
```

Expected: 3 PASSED.

- [ ] **Step 3: Confirm SPManager class still parses and imports**

```bash
python -c "from server.lib.sp_manager import SPManager; print(hasattr(SPManager, 'reactivate_tenant'), hasattr(SPManager, 'delete_tenant'))"
```

Expected: `True True`.

- [ ] **Step 4: Commit**

```bash
git add server/lib/sp_manager.py
git commit -m "Add SPManager.reactivate_tenant + delete_tenant"
```

---

## Task 2: In-process bulk onboard job runner

Create `server/jobs/bulk_onboard.py` — a small in-process job manager. It accepts a list of `(tenant_id, tenant_name)` pairs, runs onboarding through `SPManager.onboard_tenant` on a worker thread pool with rate-limit backoff, and exposes a `get_status(job_id)` for polling.

**Files:**
- Create: `server/jobs/__init__.py` (empty)
- Create: `server/jobs/bulk_onboard.py`
- Create: `tests/test_bulk_onboard_job.py`

- [ ] **Step 1: Create the package marker**

```bash
mkdir -p server/jobs
touch server/jobs/__init__.py
```

- [ ] **Step 2: Write the failing test (mocks SPManager)**

```python
# tests/test_bulk_onboard_job.py
"""Tests for server.jobs.bulk_onboard — in-process job runner."""
from __future__ import annotations

import time
from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest

from server.jobs import bulk_onboard


@dataclass
class _FakeTenant:
    tenant_id: str
    tenant_name: str
    sp_app_id: str
    sp_display_name: str
    status: str = "active"
    created_at: object = None
    updated_at: object = None


@dataclass
class _FakeOnboardResult:
    tenant: _FakeTenant
    client_id: str
    client_secret: str


def _make_fake_mgr(*, fail_on: set[str] | None = None):
    """Build a MagicMock that mimics SPManager.onboard_tenant."""
    fail_on = fail_on or set()
    mgr = MagicMock()

    def onboard(tenant_id, tenant_name):
        time.sleep(0.01)  # simulate work; lets progress polling observe states
        if tenant_id in fail_on:
            raise RuntimeError(f"forced failure for {tenant_id}")
        sp_app = f"sp-{tenant_id}"
        return _FakeOnboardResult(
            tenant=_FakeTenant(
                tenant_id=tenant_id,
                tenant_name=tenant_name,
                sp_app_id=sp_app,
                sp_display_name=f"mt-genie-{tenant_id}",
            ),
            client_id=sp_app,
            client_secret=f"secret-{tenant_id}",
        )

    mgr.onboard_tenant.side_effect = onboard
    mgr.grant_data_access.return_value = None
    mgr.grant_genie_access.return_value = None
    return mgr


def test_submit_returns_job_id():
    runner = bulk_onboard.JobRunner(_make_fake_mgr(), max_workers=2)
    job_id = runner.submit([
        {"tenant_id": "a", "tenant_name": "A"},
        {"tenant_id": "b", "tenant_name": "B"},
    ])
    assert isinstance(job_id, str) and len(job_id) > 0


def test_status_progresses_to_completed():
    runner = bulk_onboard.JobRunner(_make_fake_mgr(), max_workers=2)
    job_id = runner.submit([
        {"tenant_id": "a", "tenant_name": "A"},
        {"tenant_id": "b", "tenant_name": "B"},
    ])
    deadline = time.time() + 5.0
    while time.time() < deadline:
        status = runner.get_status(job_id)
        if status.state == "completed":
            break
        time.sleep(0.05)
    status = runner.get_status(job_id)
    assert status.state == "completed"
    assert status.processed == 2
    assert status.total == 2
    assert len(status.errors) == 0


def test_partial_failure_recorded_in_errors():
    runner = bulk_onboard.JobRunner(_make_fake_mgr(fail_on={"b"}), max_workers=2)
    job_id = runner.submit([
        {"tenant_id": "a", "tenant_name": "A"},
        {"tenant_id": "b", "tenant_name": "B"},
        {"tenant_id": "c", "tenant_name": "C"},
    ])
    deadline = time.time() + 5.0
    while time.time() < deadline:
        if runner.get_status(job_id).state == "completed":
            break
        time.sleep(0.05)
    status = runner.get_status(job_id)
    assert status.state == "completed"
    assert status.processed == 3
    assert len(status.errors) == 1
    assert status.errors[0]["tenant_id"] == "b"
    assert "forced failure" in status.errors[0]["error"]


def test_results_carry_secret_for_successes():
    runner = bulk_onboard.JobRunner(_make_fake_mgr(), max_workers=2)
    job_id = runner.submit([{"tenant_id": "a", "tenant_name": "A"}])
    deadline = time.time() + 3.0
    while time.time() < deadline:
        if runner.get_status(job_id).state == "completed":
            break
        time.sleep(0.05)
    status = runner.get_status(job_id)
    results = status.results
    assert len(results) == 1
    assert results[0]["tenant_id"] == "a"
    assert results[0]["client_secret"] == "secret-a"
    assert results[0]["sp_app_id"] == "sp-a"


def test_unknown_job_id_returns_none():
    runner = bulk_onboard.JobRunner(_make_fake_mgr(), max_workers=2)
    assert runner.get_status("nope") is None
```

- [ ] **Step 3: Run pytest — tests should FAIL with ImportError**

```bash
pytest tests/test_bulk_onboard_job.py -v
```

Expected: ModuleNotFoundError on `server.jobs.bulk_onboard`.

- [ ] **Step 4: Implement the job runner**

```python
# server/jobs/bulk_onboard.py
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
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/test_bulk_onboard_job.py -v
```

Expected: 5 PASSED.

If any test fails, debug. The most likely failure is timing — the polling loop waits up to 5 seconds. If your machine is slow, bump the deadline. Otherwise, fix the implementation.

- [ ] **Step 6: Smoke test still passes**

```bash
pytest tests/test_smoke.py -v
```

Expected: 3 PASSED.

- [ ] **Step 7: Commit**

```bash
git add server/jobs tests/test_bulk_onboard_job.py
git commit -m "Add in-process bulk onboard job runner"
```

---

## Task 3: Bulk onboard + jobs router

Add `POST /api/tenants/bulk` (kicks off a job, returns `job_id`) and `GET /api/jobs/{job_id}` (polls progress).

**Files:**
- Create: `server/routers/jobs.py`
- Modify: `server/routers/__init__.py` (register jobs router)
- Modify: `server/routers/tenants.py` (add `/bulk` endpoint)
- Create: `tests/test_router_bulk_onboard.py`

- [ ] **Step 1: Write the failing test for bulk + status**

```python
# tests/test_router_bulk_onboard.py
"""Endpoint tests for POST /api/tenants/bulk and GET /api/jobs/{id}."""
from __future__ import annotations

import time
from dataclasses import dataclass
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient


@dataclass
class _FakeTenant:
    tenant_id: str
    tenant_name: str
    sp_app_id: str
    sp_display_name: str
    status: str = "active"
    created_at: object = None
    updated_at: object = None


@dataclass
class _FakeOnboardResult:
    tenant: _FakeTenant
    client_id: str
    client_secret: str


@pytest.fixture
def client(monkeypatch):
    from server import app as app_module
    from server.routers import tenants as tenants_router

    fake_mgr = MagicMock()

    def fake_onboard(tenant_id, tenant_name):
        sp_app = f"sp-{tenant_id}"
        return _FakeOnboardResult(
            tenant=_FakeTenant(
                tenant_id=tenant_id,
                tenant_name=tenant_name,
                sp_app_id=sp_app,
                sp_display_name=f"mt-genie-{tenant_id}",
            ),
            client_id=sp_app,
            client_secret=f"secret-{tenant_id}",
        )

    fake_mgr.onboard_tenant.side_effect = fake_onboard
    fake_mgr.grant_data_access.return_value = None
    fake_mgr.grant_genie_access.return_value = None

    monkeypatch.setattr(tenants_router, "_mgr", lambda: fake_mgr)

    # Reset job runner state per test
    from server.routers import jobs as jobs_router
    jobs_router._reset_for_tests()

    return TestClient(app_module.app)


def test_bulk_returns_job_id(client):
    r = client.post("/api/tenants/bulk", json={
        "tenants": [
            {"tenant_id": "a", "tenant_name": "A"},
            {"tenant_id": "b", "tenant_name": "B"},
        ]
    })
    assert r.status_code == 200
    assert "job_id" in r.json()


def test_status_endpoint_progresses(client):
    r = client.post("/api/tenants/bulk", json={
        "tenants": [
            {"tenant_id": "a", "tenant_name": "A"},
            {"tenant_id": "b", "tenant_name": "B"},
        ]
    })
    job_id = r.json()["job_id"]
    deadline = time.time() + 5.0
    final = None
    while time.time() < deadline:
        s = client.get(f"/api/jobs/{job_id}")
        assert s.status_code == 200
        body = s.json()
        if body["state"] == "completed":
            final = body
            break
        time.sleep(0.05)
    assert final is not None
    assert final["total"] == 2
    assert final["processed"] == 2


def test_unknown_job_id_returns_404(client):
    r = client.get("/api/jobs/does-not-exist")
    assert r.status_code == 404


def test_bulk_rejects_empty_list(client):
    r = client.post("/api/tenants/bulk", json={"tenants": []})
    assert r.status_code == 400
```

- [ ] **Step 2: Run pytest — fails with ImportError or 404**

```bash
pytest tests/test_router_bulk_onboard.py -v
```

Expected: ImportError (module `server.routers.jobs` doesn't exist), or all tests fail.

- [ ] **Step 3: Create `server/routers/jobs.py`**

```python
# server/routers/jobs.py
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
        from server.routers.tenants import _mgr
        _runner = JobRunner(_mgr())
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
```

- [ ] **Step 4: Add `/bulk` to `server/routers/tenants.py`**

After the existing `onboard()` route, add:

```python
class BulkOnboardRequest(BaseModel):
    tenants: list[OnboardRequest]


class BulkOnboardResponse(BaseModel):
    job_id: str


@router.post('/bulk', response_model=BulkOnboardResponse)
async def bulk_onboard(req: BulkOnboardRequest) -> BulkOnboardResponse:
    if not req.tenants:
        raise HTTPException(status_code=400, detail="tenants list is empty")
    from server.routers.jobs import runner
    job_id = runner().submit([
        {"tenant_id": t.tenant_id, "tenant_name": t.tenant_name}
        for t in req.tenants
    ])
    return BulkOnboardResponse(job_id=job_id)
```

- [ ] **Step 5: Register the jobs router in `server/routers/__init__.py`**

Open `server/routers/__init__.py` and add:

```python
from .jobs import router as jobs_router
...
router.include_router(jobs_router, prefix='/jobs', tags=['jobs'])
```

The full file should now look like:

```python
"""Multi-Tenant Genie — API router."""

from fastapi import APIRouter

from .tenants import router as tenants_router
from .genie import router as genie_router
from .workspace import router as workspace_router
from .jobs import router as jobs_router

router = APIRouter()
router.include_router(tenants_router, prefix='/tenants', tags=['tenants'])
router.include_router(genie_router, prefix='/genie', tags=['genie'])
router.include_router(workspace_router, prefix='/workspace', tags=['workspace'])
router.include_router(jobs_router, prefix='/jobs', tags=['jobs'])
```

- [ ] **Step 6: Run tests**

```bash
pytest tests/test_router_bulk_onboard.py -v
pytest tests/test_smoke.py -v
```

Expected: 4 PASSED for the bulk onboard tests; 3 PASSED for smoke.

- [ ] **Step 7: Commit**

```bash
git add server/routers/jobs.py server/routers/tenants.py server/routers/__init__.py tests/test_router_bulk_onboard.py
git commit -m "Add bulk onboard endpoint + jobs router"
```

---

## Task 4: Reactivate + delete tenant endpoints

Add `POST /api/tenants/{id}/reactivate` and `DELETE /api/tenants/{id}`.

**Files:**
- Modify: `server/routers/tenants.py`
- Create: `tests/test_router_lifecycle.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_router_lifecycle.py
"""Endpoint tests for reactivate + delete."""
from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient


@dataclass
class _FakeTenant:
    tenant_id: str
    tenant_name: str
    sp_app_id: str
    sp_display_name: str
    status: str = "active"
    created_at: object = None
    updated_at: object = None


@pytest.fixture
def client(monkeypatch):
    from server import app as app_module
    from server.routers import tenants as tenants_router

    fake_mgr = MagicMock()
    fake_mgr.reactivate_tenant.return_value = "fresh-secret-xyz"
    fake_mgr.delete_tenant.return_value = None
    fake_mgr.list_tenants.return_value = [
        _FakeTenant(tenant_id="acme", tenant_name="Acme", sp_app_id="sp-acme", sp_display_name="mt-acme"),
    ]

    monkeypatch.setattr(tenants_router, "_mgr", lambda: fake_mgr)
    return TestClient(app_module.app), fake_mgr


def test_reactivate_returns_new_secret(client):
    c, fake_mgr = client
    r = c.post("/api/tenants/acme/reactivate")
    assert r.status_code == 200
    body = r.json()
    assert body["tenant_id"] == "acme"
    assert body["new_client_secret"] == "fresh-secret-xyz"
    fake_mgr.reactivate_tenant.assert_called_once_with("acme")


def test_delete_removes_tenant(client):
    c, fake_mgr = client
    r = c.delete("/api/tenants/acme")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "tenant_id": "acme"}
    fake_mgr.delete_tenant.assert_called_once_with("acme")


def test_reactivate_propagates_lookup_error(client):
    c, fake_mgr = client
    fake_mgr.reactivate_tenant.side_effect = LookupError("not found")
    r = c.post("/api/tenants/nope/reactivate")
    assert r.status_code == 500
    assert "not found" in r.json()["detail"]
```

- [ ] **Step 2: Run pytest — should fail with 404 / 405 (endpoints don't exist)**

```bash
pytest tests/test_router_lifecycle.py -v
```

Expected: 3 failures.

- [ ] **Step 3: Add the two endpoints to `server/routers/tenants.py`**

After the existing `deactivate()` route, add:

```python
@router.post('/{tenant_id}/reactivate', response_model=RotateResponse)
async def reactivate(tenant_id: str) -> RotateResponse:
    try:
        new_secret = _mgr().reactivate_tenant(tenant_id)
        for t in _mgr().list_tenants():
            if t.tenant_id == tenant_id:
                _invalidate_minter_cache(t.sp_app_id)
                break
        return RotateResponse(tenant_id=tenant_id, new_client_secret=new_secret)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete('/{tenant_id}')
async def delete(tenant_id: str) -> dict[str, Any]:
    try:
        sp_app_id = ''
        for t in _mgr().list_tenants():
            if t.tenant_id == tenant_id:
                sp_app_id = t.sp_app_id
                break
        _mgr().delete_tenant(tenant_id)
        _invalidate_minter_cache(sp_app_id)
        return {'ok': True, 'tenant_id': tenant_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_router_lifecycle.py -v
pytest tests/test_smoke.py -v
```

Expected: 3 PASSED for lifecycle; 3 PASSED for smoke.

- [ ] **Step 5: Commit**

```bash
git add server/routers/tenants.py tests/test_router_lifecycle.py
git commit -m "Add reactivate + delete tenant endpoints"
```

---

## Task 5: Audit router split (move /audit + /mapping out of tenants.py; fix audit to read from Lakebase)

The current `/api/tenants/audit` endpoint reads from UC `audit_log` (legacy). Phase 1 moved audit writes to Lakebase but didn't update the read path. This task fixes the read path AND moves it to its own router for cleaner separation. `/api/tenants/mapping` also moves out (it doesn't really belong under `/tenants/{id}`).

**New routes:**
- `GET /api/audit?limit=K` → reads from Lakebase via `audit_repo.list_recent`
- `GET /api/audit/mapping` → UC `sp_tenant_mapping` (renamed from `/tenants/mapping`)

**Files:**
- Create: `server/routers/audit.py`
- Modify: `server/routers/__init__.py` (register audit router)
- Modify: `server/routers/tenants.py` (remove `/audit` and `/mapping` routes; remove `_parse_ts`/`_parse_bool` if no longer used)
- Create: `tests/test_router_audit.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_router_audit.py
"""Endpoint tests for GET /api/audit and GET /api/audit/mapping."""
from __future__ import annotations

from datetime import datetime, timezone
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@dataclass
class _FakeAuditRow:
    id: int
    tenant_id: str | None
    actor: str | None
    action: str
    sp_app_id: str | None
    question: str | None
    status: str
    latency_ms: int | None
    detail: str | None
    created_at: datetime


@pytest.fixture
def client(monkeypatch):
    from server import app as app_module
    from server.routers import tenants as tenants_router

    fake_mgr = MagicMock()
    fake_mgr._execute_sql.return_value = [
        ["sp-acme", "acme", "true"],
        ["sp-globex", "globex", "false"],
    ]
    monkeypatch.setattr(tenants_router, "_mgr", lambda: fake_mgr)
    return TestClient(app_module.app), fake_mgr


def test_audit_returns_lakebase_rows(client):
    c, _ = client
    fake_rows = [
        _FakeAuditRow(
            id=2, tenant_id="acme", actor="rohit", action="query",
            sp_app_id="sp-acme", question="hello", status="completed",
            latency_ms=1100, detail=None,
            created_at=datetime(2026, 4, 29, 9, 0, tzinfo=timezone.utc),
        ),
        _FakeAuditRow(
            id=1, tenant_id="globex", actor="rohit", action="onboard",
            sp_app_id="sp-globex", question=None, status="ok",
            latency_ms=None, detail=None,
            created_at=datetime(2026, 4, 29, 8, 55, tzinfo=timezone.utc),
        ),
    ]
    with patch("server.routers.audit.audit_repo.list_recent", return_value=fake_rows):
        r = c.get("/api/audit?limit=10")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 2
    assert body[0]["tenant_id"] == "acme"
    assert body[0]["action"] == "query"
    assert body[0]["latency_ms"] == 1100


def test_audit_default_limit(client):
    c, _ = client
    with patch("server.routers.audit.audit_repo.list_recent", return_value=[]) as mocked:
        r = c.get("/api/audit")
    assert r.status_code == 200
    mocked.assert_called_once_with(limit=50)


def test_mapping_returns_uc_rows(client):
    c, fake_mgr = client
    r = c.get("/api/audit/mapping")
    assert r.status_code == 200
    body = r.json()
    assert body == [
        {"sp_app_id": "sp-acme", "tenant_id": "acme", "active": True},
        {"sp_app_id": "sp-globex", "tenant_id": "globex", "active": False},
    ]
```

- [ ] **Step 2: Run pytest — fails with 404**

```bash
pytest tests/test_router_audit.py -v
```

Expected: 3 failures (`/api/audit` doesn't exist yet).

- [ ] **Step 3: Create `server/routers/audit.py`**

```python
# server/routers/audit.py
"""Audit log + UC mapping read endpoints."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from server.lib.config import CONFIG
from server.lib.repository import audit as audit_repo

router = APIRouter()


class AuditRow(BaseModel):
    id: int
    tenant_id: str | None
    actor: str | None
    action: str
    sp_app_id: str | None
    question: str | None
    status: str
    latency_ms: int | None
    detail: str | None
    created_at: datetime


@router.get('', response_model=list[AuditRow])
async def list_audit(limit: int = 50) -> list[AuditRow]:
    try:
        rows = audit_repo.list_recent(limit=limit)
        return [AuditRow(**r.__dict__) for r in rows]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get('/mapping')
async def list_mapping() -> list[dict[str, Any]]:
    try:
        from server.routers.tenants import _mgr
        rows = _mgr()._execute_sql(
            f"""SELECT sp_app_id, tenant_id, active FROM {CONFIG.fq_mapping}
                ORDER BY tenant_id"""
        )
        return [
            {'sp_app_id': r[0], 'tenant_id': r[1], 'active': _parse_bool(r[2])}
            for r in rows
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _parse_bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    return str(v).lower() in ('true', '1', 't')
```

- [ ] **Step 4: Register the audit router**

In `server/routers/__init__.py`, add:

```python
from .audit import router as audit_router
...
router.include_router(audit_router, prefix='/audit', tags=['audit'])
```

Final file:

```python
"""Multi-Tenant Genie — API router."""

from fastapi import APIRouter

from .tenants import router as tenants_router
from .genie import router as genie_router
from .workspace import router as workspace_router
from .jobs import router as jobs_router
from .audit import router as audit_router

router = APIRouter()
router.include_router(tenants_router, prefix='/tenants', tags=['tenants'])
router.include_router(genie_router, prefix='/genie', tags=['genie'])
router.include_router(workspace_router, prefix='/workspace', tags=['workspace'])
router.include_router(jobs_router, prefix='/jobs', tags=['jobs'])
router.include_router(audit_router, prefix='/audit', tags=['audit'])
```

- [ ] **Step 5: Remove the old `/audit` and `/mapping` routes from `tenants.py`**

In `server/routers/tenants.py`:
- Delete the `@router.get('/audit', ...)` route and its handler `audit()`.
- Delete the `@router.get('/mapping')` route and its handler `mapping()`.
- Delete the `AuditRow` Pydantic model (it moves to `audit.py` with a richer shape).
- Delete the `_parse_ts` and `_parse_bool` helper functions (no longer used).
- Delete the `from server.lib.config import CONFIG` import if it's no longer used.

Check after editing: `grep -n "CONFIG\|_parse_ts\|_parse_bool\|AuditRow" server/routers/tenants.py` — anything still referenced should stay.

- [ ] **Step 6: Run tests**

```bash
pytest tests/test_router_audit.py tests/test_smoke.py tests/test_router_lifecycle.py tests/test_router_bulk_onboard.py -v
```

Expected: 3 + 3 + 3 + 4 = 13 PASSED.

- [ ] **Step 7: Commit**

```bash
git add server/routers tests/test_router_audit.py
git commit -m "Split audit + mapping out of tenants router; read audit from Lakebase"
```

---

## Task 6: Per-tenant query history endpoint

Add `GET /api/tenants/{tenant_id}/history?limit=K`. Reads from `audit_repo.history_for_tenant`.

**Files:**
- Modify: `server/routers/tenants.py` (add `/history` endpoint)
- Modify: `tests/test_router_lifecycle.py` (or create new test file — pick one)

(Adding to the existing lifecycle test file to avoid file proliferation.)

- [ ] **Step 1: Add the failing test**

Append to `tests/test_router_lifecycle.py`:

```python
def test_history_returns_per_tenant_rows(client):
    from datetime import datetime, timezone
    from dataclasses import dataclass
    from unittest.mock import patch

    @dataclass
    class _FakeAuditRow:
        id: int
        tenant_id: str | None
        actor: str | None
        action: str
        sp_app_id: str | None
        question: str | None
        status: str
        latency_ms: int | None
        detail: str | None
        created_at: datetime

    c, _ = client
    fake_rows = [
        _FakeAuditRow(
            id=3, tenant_id="acme", actor="rohit", action="query",
            sp_app_id="sp-acme", question="hello", status="completed",
            latency_ms=900, detail=None,
            created_at=datetime(2026, 4, 29, 9, 5, tzinfo=timezone.utc),
        ),
    ]
    with patch(
        "server.routers.tenants.audit_repo.history_for_tenant",
        return_value=fake_rows,
    ) as mocked:
        r = c.get("/api/tenants/acme/history?limit=10")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["tenant_id"] == "acme"
    assert body[0]["action"] == "query"
    mocked.assert_called_once_with("acme", limit=10)
```

- [ ] **Step 2: Run pytest — fails (no /history endpoint)**

```bash
pytest tests/test_router_lifecycle.py::test_history_returns_per_tenant_rows -v
```

Expected: 404 or test failure.

- [ ] **Step 3: Add the endpoint to `tenants.py`**

At the top of `server/routers/tenants.py`, add the import:

```python
from server.lib.repository import audit as audit_repo
```

Add the `HistoryRow` model after the existing models:

```python
class HistoryRow(BaseModel):
    id: int
    tenant_id: str | None
    actor: str | None
    action: str
    sp_app_id: str | None
    question: str | None
    status: str
    latency_ms: int | None
    detail: str | None
    created_at: datetime
```

Add the route after the `delete()` route:

```python
@router.get('/{tenant_id}/history', response_model=list[HistoryRow])
async def history(tenant_id: str, limit: int = 50) -> list[HistoryRow]:
    try:
        rows = audit_repo.history_for_tenant(tenant_id, limit=limit)
        return [HistoryRow(**r.__dict__) for r in rows]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

- [ ] **Step 4: Run test**

```bash
pytest tests/test_router_lifecycle.py -v
```

Expected: 4 PASSED (previous 3 + this one).

- [ ] **Step 5: Commit**

```bash
git add server/routers/tenants.py tests/test_router_lifecycle.py
git commit -m "Add per-tenant query history endpoint"
```

---

## Task 7: Lift verifier into `server/lib/verifier.py`

Move the isolation-verification logic out of `scripts/verify_isolation.py` (or rather, extract the testable bits) into a reusable module that both the script and the new endpoint can call.

**Files:**
- Create: `server/lib/verifier.py`
- Modify: `scripts/verify_isolation.py` (keep as a thin CLI wrapper)
- Create: `tests/test_verifier.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_verifier.py
"""Tests for server.lib.verifier — isolation verification logic.

The verifier executes SQL as each tenant's SP and asserts cross-tenant
isolation. Tests mock the SQL execution layer to focus on the assertion
logic, not the warehouse plumbing.
"""
from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest

from server.lib import verifier


@dataclass
class _FakeTenant:
    tenant_id: str
    tenant_name: str
    sp_app_id: str
    sp_display_name: str
    status: str = "active"
    created_at: object = None
    updated_at: object = None


def test_verify_one_passes_when_only_own_rows_visible():
    fake_executor = MagicMock()
    # Only one distinct tenant_id, matching the SP's tenant
    fake_executor.run_as.return_value = [["acme"]]
    result = verifier.verify_tenant(
        executor=fake_executor,
        tenant=_FakeTenant("acme", "Acme", "sp-acme", "mt-acme"),
        secret="secret-acme",
    )
    assert result.passed is True
    assert result.distinct_tenant_ids == ["acme"]


def test_verify_one_fails_when_other_tenant_visible():
    fake_executor = MagicMock()
    fake_executor.run_as.return_value = [["acme"], ["globex"]]  # leak!
    result = verifier.verify_tenant(
        executor=fake_executor,
        tenant=_FakeTenant("acme", "Acme", "sp-acme", "mt-acme"),
        secret="secret-acme",
    )
    assert result.passed is False
    assert "globex" in result.distinct_tenant_ids


def test_verify_one_fails_when_no_credential():
    fake_executor = MagicMock()
    result = verifier.verify_tenant(
        executor=fake_executor,
        tenant=_FakeTenant("acme", "Acme", "sp-acme", "mt-acme"),
        secret=None,
    )
    assert result.passed is False
    assert "no credential" in (result.error or "").lower()
    fake_executor.run_as.assert_not_called()


def test_verify_all_runs_per_active_tenant():
    fake_executor = MagicMock()
    fake_executor.run_as.return_value = [["acme"]]
    fake_credentials = {"sp-acme": "secret-acme", "sp-globex": "secret-globex"}
    tenants = [
        _FakeTenant("acme", "Acme", "sp-acme", "mt-acme"),
        _FakeTenant("globex", "Globex", "sp-globex", "mt-globex"),
        _FakeTenant("zombie", "Zombie", "sp-zombie", "mt-zombie", status="deactivated"),
    ]
    results = verifier.verify_all(
        executor=fake_executor,
        tenants=tenants,
        credentials=fake_credentials,
    )
    # Only the two active tenants get verified
    assert len(results) == 2
    assert {r.tenant_id for r in results} == {"acme", "globex"}
```

- [ ] **Step 2: Run pytest — fails with ImportError**

```bash
pytest tests/test_verifier.py -v
```

Expected: ModuleNotFoundError on `server.lib.verifier`.

- [ ] **Step 3: Implement the verifier**

```python
# server/lib/verifier.py
"""Isolation verifier — proves each tenant SP sees only its own rows.

Executes a SQL query as each tenant via the Statement Execution API,
collects distinct tenant_ids visible from the bookings table, and
asserts the only visible tenant_id is the SP's own. Used by:
- POST /api/verify (returns per-tenant pass/fail)
- scripts/verify_isolation.py (the CLI release-gate flavor)

The ``executor`` is a small interface (a `run_as(token, sql)` callable)
so we can mock it in tests without standing up a warehouse.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Optional, Protocol

import requests

from server.lib.config import CONFIG
from server.lib.token_minter import TokenMinter


@dataclass
class TenantVerifyResult:
    tenant_id: str
    tenant_name: str
    passed: bool
    distinct_tenant_ids: list[str]
    visible_row_count: Optional[int] = None
    error: Optional[str] = None


class Executor(Protocol):
    """Runs SQL with a bearer token. Mockable in tests."""

    def run_as(self, token: str, sql: str) -> list[list[Any]]: ...


class HttpExecutor:
    """Default executor: hits /api/2.0/sql/statements directly with the token."""

    def __init__(self, host: str, warehouse_id: str):
        self.host = host.rstrip("/")
        self.warehouse_id = warehouse_id

    def run_as(self, token: str, sql: str) -> list[list[Any]]:
        r = requests.post(
            f"{self.host}/api/2.0/sql/statements",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "warehouse_id": self.warehouse_id,
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
            rr = requests.get(
                f"{self.host}/api/2.0/sql/statements/{statement_id}",
                headers={"Authorization": f"Bearer {token}"},
                timeout=30,
            )
            rr.raise_for_status()
            body = rr.json()
        if body.get("status", {}).get("state") != "SUCCEEDED":
            raise RuntimeError(f"SQL failed: {body}")
        return (body.get("result") or {}).get("data_array") or []


def verify_tenant(
    *,
    executor: Executor,
    tenant,  # SPManager.Tenant or compatible — has tenant_id, sp_app_id, etc.
    secret: Optional[str],
) -> TenantVerifyResult:
    """Verify a single tenant. Never raises — failures are captured in the result."""
    if not secret:
        return TenantVerifyResult(
            tenant_id=tenant.tenant_id,
            tenant_name=tenant.tenant_name,
            passed=False,
            distinct_tenant_ids=[],
            error=f"no credential available for tenant {tenant.tenant_id}",
        )
    minter = TokenMinter()
    try:
        token = minter.get_token(tenant.sp_app_id, secret)
    except Exception as e:
        return TenantVerifyResult(
            tenant_id=tenant.tenant_id,
            tenant_name=tenant.tenant_name,
            passed=False,
            distinct_tenant_ids=[],
            error=f"token mint failed: {e}",
        )
    try:
        distinct = executor.run_as(
            token, f"SELECT DISTINCT tenant_id FROM {CONFIG.fq_bookings}"
        )
        visible_ids = sorted({str(r[0]) for r in distinct if r and r[0] is not None})
        passed = visible_ids == [tenant.tenant_id]
        return TenantVerifyResult(
            tenant_id=tenant.tenant_id,
            tenant_name=tenant.tenant_name,
            passed=passed,
            distinct_tenant_ids=visible_ids,
        )
    except Exception as e:
        return TenantVerifyResult(
            tenant_id=tenant.tenant_id,
            tenant_name=tenant.tenant_name,
            passed=False,
            distinct_tenant_ids=[],
            error=str(e),
        )


def verify_all(
    *,
    executor: Executor,
    tenants: list,
    credentials: dict[str, Optional[str]],
) -> list[TenantVerifyResult]:
    """Verify every active tenant. ``credentials`` maps sp_app_id → secret."""
    results: list[TenantVerifyResult] = []
    for t in tenants:
        if getattr(t, "status", "active") != "active":
            continue
        results.append(
            verify_tenant(
                executor=executor,
                tenant=t,
                secret=credentials.get(t.sp_app_id),
            )
        )
    return results
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_verifier.py tests/test_smoke.py -v
```

Expected: 4 + 3 = 7 PASSED.

- [ ] **Step 5: Commit**

```bash
git add server/lib/verifier.py tests/test_verifier.py
git commit -m "Add server/lib/verifier — isolation check, decoupled from script"
```

---

## Task 8: POST /api/verify endpoint

Wire the verifier behind a route. Returns `list[TenantVerifyResult]`.

**Files:**
- Create: `server/routers/verify.py`
- Modify: `server/routers/__init__.py` (register)
- Create: `tests/test_router_verify.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_router_verify.py
"""Endpoint test for POST /api/verify."""
from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@dataclass
class _FakeTenant:
    tenant_id: str
    tenant_name: str
    sp_app_id: str
    sp_display_name: str
    status: str = "active"
    created_at: object = None
    updated_at: object = None


@pytest.fixture
def client(monkeypatch):
    from server import app as app_module
    from server.routers import tenants as tenants_router

    fake_mgr = MagicMock()
    fake_mgr.list_tenants.return_value = [
        _FakeTenant("acme", "Acme", "sp-acme", "mt-acme"),
        _FakeTenant("globex", "Globex", "sp-globex", "mt-globex"),
    ]
    fake_mgr.warehouse_id = "wh-test-1"

    monkeypatch.setattr(tenants_router, "_mgr", lambda: fake_mgr)
    return TestClient(app_module.app)


def test_verify_returns_results_per_tenant(client):
    from server.lib.verifier import TenantVerifyResult

    fake_results = [
        TenantVerifyResult(
            tenant_id="acme", tenant_name="Acme",
            passed=True, distinct_tenant_ids=["acme"],
        ),
        TenantVerifyResult(
            tenant_id="globex", tenant_name="Globex",
            passed=False, distinct_tenant_ids=["acme", "globex"],
        ),
    ]
    with patch("server.routers.verify.verifier.verify_all", return_value=fake_results), \
         patch("server.routers.verify._collect_credentials", return_value={"sp-acme": "s1", "sp-globex": "s2"}):
        r = client.post("/api/verify")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 2
    assert body[0]["tenant_id"] == "acme"
    assert body[0]["passed"] is True
    assert body[1]["tenant_id"] == "globex"
    assert body[1]["passed"] is False
    assert "globex" in body[1]["distinct_tenant_ids"]
```

- [ ] **Step 2: Run pytest — fails with 404**

```bash
pytest tests/test_router_verify.py -v
```

Expected: 1 failure (404).

- [ ] **Step 3: Create `server/routers/verify.py`**

```python
# server/routers/verify.py
"""POST /api/verify — runs the isolation verifier across active tenants."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from server.lib import verifier
from server.lib.config import CONFIG
from server.lib.repository import credential as cred_repo
from server.routers.tenants import _mgr

router = APIRouter()


class VerifyResultRow(BaseModel):
    tenant_id: str
    tenant_name: str
    passed: bool
    distinct_tenant_ids: list[str]
    visible_row_count: Optional[int] = None
    error: Optional[str] = None


def _collect_credentials(tenants) -> dict[str, Optional[str]]:
    return {t.sp_app_id: cred_repo.get(t.sp_app_id) for t in tenants}


@router.post('', response_model=list[VerifyResultRow])
async def run_verify() -> list[VerifyResultRow]:
    try:
        tenants = [t for t in _mgr().list_tenants() if t.status == "active"]
        credentials = _collect_credentials(tenants)
        executor = verifier.HttpExecutor(
            host=CONFIG.host, warehouse_id=_mgr().warehouse_id
        )
        results = verifier.verify_all(
            executor=executor, tenants=tenants, credentials=credentials,
        )
        return [
            VerifyResultRow(
                tenant_id=r.tenant_id,
                tenant_name=r.tenant_name,
                passed=r.passed,
                distinct_tenant_ids=r.distinct_tenant_ids,
                visible_row_count=r.visible_row_count,
                error=r.error,
            )
            for r in results
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

- [ ] **Step 4: Register the verify router**

In `server/routers/__init__.py`, add:

```python
from .verify import router as verify_router
...
router.include_router(verify_router, prefix='/verify', tags=['verify'])
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/test_router_verify.py tests/test_smoke.py -v
```

Expected: 1 + 3 = 4 PASSED.

- [ ] **Step 6: Commit**

```bash
git add server/routers/verify.py server/routers/__init__.py tests/test_router_verify.py
git commit -m "Add POST /api/verify endpoint"
```

---

## Task 9: Inspector module

Create `server/lib/inspector.py` — a small accumulator that records six step events and emits a JSON-serializable structure for the `/api/genie/ask?inspect=true` response.

**Files:**
- Create: `server/lib/inspector.py`
- Create: `tests/test_inspector.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_inspector.py
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
```

- [ ] **Step 2: Run pytest — ImportError**

```bash
pytest tests/test_inspector.py -v
```

Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement Inspector**

```python
# server/lib/inspector.py
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
from dataclasses import dataclass, field
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
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_inspector.py tests/test_smoke.py -v
```

Expected: 4 + 3 = 7 PASSED.

- [ ] **Step 5: Commit**

```bash
git add server/lib/inspector.py tests/test_inspector.py
git commit -m "Add Inspector — six-step request flow accumulator"
```

---

## Task 10: Wire inspector into /api/genie/ask

Add an `inspect: bool = False` query param to `POST /api/genie/ask`. When true, return an `inspector` block alongside the answer.

**Files:**
- Modify: `server/routers/genie.py`
- Create: `tests/test_router_genie_inspector.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_router_genie_inspector.py
"""Endpoint test for POST /api/genie/ask?inspect=true."""
from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@dataclass
class _FakeTenant:
    tenant_id: str
    tenant_name: str
    sp_app_id: str
    sp_display_name: str
    status: str = "active"
    created_at: object = None
    updated_at: object = None


@dataclass
class _FakeGenieResponse:
    question: str
    answer_text: str | None
    sql: str | None
    rows: list[list]
    columns: list[str]
    latency_ms: int
    conversation_id: str | None
    message_id: str | None
    status: str
    raw: dict


@pytest.fixture
def client(monkeypatch):
    from server import app as app_module
    from server.routers import tenants as tenants_router
    from server.routers import genie as genie_router

    fake_mgr = MagicMock()
    fake_mgr.list_tenants.return_value = [
        _FakeTenant("acme", "Acme", "sp-acme", "mt-acme"),
    ]
    monkeypatch.setattr(tenants_router, "_mgr", lambda: fake_mgr)

    fake_genie_response = _FakeGenieResponse(
        question="how many bookings",
        answer_text="187 bookings",
        sql="SELECT COUNT(*) FROM bookings",
        rows=[[187]], columns=["count"],
        latency_ms=2113,
        conversation_id="conv-1", message_id="msg-1",
        status="COMPLETED", raw={},
    )

    def fake_ask(*, space_id, question, client_id, client_secret, conversation_id, timeout_s):
        return fake_genie_response

    monkeypatch.setattr(genie_router._client, "ask", fake_ask)
    monkeypatch.setattr(
        genie_router, "_get_secret_for_sp", lambda sp_app_id: "secret-acme"
    )

    return TestClient(app_module.app)


def test_ask_without_inspect_omits_inspector(client):
    r = client.post("/api/genie/ask", json={
        "tenant_id": "acme", "question": "how many bookings"
    })
    assert r.status_code == 200
    body = r.json()
    assert body.get("inspector") is None


def test_ask_with_inspect_returns_six_steps(client):
    r = client.post("/api/genie/ask?inspect=true", json={
        "tenant_id": "acme", "question": "how many bookings"
    })
    assert r.status_code == 200
    body = r.json()
    assert body["inspector"] is not None
    steps = body["inspector"]["steps"]
    names = [s["name"] for s in steps]
    assert names == [
        "Authenticate", "Resolve tenant", "Mint token",
        "Apply row filter", "Ask Genie", "Audit",
    ]
    apply_filter = next(s for s in steps if s["name"] == "Apply row filter")
    assert "tenant_id" in (apply_filter["summary"] or "")
```

- [ ] **Step 2: Run pytest — failures**

```bash
pytest tests/test_router_genie_inspector.py -v
```

Expected: 2 failures (no `inspect` param yet, no `inspector` in response).

- [ ] **Step 3: Modify `server/routers/genie.py`**

Top of file — add:

```python
from server.lib.inspector import Inspector
```

Update the `AskResponse` Pydantic model to include the new optional field:

```python
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
    inspector: dict | None = None
```

Replace `_ask_sync` with the inspector-aware version:

```python
def _ask_sync(
    tenant_id: str,
    question: str,
    conversation_id: str | None = None,
    *,
    inspect: bool = False,
) -> AskResponse:
    insp = Inspector() if inspect else None

    # Step 1: Authenticate (resolve which tenant the request belongs to)
    if insp is not None:
        with insp.step("Authenticate") as step:
            tenants = [t for t in _mgr().list_tenants() if t.tenant_id == tenant_id]
            if not tenants:
                raise ValueError(f'Tenant {tenant_id} not found')
            tenant = tenants[0]
            step.summary = f"Tenant resolved → {tenant.tenant_id} (sp_app_id={tenant.sp_app_id[:12]}…)"
            step.code_snippet = "tenants = mgr.list_tenants()  # reads client_registry"
    else:
        tenants = [t for t in _mgr().list_tenants() if t.tenant_id == tenant_id]
        if not tenants:
            raise ValueError(f'Tenant {tenant_id} not found')
        tenant = tenants[0]

    # Step 2: Resolve tenant (Lakebase lookup → genie_space_id)
    if insp is not None:
        with insp.step("Resolve tenant") as step:
            space_id = CONFIG.genie_space_id  # per-tenant override is Phase-2-future
            step.summary = f"genie_space_id={space_id[:12]}… (workspace global)"
            step.code_snippet = "tenant_repo.get(tenant_id)  # → client_registry row"
    else:
        space_id = CONFIG.genie_space_id

    # Step 3: Mint token
    if insp is not None:
        with insp.step("Mint token") as step:
            secret = _get_secret_for_sp(tenant.sp_app_id)
            if not secret:
                raise ValueError(
                    f"No credential stored for tenant {tenant_id}. "
                    "Rotate on the Admin tab to regenerate."
                )
            step.summary = "OAuth M2M token (cache-aware)"
            step.code_snippet = (
                "minter.get_token(client_id, client_secret)  # /oidc/v1/token"
            )
    else:
        secret = _get_secret_for_sp(tenant.sp_app_id)
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
                f"Filter resolves for sp_app_id={tenant.sp_app_id[:12]}… "
                f"→ tenant_id='{tenant.tenant_id}'"
            ),
            code_snippet=(
                "CREATE OR REPLACE FUNCTION tenant_row_filter(tenant_id STRING)\n"
                "RETURN EXISTS (\n"
                "  SELECT 1 FROM sp_tenant_mapping\n"
                "  WHERE sp_app_id = session_user() AND active\n"
                "    AND m.tenant_id = tenant_row_filter.tenant_id\n"
                ");"
            ),
        )

    # Step 5: Ask Genie
    if insp is not None:
        with insp.step("Ask Genie") as step:
            resp = _client.ask(
                space_id=space_id, question=question,
                client_id=tenant.sp_app_id, client_secret=secret,
                conversation_id=conversation_id, timeout_s=120,
            )
            step.summary = (
                f"Genie status={resp.status}; rows={len(resp.rows)}; "
                f"cols={len(resp.columns)}"
            )
            step.code_snippet = (
                "POST /api/2.0/genie/spaces/{space_id}/start-conversation"
            )
    else:
        resp = _client.ask(
            space_id=space_id, question=question,
            client_id=tenant.sp_app_id, client_secret=secret,
            conversation_id=conversation_id, timeout_s=120,
        )

    # Step 6: Audit (best-effort)
    if insp is not None:
        with insp.step("Audit") as step:
            try:
                _mgr()._audit(
                    'query', tenant.tenant_id, tenant.sp_app_id,
                    question=resp.question, latency_ms=resp.latency_ms,
                    status='ok' if resp.status == 'COMPLETED' else 'error',
                    detail=None if resp.status == 'COMPLETED' else f'genie_status={resp.status}',
                )
                step.summary = "audit_log row written"
                step.code_snippet = "audit_repo.append(action='query', ...)"
            except Exception as e:
                step.summary = f"audit failed (non-fatal): {e}"
    else:
        try:
            _mgr()._audit(
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
        inspector=insp.build() if insp is not None else None,
    )
```

Update the `ask` route handler to pass through the `inspect` query param:

```python
@router.post('/ask', response_model=AskResponse)
async def ask(req: AskRequest, inspect: bool = False) -> AskResponse:
    try:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            _pool, _ask_sync_with_inspect, req.tenant_id, req.question, req.conversation_id, inspect,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _ask_sync_with_inspect(tenant_id: str, question: str, conversation_id: str | None, inspect: bool) -> AskResponse:
    """Wrapper because run_in_executor doesn't take kwargs."""
    return _ask_sync(tenant_id, question, conversation_id, inspect=inspect)
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_router_genie_inspector.py tests/test_smoke.py -v
```

Expected: 2 + 3 = 5 PASSED.

- [ ] **Step 5: Commit**

```bash
git add server/routers/genie.py tests/test_router_genie_inspector.py
git commit -m "Add inspector payload on POST /api/genie/ask?inspect=true"
```

---

## Task 11: End-to-end smoke verification

Confirm everything Phase 2 added still imports cleanly, the new endpoints register, and the full test suite is green except for the documented Postgres-skipping ones.

**Files:** none (verification only)

- [ ] **Step 1: Run all tests**

```bash
pytest tests/ -v
```

Expected: smoke (3) + db (3 SKIPPED) + tenant (6 SKIPPED) + audit-repo (3 SKIPPED) + credential-repo (6 SKIPPED) + bulk-onboard-job (5) + router-bulk-onboard (4) + router-lifecycle (4) + router-audit (3) + verifier (4) + router-verify (1) + inspector (4) + router-genie-inspector (2) = **27 PASSED + 18 SKIPPED**.

- [ ] **Step 2: Confirm no broken imports**

```bash
python -c "from server.app import app; print('routes:', len(app.routes))"
```

Expected: prints a count of routes (>= 14, since we added several).

- [ ] **Step 3: Confirm new endpoints registered**

```bash
python -c "from server.app import app; print(sorted({r.path for r in app.routes if hasattr(r, 'path')}))"
```

Expected: includes `/api/tenants/bulk`, `/api/jobs/{job_id}`, `/api/tenants/{tenant_id}/reactivate`, `/api/tenants/{tenant_id}` (DELETE), `/api/tenants/{tenant_id}/history`, `/api/audit`, `/api/audit/mapping`, `/api/verify`, plus the existing routes.

- [ ] **Step 4: Git status + log**

```bash
git status
git log --oneline b428c87..HEAD
```

Expected: clean tree, ~10 new commits since the start of Phase 2 (the `b428c87` commit was the final Phase 1 cleanup).

- [ ] **Step 5: Summarize**

Write a one-paragraph summary:
- What Phase 2 added (lifecycle ops, bulk job runner, verifier, inspector, audit-router split).
- Test counts (27 passed, 18 skipped — Postgres-backed).
- What's NOT verified locally (anything Postgres-touching).
- Suggested next step: bring up Docker → run `pytest tests/` → 45 passed; then move to Phase 3 (UI rebuild).

- [ ] **Step 6: No commit needed unless verification surfaces fixes**

If anything failed, fix and commit. Otherwise, Phase 2 is done.

---

## Phase 2 done

When all 11 tasks are checked, the API surface for Phase 3 is complete:

- `POST /api/tenants/bulk` + `GET /api/jobs/{job_id}` (N1)
- `POST /api/tenants/{id}/rotate` (Phase 1) + `/deactivate` (Phase 1) + `/reactivate` (Task 4) + `DELETE /api/tenants/{id}` (Task 4) (N2)
- `POST /api/verify` (N3)
- `GET /api/tenants/{id}/history` (N4)
- `POST /api/genie/ask?inspect=true` returning an `inspector` block (F2)
- `GET /api/audit` (now reads from Lakebase, not the dead UC table)
- `GET /api/audit/mapping` (renamed from `/tenants/mapping`)

The UI still consumes only the old endpoints — nothing visible to a user. Phase 3 rebuilds the UI on top of this new API surface.
