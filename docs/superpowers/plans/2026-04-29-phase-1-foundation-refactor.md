# Phase 1 — Foundation Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Strip BCD/Advito branding, restructure the repo (`api/` → `server/`, flatten `src/`, introduce `domain/` and `sql/lakebase/`), introduce Lakebase as the OLTP metadata store via a repository pattern, and ship `bootstrap.sh` + `docker-compose.yml`. Same features as today, new shape.

**Architecture:** Three logical stages, executed in order:
1. **Clean & restructure** — branding scrub, dead-doc deletion, mechanical file moves with import updates. The app keeps using UC Delta as its only store; nothing functional changes.
2. **Lakebase wiring** — add psycopg + Postgres docker-compose, write `server/lib/db.py` and four repositories (TDD against a real Postgres). The repositories are not yet called by `SPManager`.
3. **Switch the implementation** — refactor `SPManager` and routers to use repositories. Per-tenant SP credentials move from `.demo-secrets.env` (today) to `sp_credentials` in Lakebase, encrypted with AES-GCM. Onboarding becomes transactional with rollback. Add domain layer + bootstrap script.

**Tech Stack:** Python 3.11, FastAPI, psycopg 3 (raw SQL), Postgres 16 (docker-compose for local), Databricks SDK, AES-GCM via `cryptography`, pytest, Vite/React (untouched in Phase 1).

**Working tree state assumed at start:** branch `generalize-and-scale`, on commit `782b3b8` (the design spec). Current shape: `api/`, `src/lib/`, `src/scripts/`, `src/sql/`, `src/proxy/` (empty), `src/ui/` (single unused `app.py`), `web/`, `docs/`, `diagrams/`.

---

## Task 1: Smoke test scaffolding

We need a baseline of "the app imports and starts" before any moves, so each subsequent refactor task can run `pytest tests/test_smoke.py` to confirm it didn't break the wiring.

**Files:**
- Modify: `pyproject.toml.template` → `pyproject.toml` (rename and activate)
- Create: `tests/__init__.py` (empty)
- Create: `tests/conftest.py`
- Create: `tests/test_smoke.py`

- [ ] **Step 1: Activate pyproject.toml**

```bash
mv pyproject.toml.template pyproject.toml
```

- [ ] **Step 2: Add the dev deps we'll need across the plan**

Edit `pyproject.toml` — under `[project] dependencies`, add:

```toml
"psycopg[binary]>=3.2.0",
"cryptography>=42.0.0",
```

Under `[project.optional-dependencies] dev`, add:

```toml
"testcontainers[postgres]>=4.0.0",
```

- [ ] **Step 3: Install deps**

```bash
pip install -e ".[dev]"
```

Expected: completes without error.

- [ ] **Step 4: Write the smoke test**

```python
# tests/conftest.py
import sys
from pathlib import Path

# Repo root on sys.path so `from server.lib...` and `from api.routers...` both resolve
REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
```

```python
# tests/test_smoke.py
"""Baseline smoke test: the FastAPI app imports without error.

Used as a tripwire for the file-move tasks in this plan. After each move,
`pytest tests/test_smoke.py` should pass.
"""
import importlib


def test_app_imports():
    mod = importlib.import_module("api.app")
    assert mod.app is not None


def test_routers_import():
    importlib.import_module("api.routers")


def test_lib_imports():
    importlib.import_module("src.lib.config")
    importlib.import_module("src.lib.sp_manager")
    importlib.import_module("src.lib.genie_client")
    importlib.import_module("src.lib.token_minter")
```

- [ ] **Step 5: Run the smoke test**

```bash
pytest tests/test_smoke.py -v
```

Expected: 3 PASSED. If any fails, stop and fix the import path before continuing — the baseline must be green.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml tests/
git commit -m "Add pyproject.toml + smoke test scaffolding"
```

---

## Task 2: Strip BCD/Advito branding from web TSX

The branding lives in four files. Replace BCD/Advito-specific copy with generic reference-solution copy. Functional UI is unchanged; this is a copy edit.

**Files:**
- Modify: `web/src/App.tsx:35` (header subtitle)
- Modify: `web/src/pages/AdminPage.tsx:187` (overview blurb)
- Modify: `web/src/pages/ClientPage.tsx:99-104` (client view header)
- Modify: `web/src/pages/ArchitecturePage.tsx:174` (motivation pull-quote)

- [ ] **Step 1: Edit App.tsx subtitle**

Replace the existing line:

```tsx
BCD &amp; Advito embedded analytics — one service principal per client organization
```

with:

```tsx
A reference solution for delivering Genie to thousands of isolated tenants — one service principal per tenant
```

- [ ] **Step 2: Edit AdminPage.tsx overview blurb**

Replace the existing line:

```tsx
One Databricks SP per BCD / Advito client organization. Each
```

with:

```tsx
One Databricks SP per tenant organization. Each
```

- [ ] **Step 3: Edit ClientPage.tsx header (lines 99-104)**

Replace this block:

```tsx
                BCD &amp; Advito embedded analytics — multi-tenant isolation pattern
              </h1>
              <p className="text-sm text-muted-foreground mt-1">
                Same pattern for both surfaces: Advito embeds Genie in BCD Pay
                for ~130 client organizations; BCD Decision Source + CSS
                extend to the broader BCD client base. Every client sees only
```

with:

```tsx
                Embedded analytics — multi-tenant isolation pattern
              </h1>
              <p className="text-sm text-muted-foreground mt-1">
                Each tenant queries through its own Service Principal; UC row
                filters keep query results scoped to that tenant's data.
                The proxy mints per-tenant OAuth tokens and audits every
                request. Every tenant sees only
```

- [ ] **Step 4: Edit ArchitecturePage.tsx motivation pull-quote (line 174)**

Replace the existing pull-quote text (currently a long BCD-specific quote) with:

```tsx
            text='"Deliver Genie to thousands of tenants without giving any of them a Databricks account, and prove that tenant A can never see tenant B\'s data. The same pattern works for embedded analytics in a SaaS product, partner-facing reporting, and customer-portal dashboards."'
```

- [ ] **Step 5: Confirm no BCD/Advito strings remain in web/src**

```bash
grep -rni "bcd\|advito" web/src && echo "FOUND — go fix" || echo "clean"
```

Expected: `clean`.

- [ ] **Step 6: Run smoke test**

```bash
pytest tests/test_smoke.py -v
```

Expected: 3 PASSED.

- [ ] **Step 7: Commit**

```bash
git add web/src
git commit -m "Strip BCD/Advito branding from UI copy"
```

---

## Task 3: Delete POC residue docs

These files are point-in-time artifacts of the BCD POC. Per the spec, they're deleted (not archived); git history preserves them.

**Files:**
- Delete: `docs/poc.md`
- Delete: `docs/poc-flow.md`
- Delete: `docs/bcd-context.md`
- Delete: `docs/followup-email.md` (currently untracked)
- Delete: `docs/pattern-b-custom-claims.md`
- Modify: `README.md` (remove links to deleted docs)

- [ ] **Step 1: Delete the docs**

```bash
git rm docs/poc.md docs/poc-flow.md docs/bcd-context.md docs/pattern-b-custom-claims.md
rm -f docs/followup-email.md
```

- [ ] **Step 2: Remove links from README.md**

Open `README.md`. In the "Documentation" table, delete these rows:

- The row for `docs/bcd-context.md`
- The row for `docs/poc-flow.md`
- The row for `docs/pattern-b-custom-claims.md`

(Leave the rest of the README alone for now — the full README rewrite is Phase 4.)

- [ ] **Step 3: Confirm no broken links to deleted files**

```bash
grep -rn "bcd-context\|poc-flow\|pattern-b-custom-claims\|followup-email\|docs/poc.md" --include="*.md" . && echo "FOUND — go fix" || echo "clean"
```

Expected: `clean`.

- [ ] **Step 4: Commit**

```bash
git add README.md docs/
git commit -m "Delete POC residue docs"
```

---

## Task 4: Update README header (interim)

A full README rewrite is Phase 4. For Phase 1 we just want the top-of-file framing to stop saying "BCD/Advito" so the repo's first impression is honest about what it is.

**Files:**
- Modify: `README.md:1-12` (heading + problem statement)

- [ ] **Step 1: Replace the top section**

Replace lines 1–12 of `README.md` (everything from `# Multi-Tenant Genie Architecture` through the end of "Problem Statement") with:

```markdown
# Multi-Tenant Genie

A reference solution for delivering Databricks Genie to thousands of isolated tenants — one Service Principal per tenant, UC row filters for hard data isolation, no Databricks accounts for end users.

> **Status:** Refactoring to a generalized reference solution (branch `generalize-and-scale`). The full README + quickstart land in Phase 4 of the migration. See `docs/superpowers/specs/2026-04-28-generalize-and-scale-design.md` for the plan.

## Problem Statement

Deliver a natural-language analytics experience (via Databricks Genie Conversation API) to thousands of external tenants where:

- Each tenant queries their **own data only** (strict row-level isolation)
- Tenants authenticate via API keys — **no Databricks accounts required**
- The platform operator manages onboarding/offboarding without per-tenant Databricks provisioning
- Audit trails trace every query back to the originating tenant
```

- [ ] **Step 2: Confirm no BCD/Advito strings remain in README**

```bash
grep -ni "bcd\|advito" README.md && echo "FOUND" || echo "clean"
```

Expected: `clean`.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "Drop BCD/Advito framing from README header (interim)"
```

---

## Task 5: Move `api/` → `server/` (with import updates)

Mechanical move. The smoke test verifies imports survive.

**Files:**
- Rename: `api/` → `server/`
- Modify: `tests/test_smoke.py` (update imports)

- [ ] **Step 1: Move the directory**

```bash
git mv api server
```

- [ ] **Step 2: Verify no other code imports `api.`**

```bash
grep -rn "from api\|import api" --include="*.py" . && echo "review these" || echo "clean"
```

Expected: `clean` (the only references should already have moved with `git mv`). If anything turns up, update those paths too.

- [ ] **Step 3: Update smoke test**

In `tests/test_smoke.py`:

```python
def test_app_imports():
    mod = importlib.import_module("server.app")
    assert mod.app is not None


def test_routers_import():
    importlib.import_module("server.routers")
```

- [ ] **Step 4: Run smoke test**

```bash
pytest tests/test_smoke.py -v
```

Expected: 3 PASSED.

- [ ] **Step 5: Commit**

```bash
git add server tests/test_smoke.py
git commit -m "Rename api/ to server/"
```

---

## Task 6: Move `src/lib/` → `server/lib/` (with import updates)

The lib code becomes part of the server package.

**Files:**
- Rename: `src/lib/` → `server/lib/`
- Modify: `server/routers/tenants.py` (drop sys.path hack, update imports)
- Modify: `server/routers/genie.py` (same)
- Modify: `server/routers/workspace.py` (same)
- Modify: `tests/test_smoke.py` (update imports)
- Modify: `src/scripts/seed_demo.py` (update imports)
- Modify: `src/scripts/bulk_onboard.py` (update imports)
- Modify: `src/scripts/verify_isolation.py` (update imports)

- [ ] **Step 1: Move the directory**

```bash
git mv src/lib server/lib
```

- [ ] **Step 2: Update router imports**

In each of `server/routers/tenants.py`, `server/routers/genie.py`, `server/routers/workspace.py`:

Delete the `_REPO` / `sys.path.insert` block at the top (no longer needed once `server` is the package), and replace `from src.lib.X` with `from server.lib.X`.

For example, in `server/routers/tenants.py`, replace:

```python
import sys
from pathlib import Path
...
_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from src.lib.config import CONFIG  # noqa: E402
from src.lib.sp_manager import SPManager  # noqa: E402
```

with:

```python
from server.lib.config import CONFIG
from server.lib.sp_manager import SPManager
```

The `_REPO` constant is still used inside `_secrets_path()`. Replace its calculation:

```python
from pathlib import Path
_REPO = Path(__file__).resolve().parents[2]
```

This still resolves correctly because `server/routers/tenants.py` → `parents[2]` is the repo root.

- [ ] **Step 3: Update script imports**

In each of `src/scripts/seed_demo.py`, `src/scripts/bulk_onboard.py`, `src/scripts/verify_isolation.py`, replace `from src.lib.X` with `from server.lib.X`. Keep the `sys.path` shim — these scripts are still under `src/` for now (Task 7 moves them).

- [ ] **Step 4: Update smoke test imports**

In `tests/test_smoke.py`:

```python
def test_lib_imports():
    importlib.import_module("server.lib.config")
    importlib.import_module("server.lib.sp_manager")
    importlib.import_module("server.lib.genie_client")
    importlib.import_module("server.lib.token_minter")
```

- [ ] **Step 5: Confirm no `src.lib` references survive**

```bash
grep -rn "src\.lib\|from src import lib" --include="*.py" . && echo "FOUND — fix these" || echo "clean"
```

Expected: `clean`.

- [ ] **Step 6: Run smoke test**

```bash
pytest tests/test_smoke.py -v
```

Expected: 3 PASSED.

- [ ] **Step 7: Commit**

```bash
git add server tests src/scripts
git commit -m "Move src/lib/ to server/lib/"
```

---

## Task 7: Move `src/scripts/` → `scripts/`

**Files:**
- Rename: `src/scripts/` → `scripts/`
- Modify: `scripts/seed_demo.py:25-29` (the `sys.path` shim)
- Modify: `scripts/bulk_onboard.py` (same shim)
- Modify: `scripts/verify_isolation.py` (same shim)

- [ ] **Step 1: Move the directory**

```bash
git mv src/scripts scripts
```

- [ ] **Step 2: Update sys.path shim in each script**

In each of `scripts/seed_demo.py`, `scripts/bulk_onboard.py`, `scripts/verify_isolation.py`, the `_REPO = Path(__file__).resolve().parents[2]` shim now resolves wrong (one level off). Change to:

```python
_REPO = Path(__file__).resolve().parents[1]
```

- [ ] **Step 3: Confirm scripts still parse**

```bash
python -c "import ast; ast.parse(open('scripts/seed_demo.py').read())"
python -c "import ast; ast.parse(open('scripts/bulk_onboard.py').read())"
python -c "import ast; ast.parse(open('scripts/verify_isolation.py').read())"
```

Expected: no output (silent success).

- [ ] **Step 4: Run smoke test**

```bash
pytest tests/test_smoke.py -v
```

Expected: 3 PASSED.

- [ ] **Step 5: Commit**

```bash
git add scripts
git commit -m "Move src/scripts/ to scripts/"
```

---

## Task 8: Move `src/sql/` → `sql/`, fold row_filters into setup, set up `sql/lakebase/`

**Files:**
- Rename: `src/sql/setup.sql` → `sql/setup.sql`
- Delete: `src/sql/row_filters.sql` (content folded into `sql/setup.sql`)
- Rename: `src/sql/lakebase_schema.sql` → `sql/lakebase/V001__initial.sql`

- [ ] **Step 1: Read row_filters.sql to confirm what needs folding**

```bash
cat src/sql/row_filters.sql
```

Note: `src/sql/setup.sql` already contains the `tenant_row_filter` function and `ALTER TABLE … SET ROW FILTER` statements (per the file we read in spec phase). `row_filters.sql` is likely a duplicate or earlier draft. Verify by reading both, and only fold in any statements present in `row_filters.sql` but NOT in `setup.sql`.

- [ ] **Step 2: Move setup.sql**

```bash
mkdir -p sql/lakebase
git mv src/sql/setup.sql sql/setup.sql
```

If `row_filters.sql` contains anything not duplicated in `setup.sql`, append it to `sql/setup.sql` first.

- [ ] **Step 3: Delete row_filters.sql**

```bash
git rm src/sql/row_filters.sql
```

- [ ] **Step 4: Move lakebase_schema.sql to versioned migration**

```bash
git mv src/sql/lakebase_schema.sql sql/lakebase/V001__initial.sql
```

- [ ] **Step 5: Update any code references**

```bash
grep -rn "src/sql\|src\.sql" --include="*.py" --include="*.sh" --include="*.md" . && echo "review these" || echo "clean"
```

If anything turns up, update the path. (Likely candidates: `scripts/seed_demo.py` if it reads SQL files, README docs.)

- [ ] **Step 6: Run smoke test**

```bash
pytest tests/test_smoke.py -v
```

Expected: 3 PASSED.

- [ ] **Step 7: Commit**

```bash
git add sql src
git commit -m "Move src/sql/ to sql/, set up sql/lakebase/V001__initial.sql"
```

---

## Task 9: Delete `src/proxy/` and `src/ui/` (unused)

`src/proxy/` is empty. `src/ui/app.py` is a Streamlit app that predates the React UI; it's not referenced from anywhere.

**Files:**
- Delete: `src/proxy/`
- Delete: `src/ui/`
- Delete: `src/` (now empty)

- [ ] **Step 1: Confirm `src/ui/app.py` isn't imported anywhere**

```bash
grep -rn "src\.ui\|src/ui" --include="*.py" --include="*.sh" --include="*.md" . && echo "FOUND" || echo "clean"
```

Expected: `clean`.

- [ ] **Step 2: Confirm `src/proxy` is empty**

```bash
ls -A src/proxy
```

Expected: empty (only `__pycache__` if anything; ignore).

- [ ] **Step 3: Remove**

```bash
git rm -r src/ui
rm -rf src/proxy src/__pycache__
# Remove src/ if it now only contains __init__ remnants:
ls -A src 2>/dev/null && rmdir src 2>/dev/null || true
```

- [ ] **Step 4: Run smoke test**

```bash
pytest tests/test_smoke.py -v
```

Expected: 3 PASSED.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "Delete unused src/proxy/ and src/ui/"
```

---

## Task 10: Add docker-compose.yml for local Postgres

This file gives an SA running locally a one-command Postgres. It backs the new Lakebase repositories during local dev.

**Files:**
- Create: `docker-compose.yml`
- Modify: `.gitignore` (add postgres data volume)

- [ ] **Step 1: Write docker-compose.yml**

```yaml
# docker-compose.yml
# Local Postgres that stands in for Lakebase during dev.
# Bring up: docker compose up -d
# Connection string: postgresql://postgres:postgres@localhost:5432/mtg

services:
  postgres:
    image: postgres:16
    container_name: mt-genie-postgres
    environment:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
      POSTGRES_DB: mtg
    ports:
      - "5432:5432"
    volumes:
      - mt-genie-postgres-data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres -d mtg"]
      interval: 2s
      timeout: 2s
      retries: 30

volumes:
  mt-genie-postgres-data:
```

- [ ] **Step 2: Update .gitignore**

Append:

```
# Local docker volumes
.docker/
```

(The named volume above lives inside Docker itself, but if anyone uses bind mounts for debugging we want them ignored.)

- [ ] **Step 3: Bring it up and confirm it answers**

```bash
docker compose up -d
docker compose exec -T postgres pg_isready -U postgres -d mtg
```

Expected: `... accepting connections`.

- [ ] **Step 4: Commit**

```bash
git add docker-compose.yml .gitignore
git commit -m "Add docker-compose.yml for local Postgres"
```

---

## Task 11: Write `server/lib/db.py` — connection helper + migration runner (TDD)

The module that owns the Postgres connection and applies `sql/lakebase/V*.sql` migrations on startup.

**Files:**
- Create: `tests/test_db.py`
- Create: `server/lib/db.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_db.py
"""Tests for server.lib.db — connection + migration runner.

Requires `docker compose up -d` (Postgres on :5432). Skipped otherwise.
"""
import os
import pytest
import psycopg

from server.lib import db

LOCAL_DB = "postgresql://postgres:postgres@localhost:5432/mtg"


def _can_connect() -> bool:
    try:
        with psycopg.connect(LOCAL_DB, connect_timeout=2):
            return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _can_connect(),
    reason="Local Postgres not running — bring up docker-compose to run db tests",
)


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    """Reset the public schema before each test."""
    with psycopg.connect(LOCAL_DB, autocommit=True) as conn:
        conn.execute("DROP SCHEMA public CASCADE")
        conn.execute("CREATE SCHEMA public")
    monkeypatch.setenv("DATABASE_URL", LOCAL_DB)
    yield


def test_get_connection_returns_open_connection(fresh_db):
    with db.get_connection() as conn:
        assert not conn.closed
        cur = conn.execute("SELECT 1")
        assert cur.fetchone()[0] == 1


def test_apply_migrations_creates_schema_objects(fresh_db, tmp_path):
    # Write a tiny migration to a temp directory and point the runner at it
    mig_dir = tmp_path / "migrations"
    mig_dir.mkdir()
    (mig_dir / "V001__a.sql").write_text(
        "CREATE TABLE thing (id SERIAL PRIMARY KEY, name TEXT NOT NULL);"
    )
    (mig_dir / "V002__b.sql").write_text(
        "ALTER TABLE thing ADD COLUMN extra TEXT;"
    )
    db.apply_migrations(mig_dir)
    with db.get_connection() as conn:
        cols = [r[0] for r in conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'thing' ORDER BY ordinal_position"
        ).fetchall()]
        assert cols == ["id", "name", "extra"]


def test_apply_migrations_is_idempotent(fresh_db, tmp_path):
    mig_dir = tmp_path / "migrations"
    mig_dir.mkdir()
    (mig_dir / "V001__a.sql").write_text(
        "CREATE TABLE thing (id SERIAL PRIMARY KEY);"
    )
    db.apply_migrations(mig_dir)
    db.apply_migrations(mig_dir)  # Second run must not error
    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall()
        assert [r[0] for r in rows] == ["V001__a.sql"]
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
pytest tests/test_db.py -v
```

Expected: ImportError or ModuleNotFoundError on `server.lib.db`.

- [ ] **Step 3: Write the implementation**

```python
# server/lib/db.py
"""Postgres connection + idempotent migration runner.

In production (Databricks Apps), the Lakebase resource block injects
``DATABASE_URL`` as an env var. In local dev, ``docker-compose up -d``
provides a Postgres on :5432 and the developer points ``DATABASE_URL``
at it (default in ``.env.local``).

Migrations live under ``sql/lakebase/`` as ``V<NNN>__<name>.sql`` files
and are applied in lexicographic order. Applied versions are tracked in
the ``schema_migrations`` table; rerunning is a no-op.
"""
from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import psycopg

logger = logging.getLogger(__name__)


def database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set. In local dev, run "
            "`docker compose up -d` and `export DATABASE_URL=postgresql://postgres:postgres@localhost:5432/mtg`."
        )
    return url


@contextmanager
def get_connection() -> Iterator[psycopg.Connection]:
    """Yield a psycopg connection. Caller must commit or rollback."""
    conn = psycopg.connect(database_url())
    try:
        yield conn
    finally:
        conn.close()


def apply_migrations(migrations_dir: Path | str) -> None:
    """Apply every V*.sql in ``migrations_dir`` not yet recorded.

    Idempotent: re-running is a no-op once all files are recorded.
    """
    mig_dir = Path(migrations_dir)
    files = sorted(p for p in mig_dir.glob("V*.sql"))
    with psycopg.connect(database_url(), autocommit=True) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "  version TEXT PRIMARY KEY, "
            "  applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()"
            ")"
        )
        applied = {
            r[0] for r in conn.execute("SELECT version FROM schema_migrations").fetchall()
        }
        for f in files:
            if f.name in applied:
                continue
            logger.info("Applying migration %s", f.name)
            sql = f.read_text()
            conn.execute(sql)
            conn.execute(
                "INSERT INTO schema_migrations (version) VALUES (%s)",
                (f.name,),
            )
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_db.py -v
```

Expected: 3 PASSED.

- [ ] **Step 5: Commit**

```bash
git add server/lib/db.py tests/test_db.py
git commit -m "Add server/lib/db.py — connection + migration runner"
```

---

## Task 12: Write `server/lib/repository/tenant.py` (TDD)

The repository for `client_registry` (Lakebase). Note: the existing `V001__initial.sql` defines `client_registry` with columns including `tenant_id`, `display_name`, `tier`, `metadata`, `active`, `created_at`, `updated_at`. We add `genie_space_id` and a `sp_app_id` column we'll need (the existing schema doesn't include the SP linkage; today's UC `tenants` table holds it). Update `V001__initial.sql` accordingly.

**Files:**
- Modify: `sql/lakebase/V001__initial.sql` (add `genie_space_id`, `sp_app_id` columns to `client_registry`)
- Create: `server/lib/repository/__init__.py` (empty)
- Create: `tests/test_repository_tenant.py`
- Create: `server/lib/repository/tenant.py`

- [ ] **Step 1: Update V001__initial.sql**

In `sql/lakebase/V001__initial.sql`, change the `client_registry` table definition to:

```sql
CREATE TABLE client_registry (
    id SERIAL PRIMARY KEY,
    tenant_id VARCHAR(255) UNIQUE NOT NULL,
    display_name VARCHAR(255) NOT NULL,
    sp_app_id VARCHAR(255) UNIQUE NOT NULL,
    sp_display_name VARCHAR(255) NOT NULL,
    genie_space_id VARCHAR(255),                      -- NULL → use workspace global
    tier VARCHAR(50) DEFAULT 'standard',
    rate_limit_per_min INTEGER DEFAULT 3,
    status VARCHAR(50) NOT NULL DEFAULT 'active',     -- active | rotating | deactivated
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_client_registry_status ON client_registry(status);
CREATE INDEX idx_client_registry_sp_app ON client_registry(sp_app_id);
```

(Drop the old `api_key_hash` column — we use OAuth M2M, not API keys, so it never had a populated value in our flow.)

Also drop the `idx_client_api_key` and `idx_client_active` index definitions (no longer applicable).

- [ ] **Step 2: Write the failing test**

```python
# tests/test_repository_tenant.py
"""Tests for server.lib.repository.tenant — client_registry CRUD.

Requires `docker compose up -d` (Postgres on :5432). Skipped otherwise.
"""
import os
import pytest
import psycopg

from server.lib import db
from server.lib.repository import tenant as tenant_repo

LOCAL_DB = "postgresql://postgres:postgres@localhost:5432/mtg"


def _can_connect() -> bool:
    try:
        with psycopg.connect(LOCAL_DB, connect_timeout=2):
            return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _can_connect(), reason="Local Postgres not running"
)


@pytest.fixture
def fresh_db(monkeypatch):
    with psycopg.connect(LOCAL_DB, autocommit=True) as conn:
        conn.execute("DROP SCHEMA public CASCADE")
        conn.execute("CREATE SCHEMA public")
    monkeypatch.setenv("DATABASE_URL", LOCAL_DB)
    db.apply_migrations("sql/lakebase")
    yield


def test_insert_and_get(fresh_db):
    tenant_repo.insert(
        tenant_id="acme",
        display_name="Acme Industrial",
        sp_app_id="app-123",
        sp_display_name="mt-genie-acme",
    )
    t = tenant_repo.get("acme")
    assert t is not None
    assert t.tenant_id == "acme"
    assert t.display_name == "Acme Industrial"
    assert t.sp_app_id == "app-123"
    assert t.status == "active"
    assert t.genie_space_id is None


def test_get_missing_returns_none(fresh_db):
    assert tenant_repo.get("nope") is None


def test_list_returns_in_creation_order(fresh_db):
    tenant_repo.insert(tenant_id="a", display_name="A", sp_app_id="sp-a", sp_display_name="A")
    tenant_repo.insert(tenant_id="b", display_name="B", sp_app_id="sp-b", sp_display_name="B")
    rows = tenant_repo.list_all()
    ids = [r.tenant_id for r in rows]
    assert ids == ["b", "a"]  # newest first


def test_set_status(fresh_db):
    tenant_repo.insert(tenant_id="x", display_name="X", sp_app_id="sp-x", sp_display_name="X")
    tenant_repo.set_status("x", "deactivated")
    assert tenant_repo.get("x").status == "deactivated"


def test_delete_removes_row(fresh_db):
    tenant_repo.insert(tenant_id="y", display_name="Y", sp_app_id="sp-y", sp_display_name="Y")
    tenant_repo.delete("y")
    assert tenant_repo.get("y") is None


def test_insert_with_genie_space_override(fresh_db):
    tenant_repo.insert(
        tenant_id="z", display_name="Z", sp_app_id="sp-z", sp_display_name="Z",
        genie_space_id="space-42",
    )
    assert tenant_repo.get("z").genie_space_id == "space-42"
```

- [ ] **Step 3: Run test to confirm it fails**

```bash
pytest tests/test_repository_tenant.py -v
```

Expected: ImportError on `server.lib.repository.tenant`.

- [ ] **Step 4: Implement tenant_repo**

```python
# server/lib/repository/__init__.py
# (empty file)
```

```python
# server/lib/repository/tenant.py
"""client_registry CRUD against Lakebase / local Postgres."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from server.lib import db


@dataclass(frozen=True)
class TenantRow:
    tenant_id: str
    display_name: str
    sp_app_id: str
    sp_display_name: str
    status: str
    genie_space_id: Optional[str]
    metadata: dict
    created_at: datetime
    updated_at: datetime


_COLS = (
    "tenant_id, display_name, sp_app_id, sp_display_name, status, "
    "genie_space_id, metadata, created_at, updated_at"
)


def _row(r) -> TenantRow:
    return TenantRow(
        tenant_id=r[0],
        display_name=r[1],
        sp_app_id=r[2],
        sp_display_name=r[3],
        status=r[4],
        genie_space_id=r[5],
        metadata=r[6] or {},
        created_at=r[7],
        updated_at=r[8],
    )


def insert(
    *,
    tenant_id: str,
    display_name: str,
    sp_app_id: str,
    sp_display_name: str,
    genie_space_id: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> None:
    with db.get_connection() as conn:
        conn.execute(
            "INSERT INTO client_registry "
            "(tenant_id, display_name, sp_app_id, sp_display_name, genie_space_id, metadata) "
            "VALUES (%s, %s, %s, %s, %s, %s::jsonb)",
            (
                tenant_id,
                display_name,
                sp_app_id,
                sp_display_name,
                genie_space_id,
                _json(metadata or {}),
            ),
        )
        conn.commit()


def get(tenant_id: str) -> Optional[TenantRow]:
    with db.get_connection() as conn:
        cur = conn.execute(
            f"SELECT {_COLS} FROM client_registry WHERE tenant_id = %s",
            (tenant_id,),
        )
        row = cur.fetchone()
        return _row(row) if row else None


def list_all() -> list[TenantRow]:
    with db.get_connection() as conn:
        cur = conn.execute(
            f"SELECT {_COLS} FROM client_registry ORDER BY created_at DESC"
        )
        return [_row(r) for r in cur.fetchall()]


def set_status(tenant_id: str, status: str) -> None:
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE client_registry SET status = %s, updated_at = NOW() "
            "WHERE tenant_id = %s",
            (status, tenant_id),
        )
        conn.commit()


def delete(tenant_id: str) -> None:
    with db.get_connection() as conn:
        conn.execute("DELETE FROM client_registry WHERE tenant_id = %s", (tenant_id,))
        conn.commit()


def _json(d: dict) -> str:
    import json
    return json.dumps(d)
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/test_repository_tenant.py -v
```

Expected: 6 PASSED.

- [ ] **Step 6: Commit**

```bash
git add server/lib/repository sql/lakebase tests/test_repository_tenant.py
git commit -m "Add tenant repository with CRUD + V001 schema fix"
```

---

## Task 13: Write `server/lib/repository/audit.py` (TDD)

`audit_log` writes/reads. Used by every Genie ask plus admin actions.

**Files:**
- Create: `tests/test_repository_audit.py`
- Create: `server/lib/repository/audit.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_repository_audit.py
import pytest
import psycopg

from server.lib import db
from server.lib.repository import audit as audit_repo

LOCAL_DB = "postgresql://postgres:postgres@localhost:5432/mtg"


def _can_connect() -> bool:
    try:
        with psycopg.connect(LOCAL_DB, connect_timeout=2):
            return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _can_connect(), reason="Local Postgres not running")


@pytest.fixture
def fresh_db(monkeypatch):
    with psycopg.connect(LOCAL_DB, autocommit=True) as conn:
        conn.execute("DROP SCHEMA public CASCADE")
        conn.execute("CREATE SCHEMA public")
    monkeypatch.setenv("DATABASE_URL", LOCAL_DB)
    db.apply_migrations("sql/lakebase")
    yield


def test_append_and_read(fresh_db):
    audit_repo.append(
        tenant_id="acme",
        action="query",
        question="how many bookings",
        status="completed",
        latency_ms=1200,
    )
    rows = audit_repo.list_recent(limit=10)
    assert len(rows) == 1
    r = rows[0]
    assert r.tenant_id == "acme"
    assert r.action == "query"
    assert r.latency_ms == 1200


def test_per_tenant_history(fresh_db):
    for tid in ("a", "b", "a"):
        audit_repo.append(tenant_id=tid, action="query", status="completed")
    rows = audit_repo.history_for_tenant("a", limit=10)
    assert len(rows) == 2
    assert all(r.tenant_id == "a" for r in rows)


def test_recent_orders_newest_first(fresh_db):
    audit_repo.append(tenant_id="a", action="query", status="completed")
    audit_repo.append(tenant_id="b", action="query", status="completed")
    rows = audit_repo.list_recent(limit=10)
    assert rows[0].tenant_id == "b"
    assert rows[1].tenant_id == "a"
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
pytest tests/test_repository_audit.py -v
```

Expected: ImportError.

- [ ] **Step 3: Adjust V001__initial.sql audit_log to match what we write**

The existing `V001__initial.sql` has a `client_ip INET` column we never populate, and is missing an `action` column we need. Replace the `audit_log` definition with:

```sql
CREATE TABLE audit_log (
    id BIGSERIAL PRIMARY KEY,
    tenant_id VARCHAR(255),
    actor VARCHAR(255),
    action VARCHAR(50) NOT NULL,                  -- onboard | rotate | deactivate | reactivate | delete | query
    sp_app_id VARCHAR(255),
    question TEXT,
    genie_space_id VARCHAR(255),
    status VARCHAR(50) NOT NULL,                  -- pending | completed | failed | rate_limited | ok | error
    latency_ms INTEGER,
    rows_returned INTEGER,
    detail TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_audit_tenant_time ON audit_log(tenant_id, created_at DESC);
CREATE INDEX idx_audit_created ON audit_log(created_at DESC);
CREATE INDEX idx_audit_status ON audit_log(status);
CREATE INDEX idx_audit_action ON audit_log(action);
```

Drop the `error_message` column (we use `detail`); drop the `genie_conversation_id` and `genie_message_id` columns (Genie response carries them; we don't need them in the operational log).

- [ ] **Step 4: Implement audit_repo**

```python
# server/lib/repository/audit.py
"""audit_log writes/reads against Lakebase."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from server.lib import db


@dataclass(frozen=True)
class AuditRow:
    id: int
    tenant_id: Optional[str]
    actor: Optional[str]
    action: str
    sp_app_id: Optional[str]
    question: Optional[str]
    status: str
    latency_ms: Optional[int]
    detail: Optional[str]
    created_at: datetime


_COLS = (
    "id, tenant_id, actor, action, sp_app_id, question, status, "
    "latency_ms, detail, created_at"
)


def _row(r) -> AuditRow:
    return AuditRow(
        id=r[0],
        tenant_id=r[1],
        actor=r[2],
        action=r[3],
        sp_app_id=r[4],
        question=r[5],
        status=r[6],
        latency_ms=r[7],
        detail=r[8],
        created_at=r[9],
    )


def append(
    *,
    action: str,
    status: str,
    tenant_id: Optional[str] = None,
    actor: Optional[str] = None,
    sp_app_id: Optional[str] = None,
    question: Optional[str] = None,
    latency_ms: Optional[int] = None,
    detail: Optional[str] = None,
) -> None:
    with db.get_connection() as conn:
        conn.execute(
            "INSERT INTO audit_log "
            "(tenant_id, actor, action, sp_app_id, question, status, latency_ms, detail) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (tenant_id, actor, action, sp_app_id, question, status, latency_ms, detail),
        )
        conn.commit()


def list_recent(limit: int = 50) -> list[AuditRow]:
    with db.get_connection() as conn:
        cur = conn.execute(
            f"SELECT {_COLS} FROM audit_log ORDER BY created_at DESC LIMIT %s",
            (limit,),
        )
        return [_row(r) for r in cur.fetchall()]


def history_for_tenant(tenant_id: str, limit: int = 50) -> list[AuditRow]:
    with db.get_connection() as conn:
        cur = conn.execute(
            f"SELECT {_COLS} FROM audit_log WHERE tenant_id = %s "
            "ORDER BY created_at DESC LIMIT %s",
            (tenant_id, limit),
        )
        return [_row(r) for r in cur.fetchall()]
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/test_repository_audit.py -v
```

Expected: 3 PASSED.

- [ ] **Step 6: Commit**

```bash
git add server/lib/repository/audit.py sql/lakebase tests/test_repository_audit.py
git commit -m "Add audit repository + V001 audit_log column cleanup"
```

---

## Task 14: Write `server/lib/repository/credential.py` with AES-GCM (TDD)

`sp_credentials` stores per-tenant OAuth secrets, encrypted at rest with AES-GCM. The AES key is read from env (`AES_KEY_BASE64` — 32 bytes base64-encoded) and is optional in local dev (warns + stores plaintext if missing).

**Files:**
- Modify: `sql/lakebase/V001__initial.sql` (rework `sp_credentials` table)
- Create: `tests/test_repository_credential.py`
- Create: `server/lib/repository/credential.py`

- [ ] **Step 1: Update V001 sp_credentials definition**

The existing `sp_credentials` table is geared toward storing a small set of admin SPs labelled by name. We instead need one row per *tenant SP* with the OAuth secret encrypted. Replace with:

```sql
CREATE TABLE sp_credentials (
    sp_app_id VARCHAR(255) PRIMARY KEY,
    -- AES-GCM ciphertext (nonce || ciphertext || tag); base64 in column.
    -- If aes_key is unset (local dev), value is stored as `plain:<secret>`
    -- and a startup warning is logged.
    secret_encrypted TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    rotated_at TIMESTAMPTZ
);
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_repository_credential.py
import base64
import os
import pytest
import psycopg

from server.lib import db
from server.lib.repository import credential as cred_repo

LOCAL_DB = "postgresql://postgres:postgres@localhost:5432/mtg"


def _can_connect() -> bool:
    try:
        with psycopg.connect(LOCAL_DB, connect_timeout=2):
            return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _can_connect(), reason="Local Postgres not running")


@pytest.fixture
def fresh_db(monkeypatch):
    with psycopg.connect(LOCAL_DB, autocommit=True) as conn:
        conn.execute("DROP SCHEMA public CASCADE")
        conn.execute("CREATE SCHEMA public")
    monkeypatch.setenv("DATABASE_URL", LOCAL_DB)
    db.apply_migrations("sql/lakebase")
    yield


@pytest.fixture
def with_aes_key(monkeypatch):
    key = base64.urlsafe_b64encode(os.urandom(32)).decode()
    monkeypatch.setenv("AES_KEY_BASE64", key)
    yield key


@pytest.fixture
def without_aes_key(monkeypatch):
    monkeypatch.delenv("AES_KEY_BASE64", raising=False)
    yield


def test_put_and_get_with_key(fresh_db, with_aes_key):
    cred_repo.put("app-123", "super-secret")
    assert cred_repo.get("app-123") == "super-secret"


def test_put_and_get_without_key_uses_plaintext_marker(fresh_db, without_aes_key):
    cred_repo.put("app-456", "another-secret")
    # Verify it's stored plaintext (with the marker) — the test reads the
    # raw row so we know the warning path actually wrote `plain:`.
    with db.get_connection() as conn:
        raw = conn.execute(
            "SELECT secret_encrypted FROM sp_credentials WHERE sp_app_id = %s",
            ("app-456",),
        ).fetchone()[0]
    assert raw.startswith("plain:")
    assert cred_repo.get("app-456") == "another-secret"


def test_round_trip_ciphertext_is_not_plaintext(fresh_db, with_aes_key):
    cred_repo.put("app-789", "hunter2")
    with db.get_connection() as conn:
        raw = conn.execute(
            "SELECT secret_encrypted FROM sp_credentials WHERE sp_app_id = %s",
            ("app-789",),
        ).fetchone()[0]
    assert "hunter2" not in raw
    assert not raw.startswith("plain:")


def test_get_missing_returns_none(fresh_db, with_aes_key):
    assert cred_repo.get("nope") is None


def test_delete(fresh_db, with_aes_key):
    cred_repo.put("app-x", "secret")
    cred_repo.delete("app-x")
    assert cred_repo.get("app-x") is None


def test_rotate_overwrites(fresh_db, with_aes_key):
    cred_repo.put("app-r", "old")
    cred_repo.put("app-r", "new")  # overwrite
    assert cred_repo.get("app-r") == "new"
```

- [ ] **Step 3: Run test to confirm it fails**

```bash
pytest tests/test_repository_credential.py -v
```

Expected: ImportError.

- [ ] **Step 4: Implement credential repo**

```python
# server/lib/repository/credential.py
"""sp_credentials with AES-GCM encryption-at-rest.

Production: ``AES_KEY_BASE64`` env var holds the 32-byte key, base64-encoded.
Local dev: if the env var is absent, secrets are stored with a ``plain:``
prefix and a loud WARN is logged on startup. Production deploy fails closed
if the key is missing (enforced by ``server.lib.config``).
"""
from __future__ import annotations

import base64
import logging
import os
from typing import Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from server.lib import db

logger = logging.getLogger(__name__)

PLAIN_MARKER = "plain:"


def _key() -> Optional[bytes]:
    raw = os.environ.get("AES_KEY_BASE64")
    if not raw:
        return None
    return base64.urlsafe_b64decode(raw)


def _encrypt(plaintext: str) -> str:
    key = _key()
    if key is None:
        logger.warning(
            "AES_KEY_BASE64 unset — storing SP credential as plaintext "
            "(local-dev only). Set AES_KEY_BASE64 in production."
        )
        return PLAIN_MARKER + plaintext
    aes = AESGCM(key)
    nonce = os.urandom(12)
    ct = aes.encrypt(nonce, plaintext.encode(), associated_data=None)
    return base64.b64encode(nonce + ct).decode()


def _decrypt(value: str) -> str:
    if value.startswith(PLAIN_MARKER):
        return value[len(PLAIN_MARKER):]
    key = _key()
    if key is None:
        raise RuntimeError(
            "Stored credential is encrypted but AES_KEY_BASE64 is unset"
        )
    raw = base64.b64decode(value)
    nonce, ct = raw[:12], raw[12:]
    aes = AESGCM(key)
    return aes.decrypt(nonce, ct, associated_data=None).decode()


def put(sp_app_id: str, secret: str) -> None:
    enc = _encrypt(secret)
    with db.get_connection() as conn:
        conn.execute(
            "INSERT INTO sp_credentials (sp_app_id, secret_encrypted) "
            "VALUES (%s, %s) "
            "ON CONFLICT (sp_app_id) DO UPDATE "
            "SET secret_encrypted = EXCLUDED.secret_encrypted, "
            "    rotated_at = NOW()",
            (sp_app_id, enc),
        )
        conn.commit()


def get(sp_app_id: str) -> Optional[str]:
    with db.get_connection() as conn:
        cur = conn.execute(
            "SELECT secret_encrypted FROM sp_credentials WHERE sp_app_id = %s",
            (sp_app_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return _decrypt(row[0])


def delete(sp_app_id: str) -> None:
    with db.get_connection() as conn:
        conn.execute(
            "DELETE FROM sp_credentials WHERE sp_app_id = %s", (sp_app_id,)
        )
        conn.commit()
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/test_repository_credential.py -v
```

Expected: 6 PASSED.

- [ ] **Step 6: Commit**

```bash
git add server/lib/repository/credential.py sql/lakebase tests/test_repository_credential.py
git commit -m "Add credential repository with AES-GCM encryption-at-rest"
```

---

## Task 15: Write `server/lib/repository/mapping.py` (UC Delta)

`sp_tenant_mapping` stays in UC because the row filter SQL joins it. This repo's job is to wrap the UC writes so callers don't talk to the warehouse client directly. No Postgres involvement.

**Files:**
- Create: `server/lib/repository/mapping.py`

(No unit test — the repo wraps the warehouse client and the meaningful test is the live isolation test in `scripts/verify_isolation.py`. Mocking `WorkspaceClient.statement_execution` to test SQL string assembly would test our mock, not the repo. We skip and rely on the integration test in Task 23.)

- [ ] **Step 1: Implement mapping repo**

```python
# server/lib/repository/mapping.py
"""sp_tenant_mapping in UC Delta (joined by the row filter)."""
from __future__ import annotations

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import StatementState

from server.lib.config import CONFIG


def _execute(w: WorkspaceClient, warehouse_id: str, sql: str) -> None:
    resp = w.statement_execution.execute_statement(
        warehouse_id=warehouse_id, statement=sql, wait_timeout="30s"
    )
    while resp.status.state in (StatementState.PENDING, StatementState.RUNNING):
        import time
        time.sleep(0.5)
        resp = w.statement_execution.get_statement(resp.statement_id)
    if resp.status.state != StatementState.SUCCEEDED:
        raise RuntimeError(f"UC statement failed: {resp.status.error}")


def insert_mapping(w: WorkspaceClient, warehouse_id: str, sp_app_id: str, tenant_id: str) -> None:
    _execute(
        w, warehouse_id,
        f"INSERT INTO {CONFIG.fq_mapping} (sp_app_id, tenant_id, active) "
        f"VALUES ('{sp_app_id}', '{tenant_id}', true)",
    )


def deactivate_mapping(w: WorkspaceClient, warehouse_id: str, sp_app_id: str) -> None:
    _execute(
        w, warehouse_id,
        f"UPDATE {CONFIG.fq_mapping} SET active = false WHERE sp_app_id = '{sp_app_id}'",
    )


def activate_mapping(w: WorkspaceClient, warehouse_id: str, sp_app_id: str) -> None:
    _execute(
        w, warehouse_id,
        f"UPDATE {CONFIG.fq_mapping} SET active = true WHERE sp_app_id = '{sp_app_id}'",
    )


def delete_mapping(w: WorkspaceClient, warehouse_id: str, sp_app_id: str) -> None:
    _execute(
        w, warehouse_id,
        f"DELETE FROM {CONFIG.fq_mapping} WHERE sp_app_id = '{sp_app_id}'",
    )
```

- [ ] **Step 2: Smoke test still green**

```bash
pytest tests/test_smoke.py -v
```

Expected: 3 PASSED.

- [ ] **Step 3: Commit**

```bash
git add server/lib/repository/mapping.py
git commit -m "Add UC mapping repository"
```

---

## Task 16: Refactor `SPManager` to use repositories

Today `SPManager.list_tenants()` reads the UC `tenants` table. After this task it reads from Lakebase via `tenant_repo`. UC `sp_tenant_mapping` writes go through `mapping_repo`. Audit goes through `audit_repo`. Per-tenant secrets go through `credential_repo`.

The legacy UC `tenants` table is no longer written to. We leave it in `sql/setup.sql` for now (Task 22 might prune it) — no harm in the table existing while unused, and removing it from `setup.sql` would break the existing `seed_demo.py` until that's also refactored.

**Files:**
- Modify: `server/lib/sp_manager.py` (significant rewrite — keeps the same public method shapes)

- [ ] **Step 1: Replace `list_tenants()`, `_fetch_tenant()`, `_audit()`**

In `server/lib/sp_manager.py`, replace these three methods with versions that delegate to repositories:

```python
def list_tenants(self, include_deactivated: bool = True) -> list[Tenant]:
    from server.lib.repository import tenant as tenant_repo
    rows = tenant_repo.list_all()
    if not include_deactivated:
        rows = [r for r in rows if r.status != "deactivated"]
    return [
        Tenant(
            tenant_id=r.tenant_id,
            tenant_name=r.display_name,
            sp_app_id=r.sp_app_id,
            sp_display_name=r.sp_display_name,
            status=r.status,
            created_at=r.created_at,
            updated_at=r.updated_at,
        )
        for r in rows
    ]


def _fetch_tenant(self, tenant_id: str) -> Tenant:
    from server.lib.repository import tenant as tenant_repo
    r = tenant_repo.get(tenant_id)
    if not r:
        raise LookupError(f"Tenant {tenant_id} not found")
    return Tenant(
        tenant_id=r.tenant_id,
        tenant_name=r.display_name,
        sp_app_id=r.sp_app_id,
        sp_display_name=r.sp_display_name,
        status=r.status,
        created_at=r.created_at,
        updated_at=r.updated_at,
    )


def _audit(
    self, action: str, tenant_id: str, sp_app_id: str, *,
    detail: str | None = None,
    latency_ms: int | None = None,
    status: str = "ok",
    question: str | None = None,
) -> None:
    from server.lib.repository import audit as audit_repo
    actor = "unknown"
    try:
        actor = self.w.current_user.me().user_name or "unknown"
    except Exception:
        pass
    audit_repo.append(
        action=action, status=status, tenant_id=tenant_id, actor=actor,
        sp_app_id=sp_app_id, question=question, latency_ms=latency_ms, detail=detail,
    )
```

- [ ] **Step 2: Replace `onboard_tenant()` to be transactional**

Replace the existing method with:

```python
def onboard_tenant(self, tenant_id: str, tenant_name: str) -> OnboardResult:
    """Create SP, mint secret, register in Lakebase + UC mapping. Roll back on any failure."""
    from server.lib.repository import (
        tenant as tenant_repo,
        credential as cred_repo,
        mapping as mapping_repo,
    )

    display = f"{CONFIG.sp_display_prefix}-{tenant_id}"
    logger.info("Creating SP %s", display)
    sp = self.w.service_principals.create(display_name=display, active=True)
    sp_app_id = sp.application_id
    sp_db_id = sp.id

    try:
        secret = self.w.service_principal_secrets_proxy.create(
            service_principal_id=sp_db_id
        )
        client_secret = secret.secret

        # 1. UC mapping (row-filter join target)
        mapping_repo.insert_mapping(self.w, self.warehouse_id, sp_app_id, tenant_id)

        # 2. Lakebase: tenant + credential
        tenant_repo.insert(
            tenant_id=tenant_id,
            display_name=tenant_name,
            sp_app_id=sp_app_id,
            sp_display_name=display,
        )
        cred_repo.put(sp_app_id, client_secret)
    except Exception as e:
        # Roll back: delete UC mapping (if it was inserted), delete Lakebase rows, delete SP
        try:
            mapping_repo.delete_mapping(self.w, self.warehouse_id, sp_app_id)
        except Exception:
            pass
        try:
            tenant_repo.delete(tenant_id)
        except Exception:
            pass
        try:
            cred_repo.delete(sp_app_id)
        except Exception:
            pass
        try:
            self.w.service_principals.delete(id=sp_db_id)
        except Exception:
            pass
        raise

    self._audit("onboard", tenant_id, sp_app_id, detail=f"sp_db_id={sp_db_id}")

    now = datetime.now(timezone.utc)
    return OnboardResult(
        tenant=Tenant(
            tenant_id=tenant_id, tenant_name=tenant_name,
            sp_app_id=sp_app_id, sp_display_name=display,
            status="active", created_at=now, updated_at=now,
        ),
        client_id=sp_app_id,
        client_secret=client_secret,
    )
```

- [ ] **Step 3: Replace `rotate_secret()`**

```python
def rotate_secret(self, tenant_id: str) -> str:
    from server.lib.repository import credential as cred_repo
    tenant = self._fetch_tenant(tenant_id)
    sp_db_id = self._sp_db_id(tenant.sp_app_id)

    existing = list(self.w.service_principal_secrets_proxy.list(
        service_principal_id=sp_db_id
    ))
    fresh = self.w.service_principal_secrets_proxy.create(service_principal_id=sp_db_id)

    cred_repo.put(tenant.sp_app_id, fresh.secret)

    for s in existing:
        try:
            self.w.service_principal_secrets_proxy.delete(
                service_principal_id=sp_db_id, secret_id=s.id
            )
        except Exception as e:
            logger.warning("Could not delete old secret %s: %s", s.id, e)

    from server.lib.repository import tenant as tenant_repo
    tenant_repo.set_status(tenant_id, "active")
    self._audit("rotate", tenant_id, tenant.sp_app_id)
    return fresh.secret
```

- [ ] **Step 4: Replace `deactivate_tenant()`**

```python
def deactivate_tenant(self, tenant_id: str) -> None:
    from server.lib.repository import (
        tenant as tenant_repo, credential as cred_repo, mapping as mapping_repo
    )
    tenant = self._fetch_tenant(tenant_id)
    sp_db_id = self._sp_db_id(tenant.sp_app_id)

    self.w.service_principals.update(
        id=sp_db_id, active=False,
        application_id=tenant.sp_app_id, display_name=tenant.sp_display_name,
    )
    for s in self.w.service_principal_secrets_proxy.list(service_principal_id=sp_db_id):
        self.w.service_principal_secrets_proxy.delete(
            service_principal_id=sp_db_id, secret_id=s.id
        )

    cred_repo.delete(tenant.sp_app_id)
    mapping_repo.deactivate_mapping(self.w, self.warehouse_id, tenant.sp_app_id)
    tenant_repo.set_status(tenant_id, "deactivated")
    self._audit("deactivate", tenant_id, tenant.sp_app_id)
```

- [ ] **Step 5: Run smoke test**

```bash
pytest tests/test_smoke.py -v
```

Expected: 3 PASSED.

- [ ] **Step 6: Commit**

```bash
git add server/lib/sp_manager.py
git commit -m "Refactor SPManager to use repositories with transactional onboard"
```

---

## Task 17: Update routers — drop `.demo-secrets.env` and use credential_repo

Today `server/routers/tenants.py` and `server/routers/genie.py` shuttle per-tenant secrets through a `.demo-secrets.env` file in the repo root. With `credential_repo` in place, that file goes away.

**Files:**
- Modify: `server/routers/tenants.py` (drop `_load_secrets/_save_secrets/_secret_key/_secrets_path`)
- Modify: `server/routers/genie.py` (drop `_get_secret`, replace with `credential_repo.get`)

- [ ] **Step 1: Edit `server/routers/tenants.py`**

Delete:
- `_secrets_path()`, `_load_secrets()`, `_save_secrets()`, `_secret_key()` (functions)
- The `secrets = _load_secrets()` block in `list_tenants()` and the `has_local_secret` field math
- The `_save_secrets(secrets)` blocks in `onboard()`, `rotate()`, `deactivate()`

In `Tenant` (Pydantic): remove the `has_local_secret` field. (UI consumers must also stop expecting it — Task 19.)

Replace the `list_tenants()` body with:

```python
@router.get('', response_model=list[Tenant])
async def list_tenants() -> list[Tenant]:
    try:
        return [
            Tenant(
                tenant_id=t.tenant_id,
                tenant_name=t.tenant_name,
                sp_app_id=t.sp_app_id,
                sp_display_name=t.sp_display_name,
                status=t.status,
                created_at=t.created_at,
                updated_at=t.updated_at,
            )
            for t in _mgr().list_tenants()
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

Replace the entire `onboard()` body with:

```python
@router.post('/onboard', response_model=OnboardResponse)
async def onboard(req: OnboardRequest) -> OnboardResponse:
    try:
        tenant_id = req.tenant_id.strip().lower()
        tenant_name = req.tenant_name.strip()
        if not tenant_id or not tenant_name:
            raise ValueError('tenant_id and tenant_name are required')
        result = _mgr().onboard_tenant(tenant_id, tenant_name)
        _mgr().grant_data_access([tenant_id])
        _mgr().grant_genie_access([tenant_id])
        return OnboardResponse(
            tenant=Tenant(
                tenant_id=result.tenant.tenant_id,
                tenant_name=result.tenant.tenant_name,
                sp_app_id=result.tenant.sp_app_id,
                sp_display_name=result.tenant.sp_display_name,
                status=result.tenant.status,
                created_at=result.tenant.created_at,
                updated_at=result.tenant.updated_at,
            ),
            client_id=result.client_id,
            client_secret=result.client_secret,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

Replace the entire `rotate()` body with:

```python
@router.post('/{tenant_id}/rotate', response_model=RotateResponse)
async def rotate(tenant_id: str) -> RotateResponse:
    try:
        new_secret = _mgr().rotate_secret(tenant_id)
        for t in _mgr().list_tenants():
            if t.tenant_id == tenant_id:
                _invalidate_minter_cache(t.sp_app_id)
                break
        return RotateResponse(tenant_id=tenant_id, new_client_secret=new_secret)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

Replace the entire `deactivate()` body with:

```python
@router.post('/{tenant_id}/deactivate')
async def deactivate(tenant_id: str) -> dict[str, Any]:
    try:
        sp_app_id = ''
        for t in _mgr().list_tenants():
            if t.tenant_id == tenant_id:
                sp_app_id = t.sp_app_id
                break
        _mgr().deactivate_tenant(tenant_id)
        _invalidate_minter_cache(sp_app_id)
        return {'ok': True, 'tenant_id': tenant_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

- [ ] **Step 2: Edit `server/routers/genie.py`**

Replace `_get_secret(tenant_id)` with:

```python
def _get_secret_for_sp(sp_app_id: str) -> str | None:
    from server.lib.repository import credential as cred_repo
    return cred_repo.get(sp_app_id)
```

In `_ask_sync()`, replace:

```python
secret = _get_secret(tenant_id)
```

with (after the tenant lookup, so `tenant.sp_app_id` is known):

```python
secret = _get_secret_for_sp(tenant.sp_app_id)
```

Adjust the order: look up the tenant first, then fetch credentials by `sp_app_id`. Remove the `_load_secrets` import in this file.

Update the error message (no more `.demo-secrets.env`):

```python
if not secret:
    raise ValueError(
        f"No credential stored for tenant {tenant_id}. Rotate on the Admin tab to regenerate."
    )
```

- [ ] **Step 3: Delete `.demo-secrets.env` if it exists locally**

```bash
rm -f .demo-secrets.env
```

(It was always gitignored. Confirm with `cat .gitignore | grep secret` — should already be covered by `*secret*` pattern.)

- [ ] **Step 4: Run smoke test**

```bash
pytest tests/test_smoke.py -v
```

Expected: 3 PASSED.

- [ ] **Step 5: Commit**

```bash
git add server/routers
git commit -m "Move per-tenant secrets from .demo-secrets.env to credential_repo"
```

---

## Task 18: Drop `has_local_secret` from web

The Pydantic model dropped `has_local_secret`; the React types referenced it. Remove the references.

**Files:**
- Modify: `web/src/lib/api.ts` (drop the field from the `Tenant` type)
- Modify: `web/src/pages/AdminPage.tsx` (any references)
- Modify: `web/src/pages/ClientPage.tsx` (the active-tenant filter referenced `has_local_secret`)

- [ ] **Step 1: Drop the field from `Tenant` type**

In `web/src/lib/api.ts`, remove the `has_local_secret: boolean;` field from the `Tenant` type definition.

- [ ] **Step 2: Replace the active-tenant filter in ClientPage.tsx**

Today the filter is:

```tsx
(tenants.data ?? []).filter(
  (t) => t.status === "active" && t.has_local_secret,
)
```

Replace with:

```tsx
(tenants.data ?? []).filter((t) => t.status === "active")
```

The credential lookup now happens server-side; if the credential is missing, the `/ask` endpoint returns a clear error.

- [ ] **Step 3: Update AdminPage.tsx**

```bash
grep -n "has_local_secret" web/src/pages/AdminPage.tsx
```

For any reference: replace the conditional rendering with the equivalent based on `t.status === "active"`. (If a row was showing a "no local secret" warning, replace with no warning — the server enforces it now.)

- [ ] **Step 4: Confirm no more references**

```bash
grep -rn "has_local_secret" web/src && echo "FOUND" || echo "clean"
```

Expected: `clean`.

- [ ] **Step 5: Confirm web build passes**

```bash
cd web
npm install >/dev/null 2>&1 || npm install
npm run build
cd ..
```

Expected: build succeeds with no TypeScript errors. If a `has_local_secret` reference was missed, it shows up as a TS error here.

- [ ] **Step 6: Commit**

```bash
git add web/src
git commit -m "Drop has_local_secret from web — credentials live server-side now"
```

---

## Task 19: Wire migration runner into FastAPI lifespan

When the app starts, apply pending Lakebase migrations. Idempotent — no-op if already applied.

**Files:**
- Modify: `server/app.py`

- [ ] **Step 1: Edit lifespan**

In `server/app.py`, replace the `lifespan` function with:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Apply Lakebase migrations on startup."""
    from pathlib import Path
    from server.lib import db

    mig_dir = Path(__file__).resolve().parent.parent / "sql" / "lakebase"
    if mig_dir.exists() and any(mig_dir.glob("V*.sql")):
        try:
            db.apply_migrations(mig_dir)
        except Exception as e:
            # Surface the failure but don't crash silently
            import logging
            logging.exception("Lakebase migrations failed: %s", e)
            raise
    yield
```

- [ ] **Step 2: Run smoke test**

```bash
pytest tests/test_smoke.py -v
```

Expected: 3 PASSED. (The smoke test imports the app but doesn't call `lifespan` directly — psycopg connection failure won't surface here.)

- [ ] **Step 3: Manual verification**

```bash
docker compose up -d
export DATABASE_URL=postgresql://postgres:postgres@localhost:5432/mtg
uvicorn server.app:app --host 127.0.0.1 --port 8001 &
sleep 3
curl -s http://127.0.0.1:8001/health
kill %1
```

Expected: `{"status":"healthy"}`.

Then verify the migration ran:

```bash
docker compose exec -T postgres psql -U postgres -d mtg -c "\dt"
```

Expected: tables `client_registry`, `sp_credentials`, `audit_log`, `token_cache`, `schema_migrations` listed.

- [ ] **Step 4: Commit**

```bash
git add server/app.py
git commit -m "Apply Lakebase migrations on FastAPI startup"
```

---

## Task 20: Add `server/lib/domain.py` and `domain/travel/` skeleton

Create the swappable domain layer. For Phase 1 we move the existing travel-specific seed logic into `domain/travel/` and create the registry; the routers / UI don't yet consume `sample_questions` from the API (that's Phase 3).

**Files:**
- Create: `server/lib/domain.py`
- Create: `domain/__init__.py` (empty)
- Create: `domain/README.md`
- Create: `domain/travel/__init__.py` (empty)
- Create: `domain/travel/sample_questions.json`
- Create: `domain/travel/seed.py`
- Create: `domain/travel/schema.sql`

- [ ] **Step 1: Create the registry**

```python
# server/lib/domain.py
"""Domain registry — load the active dataset (e.g., travel, retail)."""
from __future__ import annotations

import importlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

REPO = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Domain:
    name: str
    sample_questions: list[str]
    row_filter_column: str
    schema_sql_path: Path
    seed_callable: Callable  # (sp_manager) -> None


def _domain_path(name: str) -> Path:
    p = REPO / "domain" / name
    if not p.exists():
        raise FileNotFoundError(f"Domain '{name}' not found at {p}")
    return p


def load(name: str | None = None) -> Domain:
    name = name or os.environ.get("DOMAIN", "travel")
    p = _domain_path(name)
    sq = json.loads((p / "sample_questions.json").read_text())
    seed_mod = importlib.import_module(f"domain.{name}.seed")
    return Domain(
        name=name,
        sample_questions=sq["questions"],
        row_filter_column=sq.get("row_filter_column", "tenant_id"),
        schema_sql_path=p / "schema.sql",
        seed_callable=seed_mod.seed,
    )
```

- [ ] **Step 2: Create domain/README.md**

```markdown
# Swappable Domain Layer

The active demo domain is selected by the `DOMAIN` env var (default: `travel`).

## To add a new domain

1. Copy `domain/travel/` to `domain/<your-name>/`.
2. Edit `schema.sql` to declare the tables Genie will query.
3. Edit `seed.py` to populate synthetic data per tenant.
4. Edit `sample_questions.json` with prompts that fit your schema.
5. Set `DOMAIN=<your-name>` in `.env.local` (local dev) or `app.yaml` (production).

The proxy and UI never reference your domain's table names directly — they
fetch sample questions and the row-filter column via the API.
```

- [ ] **Step 3: Create domain/travel/sample_questions.json**

```json
{
  "row_filter_column": "tenant_id",
  "questions": [
    "How many bookings do I have and what is my total spend?",
    "Show my top 5 routes by total spend",
    "What's my average booking amount, by cabin class?",
    "Which suppliers appear most in my bookings?",
    "Which cabin class do my travelers use most?"
  ]
}
```

- [ ] **Step 4: Create domain/travel/schema.sql**

Move the data-table portion of `sql/setup.sql` here. That is, the `bookings` and `customers` `CREATE TABLE` statements (with their `tenant_id` columns and the `ALTER TABLE … SET ROW FILTER` lines for them). Keep `sql/setup.sql` to contain the schema, `tenants` table (legacy, still consumed by old `seed_demo` until Task 21), `sp_tenant_mapping`, and the `tenant_row_filter` function definition.

`domain/travel/schema.sql`:

```sql
-- Travel-domain tables (swappable). Tenant_id is the row-filter column.
CREATE TABLE IF NOT EXISTS ${catalog}.${schema}.bookings (
    booking_id STRING NOT NULL,
    tenant_id STRING NOT NULL,
    traveler_name STRING,
    origin STRING,
    destination STRING,
    route STRING,
    supplier STRING,
    cabin_class STRING,
    amount_usd DOUBLE,
    booked_at TIMESTAMP
) USING DELTA
COMMENT 'Synthetic travel bookings, tenant-scoped via UC row filter';

CREATE TABLE IF NOT EXISTS ${catalog}.${schema}.customers (
    tenant_id STRING NOT NULL,
    customer_segment STRING,
    industry STRING,
    headquartered_in STRING,
    active_travelers INT
) USING DELTA;

ALTER TABLE ${catalog}.${schema}.bookings
  SET ROW FILTER ${catalog}.${schema}.tenant_row_filter ON (tenant_id);

ALTER TABLE ${catalog}.${schema}.customers
  SET ROW FILTER ${catalog}.${schema}.tenant_row_filter ON (tenant_id);
```

Edit `sql/setup.sql` to remove these statements (they live in `domain/travel/schema.sql` now).

- [ ] **Step 5: Move seed logic into domain/travel/seed.py**

The current `scripts/seed_demo.py` (formerly `src/scripts/seed_demo.py`) has a `seed_data_for_tenant()` function and `_random_bookings()`. Move just the booking/customer-generation logic to `domain/travel/seed.py` as:

```python
# domain/travel/seed.py
"""Travel-domain seed logic. Imported via the domain registry."""
from __future__ import annotations

import logging
import random
from datetime import datetime, timedelta, timezone
from typing import Iterable

log = logging.getLogger(__name__)

ROUTES = [
    ("SEA", "JFK"), ("SEA", "LHR"), ("SFO", "NRT"), ("SFO", "FRA"),
    ("ORD", "LAX"), ("AUS", "DEN"), ("DFW", "BOS"), ("LGA", "MIA"),
    ("PDX", "SFO"), ("CLE", "ATL"), ("DTW", "LHR"), ("ATL", "CDG"),
]
SUPPLIERS = ["Delta", "United", "American", "British Airways", "Lufthansa", "ANA"]
CABINS = ["Economy", "Premium Economy", "Business", "First"]


def seed(mgr, tenants: Iterable[dict]) -> None:
    """Seed bookings + customers for each tenant. ``mgr`` is an SPManager."""
    from server.lib.config import CONFIG

    for t in tenants:
        tid = t["tenant_id"]
        # customers row
        mgr._execute_sql(
            f"INSERT INTO {CONFIG.catalog}.{CONFIG.schema}.customers "
            f"(tenant_id, customer_segment, industry, headquartered_in, active_travelers) "
            f"VALUES ('{tid}', 'enterprise', '{t.get('industry','Other')}', "
            f"'{t.get('hq','—')}', {int(t.get('travelers', 100))})"
        )
        # bookings rows
        n = max(50, int(t.get("travelers", 100)) // 4)
        for _ in range(n):
            origin, dest = random.choice(ROUTES)
            supplier = random.choice(SUPPLIERS)
            cabin = random.choice(CABINS)
            amount = round(random.uniform(180, 9800), 2)
            booked = datetime.now(timezone.utc) - timedelta(days=random.randint(1, 365))
            mgr._execute_sql(
                f"INSERT INTO {CONFIG.catalog}.{CONFIG.schema}.bookings "
                f"(booking_id, tenant_id, traveler_name, origin, destination, route, supplier, cabin_class, amount_usd, booked_at) "
                f"VALUES (uuid(), '{tid}', 'Traveler', '{origin}', '{dest}', "
                f"'{origin}-{dest}', '{supplier}', '{cabin}', {amount}, "
                f"TIMESTAMP'{booked.isoformat()}')"
            )
```

- [ ] **Step 6: Smoke test**

```bash
pytest tests/test_smoke.py -v
```

Expected: 3 PASSED.

- [ ] **Step 7: Commit**

```bash
git add server/lib/domain.py domain sql/setup.sql
git commit -m "Add domain layer + travel/ as the first domain pack"
```

---

## Task 21: Refactor `scripts/seed_demo.py` to use the domain registry

Today `seed_demo.py` has hardcoded travel data and writes to a UC `tenants` table that we've now made redundant. Refactor it to:
- Use `server.lib.domain.load()` to pick up the active domain.
- Onboard tenants via `SPManager.onboard_tenant()` (which writes to Lakebase).
- Hand the active domain's `seed_callable` the list of demo tenants.

We delete the legacy UC `tenants` table reads — `client_registry` (Lakebase) is the source of truth now.

**Files:**
- Modify: `scripts/seed_demo.py` (significant rewrite)

- [ ] **Step 1: Rewrite the script**

Replace the body of `scripts/seed_demo.py` with:

```python
"""Bootstrap the multi-tenant Genie demo for the active domain.

Run after `docker compose up -d` (for Lakebase locally) and a workspace
profile that points at your target Databricks workspace.

Steps:
    1. Apply Lakebase migrations.
    2. Apply UC schema (sql/setup.sql + active domain's schema.sql).
    3. Onboard the demo tenants (writes to UC mapping + Lakebase registry + credentials).
    4. Run the active domain's seed() to populate per-tenant data.

Idempotent: re-running skips already-onboarded tenants and re-seeds only
empty tables.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from server.lib import db, domain  # noqa: E402
from server.lib.config import CONFIG  # noqa: E402
from server.lib.sp_manager import SPManager  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("seed")

DEMO_TENANTS = [
    {"tenant_id": "nike", "tenant_name": "Nike",
     "industry": "Retail / Apparel", "hq": "Beaverton, OR", "travelers": 840},
    {"tenant_id": "cloudventure", "tenant_name": "CloudVenture",
     "industry": "Technology", "hq": "Austin, TX", "travelers": 312},
    {"tenant_id": "acme", "tenant_name": "Acme Industrial",
     "industry": "Manufacturing", "hq": "Cleveland, OH", "travelers": 158},
]


def apply_lakebase_migrations():
    log.info("Applying Lakebase migrations from sql/lakebase/")
    db.apply_migrations(_REPO / "sql" / "lakebase")


def apply_uc_schema(mgr: SPManager, dom: domain.Domain):
    log.info("Applying UC schema (sql/setup.sql)")
    sql = (_REPO / "sql" / "setup.sql").read_text()
    sql = sql.replace("${catalog}", CONFIG.catalog).replace(
        "${schema}", CONFIG.schema
    ).replace("${admin_group}", CONFIG.admin_group)
    for stmt in (s.strip() for s in sql.split(";") if s.strip()):
        mgr._execute_sql(stmt)

    log.info("Applying domain schema (%s)", dom.schema_sql_path)
    dsql = dom.schema_sql_path.read_text()
    dsql = dsql.replace("${catalog}", CONFIG.catalog).replace(
        "${schema}", CONFIG.schema
    )
    for stmt in (s.strip() for s in dsql.split(";") if s.strip()):
        mgr._execute_sql(stmt)


def onboard_demo_tenants(mgr: SPManager):
    from server.lib.repository import tenant as tenant_repo
    for spec in DEMO_TENANTS:
        if tenant_repo.get(spec["tenant_id"]):
            log.info("Tenant %s already exists — skipping onboard", spec["tenant_id"])
            continue
        log.info("Onboarding %s", spec["tenant_id"])
        mgr.onboard_tenant(spec["tenant_id"], spec["tenant_name"])
        mgr.grant_data_access([spec["tenant_id"]])
        mgr.grant_genie_access([spec["tenant_id"]])


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--skip-uc", action="store_true",
                   help="Skip UC schema setup (use when only re-seeding data)")
    p.add_argument("--skip-onboard", action="store_true",
                   help="Skip tenant onboarding")
    args = p.parse_args()

    apply_lakebase_migrations()
    mgr = SPManager()
    dom = domain.load()
    log.info("Active domain: %s", dom.name)

    if not args.skip_uc:
        apply_uc_schema(mgr, dom)
    if not args.skip_onboard:
        onboard_demo_tenants(mgr)

    log.info("Seeding %s data for %d tenants", dom.name, len(DEMO_TENANTS))
    dom.seed_callable(mgr, DEMO_TENANTS)
    log.info("Done.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Smoke test**

```bash
pytest tests/test_smoke.py -v
```

Expected: 3 PASSED.

- [ ] **Step 3: Commit**

```bash
git add scripts/seed_demo.py
git commit -m "Refactor seed_demo to use domain registry + Lakebase repos"
```

---

## Task 22: Write `bootstrap.sh` and `docs/local-dev.md` (interim)

The one-command local-dev entry point.

**Files:**
- Create: `bootstrap.sh` (executable)
- Create: `docs/local-dev.md`

- [ ] **Step 1: Write bootstrap.sh**

```bash
#!/usr/bin/env bash
# bootstrap.sh — one-shot local-dev setup for multi-tenant-genie.
#
# Usage:
#   ./bootstrap.sh           # set up env, bring up Postgres, install deps
#   ./bootstrap.sh --demo    # the above + seed three demo tenants in your workspace
set -euo pipefail

cd "$(dirname "$0")"

ENV_FILE=".env.local"

if [ ! -f "$ENV_FILE" ]; then
    echo "Creating $ENV_FILE — answer a few questions:"
    read -rp "Databricks workspace host (e.g. https://abc.cloud.databricks.com): " HOST
    read -rp "Databricks profile name (from ~/.databrickscfg): " PROFILE
    read -rp "UC catalog: " CATALOG
    read -rp "UC schema (default: mt_genie): " SCHEMA
    SCHEMA="${SCHEMA:-mt_genie}"
    read -rp "Genie space ID: " GENIE
    cat > "$ENV_FILE" <<EOF
MT_GENIE_HOST=$HOST
MT_GENIE_PROFILE=$PROFILE
MT_GENIE_CATALOG=$CATALOG
MT_GENIE_SCHEMA=$SCHEMA
MT_GENIE_SPACE_ID=$GENIE
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/mtg
DOMAIN=travel
EOF
    echo "Wrote $ENV_FILE."
fi

# shellcheck disable=SC1090
set -a; source "$ENV_FILE"; set +a

echo "→ Bringing up local Postgres (docker-compose)…"
docker compose up -d

echo "→ Waiting for Postgres to accept connections…"
until docker compose exec -T postgres pg_isready -U postgres -d mtg >/dev/null 2>&1; do
    sleep 1
done

echo "→ Installing Python deps…"
pip install -e ".[dev]" >/dev/null

echo "→ Applying Lakebase migrations…"
python -c "from server.lib import db; db.apply_migrations('sql/lakebase')"

if [ "${1:-}" = "--demo" ]; then
    echo "→ Seeding demo tenants in workspace ${MT_GENIE_HOST}…"
    python -m scripts.seed_demo
fi

echo
echo "Done. To run the app:"
echo "  uvicorn server.app:app --reload --port 8000"
echo "And in another terminal:"
echo "  cd web && npm install && npm run dev"
```

```bash
chmod +x bootstrap.sh
```

- [ ] **Step 2: Write docs/local-dev.md (interim)**

```markdown
# Local Development

The full local-dev guide lands in Phase 4 of the migration. For now, the short version:

## Prerequisites

- Python 3.11+
- Docker (for the local Postgres that stands in for Lakebase)
- Node 18+ and npm (for the React UI)
- A Databricks workspace profile in `~/.databrickscfg` with admin permission on a target catalog and Genie space

## Quickstart

```bash
./bootstrap.sh           # interactive: writes .env.local, brings up Postgres, applies migrations
./bootstrap.sh --demo    # also seeds three demo tenants and their data
```

Then:

```bash
# Backend
uvicorn server.app:app --reload --port 8000

# Frontend (in another terminal)
cd web && npm install && npm run dev
```

The UI runs on http://localhost:5173 and proxies API calls to http://localhost:8000.

## What lives where

- **Tenants registry & audit log** — local Postgres (named volume `mt-genie-postgres-data`). Stand-in for Lakebase.
- **`sp_tenant_mapping` (the row-filter join)** — UC Delta in your workspace.
- **Bookings / customers (the demo data)** — UC Delta in your workspace.

## Resetting

```bash
docker compose down -v   # nukes the local Postgres data volume
./bootstrap.sh --demo    # rebuild from scratch
```
```

- [ ] **Step 3: Commit**

```bash
git add bootstrap.sh docs/local-dev.md
chmod +x bootstrap.sh
git update-index --chmod=+x bootstrap.sh
git commit -m "Add bootstrap.sh and interim local-dev docs"
```

---

## Task 23: End-to-end smoke verification

Confirm the app boots, Lakebase migrations apply, and the existing API contract still works against a real workspace + the local Postgres. This is the final sanity check before the Phase 1 plan is "done".

**Files:** none (verification only)

- [ ] **Step 1: Bring up Postgres**

```bash
docker compose up -d
```

- [ ] **Step 2: Run unit tests**

```bash
pytest tests/ -v
```

Expected: all tests PASSED. Specifically: smoke (3), db (3), tenant repo (6), audit repo (3), credential repo (6) = 21 tests.

- [ ] **Step 3: Run the app and smoke-test the API**

```bash
export $(grep -v '^#' .env.local | xargs)
uvicorn server.app:app --port 8001 &
sleep 3

curl -sf http://127.0.0.1:8001/health
echo
curl -sf http://127.0.0.1:8001/api/workspace/info | python -m json.tool

kill %1
```

Expected: `{"status":"healthy"}`; the workspace info JSON has the catalog/schema/genie_space_id you configured.

- [ ] **Step 4: Verify Lakebase tables exist**

```bash
docker compose exec -T postgres psql -U postgres -d mtg -c "\dt"
```

Expected: tables `client_registry`, `sp_credentials`, `audit_log`, `token_cache`, `schema_migrations`.

- [ ] **Step 5: Confirm no BCD/Advito strings anywhere in the working tree**

```bash
grep -rni "bcd\|advito" --include="*.py" --include="*.tsx" --include="*.ts" --include="*.sql" --include="*.md" --include="*.yml" --include="*.yaml" --include="*.sh" . && echo "FOUND — fix before merging" || echo "clean"
```

Expected: `clean`.

- [ ] **Step 6: Confirm the file structure matches the spec**

```bash
ls -d server/ scripts/ sql/ sql/lakebase/ domain/ domain/travel/ tests/
test ! -d api && echo "api removed: ok" || echo "api STILL EXISTS"
test ! -d src && echo "src removed: ok" || echo "src STILL EXISTS"
```

Expected: every directory listed; "api removed: ok" and "src removed: ok".

- [ ] **Step 7: Close out**

```bash
git status   # should be clean
git log --oneline -25
```

Expected: a clean working tree and 22 new commits on top of `782b3b8`.

- [ ] **Step 8: Final commit if anything was left over**

If verification surfaced anything, fix and commit:

```bash
git add -A
git commit -m "Phase 1 verification fixes"
```

---

## Phase 1 done

When all 23 tasks are checked, the repo:
- Has zero BCD/Advito strings.
- Lives at `server/`, `scripts/`, `sql/`, `domain/`, `tests/` — no `api/` or `src/`.
- Boots against a local Postgres (Lakebase stand-in) with `bootstrap.sh`.
- Applies Lakebase migrations idempotently on startup.
- Stores tenant metadata in `client_registry`, audit in `audit_log`, encrypted credentials in `sp_credentials`.
- Keeps `sp_tenant_mapping` in UC Delta because the row filter joins it.
- Has 21 unit tests covering db, tenant_repo, audit_repo, credential_repo.
- Same end-user features as today: list, ask, sweep, onboard, rotate, deactivate, audit. UI still on the old `ClientPage.tsx`/`AdminPage.tsx`/`ArchitecturePage.tsx` — Phase 3 rebuilds them.

Phase 2 is the next plan: new endpoints (bulk, lifecycle, verify, history) + the inspector payload.
