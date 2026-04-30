# Phase 4 — Deploy + Docs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the repo deployable as a Databricks App and rewrite the documentation set so a fresh visitor can clone, deploy, and adapt the reference solution without prior context.

**Architecture:** Two work streams.
1. **Deploy** — author `app.yaml` (Databricks Apps manifest with Lakebase resource, warehouse permission, Genie space permission, AES key secret), document the deploy steps in `docs/deploy.md`, verify env-var wiring works locally.
2. **Docs** — rewrite the existing markdown set per the design spec: full README, new deploy/customizing/future-directions/migration docs, edits to scaling/security/code-snippets, retire the old implementation guide and the `pattern-a-sp-per-client.md` (rename to `pattern.md` per spec).

**Tech Stack:** Databricks Apps (`app.yaml` schema), Markdown. No code changes — Phase 1–3 already shipped the implementation. The only Python touch is making `server/lib/config.py` cleanly read every env var the deploy will set (BCD-specific defaults removed).

**Working tree assumed at start:** branch `generalize-and-scale` at the head of Phase 3 + landing-page polish (`471d301` or later). Backend tests 48 PASSED against real Postgres. Web build clean.

---

## Task 1: Reset `server/lib/config.py` defaults

`server/lib/config.py` still hard-codes the FEVM workspace as defaults (`profile`, `host`, `catalog`, `genie_space_id`, `warehouse_name`). For a reference repo, defaults should be empty and require explicit env vars in production. Local dev keeps FEVM-friendly defaults available behind a single `MT_GENIE_LOCAL_DEFAULTS=1` toggle.

**Files:**
- Modify: `server/lib/config.py`

- [ ] **Step 1: Replace `server/lib/config.py` contents**

```python
"""Shared configuration for the multi-tenant Genie reference.

In production (Databricks Apps), every value below comes from env vars
that the app.yaml resource block injects. In local dev, point ``MT_GENIE_*``
at your workspace via ``.env.local`` (bootstrap.sh writes one for you).
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    profile: str
    host: str
    catalog: str
    schema: str
    secret_scope: str
    genie_space_id: str
    warehouse_name: str
    sp_display_prefix: str
    admin_group: str

    @property
    def fq_tenants(self) -> str:
        return f"{self.catalog}.{self.schema}.tenants"

    @property
    def fq_mapping(self) -> str:
        return f"{self.catalog}.{self.schema}.sp_tenant_mapping"

    @property
    def fq_bookings(self) -> str:
        return f"{self.catalog}.{self.schema}.bookings"

    @property
    def fq_customers(self) -> str:
        return f"{self.catalog}.{self.schema}.customers"

    @property
    def fq_audit(self) -> str:
        return f"{self.catalog}.{self.schema}.audit_log"

    @property
    def fq_row_filter(self) -> str:
        return f"{self.catalog}.{self.schema}.tenant_row_filter"


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


CONFIG = Config(
    profile=_env("MT_GENIE_PROFILE"),
    host=_env("MT_GENIE_HOST"),
    catalog=_env("MT_GENIE_CATALOG"),
    schema=_env("MT_GENIE_SCHEMA", "mt_genie"),
    secret_scope=_env("MT_GENIE_SECRET_SCOPE", "mt-genie"),
    genie_space_id=_env("MT_GENIE_SPACE_ID"),
    warehouse_name=_env("MT_GENIE_WAREHOUSE_NAME", "Serverless Starter Warehouse"),
    sp_display_prefix=_env("MT_GENIE_SP_PREFIX", "mt-genie"),
    admin_group=_env("MT_GENIE_ADMIN_GROUP", "admins"),
)
```

- [ ] **Step 2: Verify smoke test still passes (no DB needed)**

```bash
pytest tests/test_smoke.py -v
```

Expected: 3 PASSED.

- [ ] **Step 3: Verify the full suite still passes against Postgres**

```bash
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/mtg \
  MT_GENIE_HOST=https://example.cloud.databricks.com \
  MT_GENIE_CATALOG=test_catalog \
  MT_GENIE_SPACE_ID=00000000000000000000000000000000 \
  pytest tests/ 2>&1 | tail -3
```

Expected: 48 PASSED. (The non-Postgres tests don't care about workspace settings; the Postgres ones need DATABASE_URL set; SPManager-touching tests use mocks so workspace creds aren't dialed.)

- [ ] **Step 4: Commit**

```bash
git add server/lib/config.py
git commit -m "Make config.py defaults env-only (no hardcoded workspace)"
```

---

## Task 2: Create `app.yaml` for Databricks Apps deploy

The Databricks Apps deployment manifest. Declares resources (Lakebase, warehouse permission, Genie space permission), env vars from those resources + secrets, and the run command.

**Files:**
- Create: `app.yaml`

- [ ] **Step 1: Create `app.yaml`**

```yaml
# Databricks App manifest for multi-tenant-genie.
#
# Deploy via:
#   databricks apps create multi-tenant-genie
#   databricks apps deploy multi-tenant-genie --source-code-path /path/to/repo
#
# See docs/deploy.md for the full deploy walkthrough.

name: multi-tenant-genie
description: |
  A reference solution for delivering Databricks Genie to thousands of
  isolated tenants. One Service Principal per tenant; UC row filters
  enforce data isolation; Lakebase holds operational metadata.

# Resources Databricks Apps provisions for the app at deploy time.
# Each one becomes an env var the runtime sees.
resources:
  - name: lakebase
    description: Postgres-backed metadata store (client_registry, sp_credentials, audit_log).
    database:
      instance_name: multi-tenant-genie-db
      database_name: mtg
      permission: CAN_USE

  - name: warehouse
    description: SQL warehouse Genie + the proxy use for UC reads/writes.
    sql_warehouse:
      id: ${var.warehouse_id}
      permission: CAN_USE

  - name: genie_space
    description: The Genie Space tenants ask questions against.
    genie_space:
      id: ${var.genie_space_id}
      permission: CAN_RUN

  - name: aes_key
    description: AES-GCM key for encrypting SP credentials at rest.
    secret:
      scope: ${var.secret_scope}
      key: aes_key_base64
      permission: READ

# Env vars exposed to the runtime. The Apps platform injects values
# from the resources above, plus any literal values you set here.
env:
  - name: DATABASE_URL
    valueFrom: lakebase
  - name: WAREHOUSE_ID
    valueFrom: warehouse
  - name: GENIE_SPACE_ID
    valueFrom: genie_space
  - name: AES_KEY_BASE64
    valueFrom: aes_key
  # Workspace-scoped values — set via the Apps deploy command's --variable
  # flags or the workspace's app config UI.
  - name: MT_GENIE_HOST
    value: ${var.host}
  - name: MT_GENIE_CATALOG
    value: ${var.catalog}
  - name: MT_GENIE_SCHEMA
    value: ${var.schema}
  - name: MT_GENIE_SPACE_ID
    value: ${var.genie_space_id}
  - name: MT_GENIE_ADMIN_GROUP
    value: ${var.admin_group}
  - name: DOMAIN
    value: ${var.domain}

# How the platform runs the app. The proxy serves the FastAPI backend
# on port 8000; Apps fronts it on its own URL.
command:
  - "uvicorn"
  - "server.app:app"
  - "--host"
  - "0.0.0.0"
  - "--port"
  - "8000"
```

- [ ] **Step 2: Verify YAML parses cleanly**

```bash
python -c "import yaml; yaml.safe_load(open('app.yaml').read()); print('ok')"
```

Expected: `ok`.

- [ ] **Step 3: Commit**

```bash
git add app.yaml
git commit -m "Add app.yaml for Databricks Apps deploy"
```

---

## Task 3: Rewrite `README.md`

The current README still references `pattern-a-sp-per-client.md`, `pattern-b-custom-claims.md` (deleted), and a phase-4 status note. Rewrite as the front door of a polished reference repo.

**Files:**
- Modify: `README.md` (full replacement)

- [ ] **Step 1: Replace README.md contents**

```markdown
# Multi-Tenant Genie

A reference solution for delivering Databricks Genie to thousands of isolated tenants — one Service Principal per tenant, UC row filters for hard data isolation, no Databricks accounts for end users.

## What it is

A FastAPI proxy + React UI that lets a single platform deliver Databricks Genie to many external tenants while guaranteeing each tenant only ever sees its own rows. The isolation is enforced by Unity Catalog row filters joined against `sp_tenant_mapping` on `session_user()` — not by prompts, not by application logic.

The repo is opinionated: Pattern A (SP-per-tenant), Lakebase for OLTP metadata, UC Delta for governed data, an in-process bulk onboard runner, and a request-flow inspector that makes the six-step request path visible to anyone watching the demo.

## Quickstart (local dev, 5 minutes)

```bash
git clone <this repo>
cd multi-tenant-genie
./bootstrap.sh --demo
```

`bootstrap.sh` prompts for your Databricks workspace + catalog + Genie space, writes `.env.local`, brings up a local Postgres (Docker), applies migrations, and (with `--demo`) seeds three demo tenants.

Then:

```bash
# Backend
uvicorn server.app:app --reload --port 8000

# Frontend (separate terminal)
cd web && npm install && npm run dev
```

Open [http://localhost:5173](http://localhost:5173).

See [docs/local-dev.md](docs/local-dev.md) for the full local-dev guide.

## Production deploy (Databricks Apps)

The canonical deploy is as a Databricks App. `app.yaml` declares the Lakebase + warehouse + Genie space + AES key resources; the platform injects env vars at runtime.

```bash
databricks apps create multi-tenant-genie
databricks apps deploy multi-tenant-genie --source-code-path .
```

See [docs/deploy.md](docs/deploy.md) for the full walkthrough including IAM grants and AES key setup.

## How the isolation works

Six steps run on every `/api/genie/ask` — visible in the UI's Request Flow Inspector:

1. **Authenticate** — proxy looks up the tenant in Lakebase's `client_registry`.
2. **Resolve tenant** — picks `genie_space_id` (per-tenant override or workspace global).
3. **Mint token** — OAuth M2M against `/oidc/v1/token` using the tenant's SP credentials (cache-aware).
4. **Apply row filter** *(the line between tenants)* — UC's `tenant_row_filter` runs in-warehouse, joining `sp_tenant_mapping` on `session_user()`.
5. **Ask Genie** — calls `/api/2.0/genie/spaces/{id}/start-conversation` as the tenant SP.
6. **Audit** — appends to Lakebase `audit_log`.

Step 4 is the load-bearing step. The full pattern is documented in [docs/pattern.md](docs/pattern.md).

## Project structure

```
multi-tenant-genie/
├── README.md                    # this file
├── app.yaml                     # Databricks Apps deploy manifest
├── docker-compose.yml           # local Postgres for dev
├── bootstrap.sh                 # one-shot local-dev setup
├── docs/
│   ├── architecture.md          # full system design
│   ├── pattern.md               # how the isolation pattern works
│   ├── deploy.md                # Databricks Apps deploy guide
│   ├── local-dev.md             # local dev guide
│   ├── customizing.md           # swap the demo domain, change schema
│   ├── scaling.md               # workspace caps, Genie 10k cap, Lakebase
│   ├── security-rbac.md         # AES-at-rest, admin bypass, audit
│   ├── future-directions.md     # Pattern B, rate limits, multi-space
│   └── migration-from-poc.md    # for anyone who cloned the original POC
├── server/                      # FastAPI proxy
│   ├── app.py
│   ├── routers/                 # tenants, genie, audit, jobs, verify, workspace
│   ├── lib/                     # config, db, sp_manager, repository/, inspector, verifier
│   └── jobs/                    # in-process bulk onboard runner
├── web/                         # React + Vite + Tailwind UI
│   └── src/
│       ├── pages/               # DemoPage, AdminPage, ArchitecturePage
│       └── components/          # Inspector, NumbersStrip, BulkOnboardDialog, ...
├── sql/                         # UC schema + Lakebase migrations
│   ├── setup.sql                # UC: schema, tenants, sp_tenant_mapping, row filter fn
│   └── lakebase/V*.sql          # Lakebase migrations applied on startup
├── domain/                      # swappable demo data
│   └── travel/                  # bookings, customers, sample questions
├── scripts/                     # CLI: seed_demo, bulk_onboard, verify_isolation
├── tests/                       # pytest unit + integration
└── diagrams/                    # Mermaid sources + rendered PNGs
```

## Adapting it

- **Different demo data?** Copy `domain/travel/` → `domain/<your-domain>/`, edit, set `DOMAIN=<your-domain>`. See [docs/customizing.md](docs/customizing.md).
- **Different Genie space per tenant?** The `client_registry.genie_space_id` column already exists — surface it in the UI when you need it. See [docs/future-directions.md](docs/future-directions.md).
- **Pattern B (custom claims)?** Documented as a future direction; not implemented. See [docs/future-directions.md](docs/future-directions.md).

## Status

Reference solution shipping today on a Databricks workspace via Databricks Apps. 48 unit/integration tests; isolation enforced by UC row filters; AES-GCM at rest for SP credentials; in-process bulk onboard runner with a documented swap-path to a Databricks Job for production scale.

What's intentionally not in this reference (each is a future direction): per-tenant rate limits, cost/token tracking per tenant, multi-Genie-space UI, and Pattern B (shared SP + custom claims).

## License

[Apache 2.0]
```

(The license line at the bottom is a placeholder if no LICENSE file exists. If one does, link to it.)

- [ ] **Step 2: Confirm no broken doc links**

```bash
grep -oE "docs/[a-z-]+\.md" README.md | sort -u | while read p; do test -f "$p" || echo "MISSING: $p"; done
```

Expected output: at this point, several lines like `MISSING: docs/deploy.md` — those files are created in later tasks. The check just confirms the list of expected files. After Phase 4 completes, this check should print nothing.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "Rewrite README — front-door for the reference solution"
```

---

## Task 4: Write `docs/deploy.md` (Databricks Apps deploy guide)

**Files:**
- Create: `docs/deploy.md`

- [ ] **Step 1: Create `docs/deploy.md`**

```markdown
# Deploying as a Databricks App

This is the canonical production deploy. The Apps platform handles the Lakebase, the warehouse permission, the Genie space permission, and the AES key — `app.yaml` declares them; the deploy command provisions and binds them.

## Prerequisites

- Databricks workspace with Apps enabled.
- Permission to create Lakebase databases (`CAN_USE` on the workspace's database catalog).
- A SQL warehouse you can grant `CAN_USE` on — Genie + the proxy use it.
- A Genie Space the app will run questions against. The app's own SP needs `CAN_RUN` on it.
- Your local Databricks CLI authenticated against the target workspace (`databricks auth login`).

## Step 1 — Create the AES key secret

The proxy encrypts each tenant's OAuth secret at rest with AES-GCM. The 32-byte key lives in a Databricks Secret. **In production deploys, the proxy refuses to start without it.**

```bash
# Generate a fresh 32-byte urlsafe-base64 key
python -c "import os, base64; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"

# Create the scope + write the key
databricks secrets create-scope multi-tenant-genie
databricks secrets put-secret multi-tenant-genie aes_key_base64
# (the CLI prompts for the value — paste the urlsafe-b64 string from above)
```

## Step 2 — Grant the app's SP `CAN_MANAGE_SERVICE_PRINCIPALS`

The app onboards tenants by creating Service Principals via the workspace SCIM API. The Databricks-Apps-issued SP needs workspace-level permission for that.

After deploying once (Step 4) the App's SP exists. Grant it:

```bash
# Workspace admin role grants the equivalent permission. This is the
# simplest path for a reference deploy. For production, scope the
# permission to just CAN_MANAGE_SERVICE_PRINCIPALS via the workspace
# admin console.
APP_SP_ID=$(databricks apps get multi-tenant-genie --output json | jq -r '.app_status.service_principal_client_id')
databricks workspace-conf set-status \
  "{\"users\": {\"workspace_users.add\": [\"${APP_SP_ID}\"]}}"
```

(The exact API for SP role grants varies by workspace setup. The simplest pre-production approach: add the App SP to the `admins` group via the account console.)

## Step 3 — Set the deploy variables

`app.yaml` references variables (`${var.host}`, `${var.catalog}`, etc.) that the deploy command resolves.

Create `app-vars.yaml`:

```yaml
host: https://your-workspace.cloud.databricks.com
catalog: your_catalog
schema: mt_genie
warehouse_id: 0123abc456def789
genie_space_id: 0123456789abcdef0123456789abcdef
admin_group: admins
secret_scope: multi-tenant-genie
domain: travel
```

## Step 4 — Create + deploy

```bash
databricks apps create multi-tenant-genie

databricks apps deploy multi-tenant-genie \
  --source-code-path . \
  --vars app-vars.yaml
```

The first deploy provisions the Lakebase instance — that takes a few minutes. Subsequent deploys reuse it.

## Step 5 — Verify the app is healthy

```bash
APP_URL=$(databricks apps get multi-tenant-genie --output json | jq -r '.url')
curl -sf "${APP_URL}/health"
```

Expected: `{"status":"healthy"}`.

Then open `${APP_URL}` in a browser. The Demo / Admin / Architecture tabs should render. Onboard a tenant from the Admin tab — that exercises the SCIM API, Lakebase, and UC mapping in one click.

## Troubleshooting

**App fails to start with `AES_KEY_BASE64 unset`:** the secret didn't bind. Re-check Step 1, confirm the secret scope name matches the `secret_scope` variable in `app-vars.yaml`.

**Onboard fails with 403 / "permission denied":** the App SP doesn't have `CAN_MANAGE_SERVICE_PRINCIPALS`. Re-check Step 2.

**Lakebase migrations fail on first deploy:** check the app logs (`databricks apps logs multi-tenant-genie`). Usually a missing `CAN_USE` on the database catalog. The Lakebase resource declaration in `app.yaml` requests it; sometimes the workspace admin needs to approve the request.

**Genie returns 404 for tenant queries:** the Genie space exists but the App SP doesn't have `CAN_RUN`. Grant via the Genie Space → Permissions UI, or wait for the deploy's `genie_space` resource binding to apply.

## Migrating from local dev to Apps

The data model is identical. To move local-dev state to a deployed app:

1. `pg_dump` your local Postgres `client_registry` + `sp_credentials` + `audit_log`.
2. `databricks apps logs --follow` until the app boots.
3. `pg_restore` into the Apps Lakebase database.

For most reference users this is unnecessary — re-onboard the demo tenants in the deployed app via the Admin tab.
```

- [ ] **Step 2: Commit**

```bash
git add docs/deploy.md
git commit -m "Add docs/deploy.md — Databricks Apps deploy walkthrough"
```

---

## Task 5: Rewrite `docs/local-dev.md`

The interim version lives at `docs/local-dev.md` (Phase 1 Task 22). Replace with a full guide.

**Files:**
- Modify: `docs/local-dev.md` (full replacement)

- [ ] **Step 1: Replace `docs/local-dev.md` contents**

```markdown
# Local Development

This is the secondary deploy path — the canonical deploy is as a Databricks App ([docs/deploy.md](deploy.md)). Local dev is what you use to iterate on the proxy or UI without a deploy roundtrip.

## Prerequisites

- Python 3.11 or newer
- Docker (for the local Postgres that stands in for Lakebase)
- Node 18+ and npm (for the React UI)
- A Databricks workspace profile in `~/.databrickscfg` with permission to create Service Principals + read your target catalog
- A target Genie Space with the SPs you'll create granted `CAN_RUN`

## One-shot setup

```bash
./bootstrap.sh           # interactive — writes .env.local, brings up Postgres, applies migrations
./bootstrap.sh --demo    # the above + seeds three demo tenants in your workspace
```

The script prompts for:
- Databricks workspace host (e.g. `https://abc.cloud.databricks.com`)
- Databricks profile name from `~/.databrickscfg`
- UC catalog
- UC schema (default `mt_genie`)
- Genie space ID

It writes `.env.local` and exits.

## Running the app

Two terminals:

```bash
# Terminal 1 — backend
uvicorn server.app:app --reload --port 8000

# Terminal 2 — frontend (Vite dev server, proxies /api → :8000)
cd web && npm install && npm run dev
```

Open [http://localhost:5173](http://localhost:5173).

## What lives where

| Data | Store |
|---|---|
| `client_registry`, `sp_credentials`, `audit_log` | Local Postgres (Docker volume `mt-genie-postgres-data`) — stand-in for Lakebase. |
| `sp_tenant_mapping` | UC Delta in your workspace — the row filter joins this. |
| `bookings`, `customers` (demo data) | UC Delta in your workspace. |
| Active domain pack | `domain/<name>/` — selects via `DOMAIN` env var. |

## AES key in local dev

By default `AES_KEY_BASE64` is **unset** locally and SP credentials are stored with a `plain:` prefix. The proxy logs a warning. This is acceptable for throwaway demo data; for anything closer to production, set the key:

```bash
export AES_KEY_BASE64=$(python -c "import os, base64; print(base64.urlsafe_b64encode(os.urandom(32)).decode())")
echo "AES_KEY_BASE64=$AES_KEY_BASE64" >> .env.local
```

## Running the tests

```bash
pytest tests/                                  # full suite (requires Postgres up)
pytest tests/test_smoke.py                     # fast sanity check, no Postgres
pytest tests/ -k "not test_repository"         # skip the Lakebase-backed tests
```

48 tests total. The 18 Lakebase-backed tests skip cleanly if Postgres isn't reachable.

## Resetting

```bash
docker compose down -v       # nukes the Lakebase data volume
./bootstrap.sh --demo        # rebuild from scratch
```

## Common issues

**`DATABASE_URL is not set`** when running uvicorn: source `.env.local` first (`set -a; source .env.local; set +a`).

**Ports 5173 / 8000 in use**: `lsof -ti:5173 | xargs kill` (or :8000).

**`SP {sp_app_id} not found`** when asking a question: the workspace deleted the SP behind the proxy's back. Deactivate then re-onboard the tenant from the Admin tab.

**Genie returns "no permission"**: the SP needs `CAN_RUN` on the Genie space. The proxy attempts `grant_genie_access` on every onboard, but if your account-level role doesn't allow that PATCH, you'll need a workspace admin to grant manually.
```

- [ ] **Step 2: Commit**

```bash
git add docs/local-dev.md
git commit -m "Rewrite docs/local-dev.md — full local-dev guide"
```

---

## Task 6: Write `docs/customizing.md`

How to swap the domain, point at your data, change row-filter columns.

**Files:**
- Create: `docs/customizing.md`

- [ ] **Step 1: Create `docs/customizing.md`**

```markdown
# Customizing the Reference

The repo is opinionated about *the pattern* (SP-per-tenant + UC row filters + Lakebase metadata) but flexible about *the data*. Here's how to swap each layer.

## Swap the demo domain

The demo ships travel data — bookings, customers, routes. The schema lives in `domain/travel/schema.sql`; the seed logic in `domain/travel/seed.py`; the sample questions in `domain/travel/sample_questions.json`. Nothing in `server/` or `web/` mentions "bookings" or "travel" by name.

To swap to your own domain:

1. **Copy the directory:**
   ```bash
   cp -r domain/travel domain/retail
   ```

2. **Edit `domain/retail/schema.sql`** — declare your tables with `tenant_id` as the row-filter column:
   ```sql
   CREATE TABLE IF NOT EXISTS ${catalog}.${schema}.orders (
       order_id STRING NOT NULL,
       tenant_id STRING NOT NULL,           -- row-filter column
       sku STRING,
       amount_usd DOUBLE,
       placed_at TIMESTAMP
   ) USING DELTA;

   ALTER TABLE ${catalog}.${schema}.orders
     SET ROW FILTER ${catalog}.${schema}.tenant_row_filter ON (tenant_id);
   ```

3. **Edit `domain/retail/seed.py`** — generate per-tenant data. The function signature is `seed(mgr, tenants: Iterable[dict])` where `mgr` is an `SPManager` instance. Use `mgr._execute_sql(...)` to write to UC.

4. **Edit `domain/retail/sample_questions.json`** — questions that fit your schema:
   ```json
   {
     "row_filter_column": "tenant_id",
     "questions": [
       "How many orders did I place last quarter?",
       "Top 10 SKUs by revenue",
       "Average order value by month"
     ]
   }
   ```

5. **Activate the new domain:**
   ```bash
   echo "DOMAIN=retail" >> .env.local
   ```

6. **Re-seed:**
   ```bash
   python scripts/seed_demo.py
   ```

## Change the row-filter column

The default is `tenant_id`. If your schema uses `customer_id`, `org_id`, or anything else, three places change:

1. **`sql/setup.sql`** — the `tenant_row_filter` function definition. Update the column name.
2. **Your domain's `schema.sql`** — the `ALTER TABLE … SET ROW FILTER … ON (column)` clause.
3. **`domain/<name>/sample_questions.json`** — set `"row_filter_column"` so the UI labels stay accurate.

The proxy code itself doesn't reference the column name; UC enforces it via the row-filter SQL alone.

## Point at your existing UC data

If you already have tenant-scoped tables in UC and just want to add the multi-tenant-genie proxy in front:

1. Make sure each governed table has a `tenant_id` (or your equivalent) column on every row.
2. Run `sql/setup.sql` against your workspace — this creates `sp_tenant_mapping` + the `tenant_row_filter` function in your chosen catalog/schema.
3. Apply the row filter to your existing tables:
   ```sql
   ALTER TABLE your_catalog.your_schema.your_table
     SET ROW FILTER your_catalog.your_schema.tenant_row_filter ON (tenant_id);
   ```
4. Skip the `domain/travel/schema.sql` runner — your tables already exist. Either (a) delete the apply-domain-schema step in `scripts/seed_demo.py` or (b) make a thin `domain/<your-name>/schema.sql` that's empty / no-op.

## Change the metadata schema

`client_registry` (Lakebase) carries `tier`, `rate_limit_per_min`, and a `metadata` JSONB column. The JSONB is intentional — extend without migrations:

```python
# When onboarding
tenant_repo.insert(
    tenant_id="acme",
    display_name="Acme",
    sp_app_id=...,
    sp_display_name=...,
    metadata={"tier": "enterprise", "region": "us-east", "contact": "ops@acme.com"},
)
```

If you need columns instead of JSONB, add a new versioned migration to `sql/lakebase/V002__add_columns.sql` and the migration runner picks it up on next startup.

## Change the demo tenants

`scripts/seed_demo.py` has `DEMO_TENANTS` at the top. Edit the list — each entry is `{tenant_id, tenant_name, industry, hq, travelers}`. The travel-specific keys (`industry`, `hq`, `travelers`) are passed to `domain/travel/seed.py` as kwargs; if your domain ignores them, that's fine.

## Change the Genie space

Single-space (default): set `MT_GENIE_SPACE_ID` and that's the global default for every tenant.

Per-tenant override: the `client_registry.genie_space_id` column accepts a UUID; when set, the proxy uses it for that tenant's queries. The UI doesn't expose this yet — see [docs/future-directions.md](future-directions.md).

## Change the UI branding

`web/src/App.tsx` controls the header title, logomark, and tabs. The Inspector's amber accent on step 4 is in `web/src/components/Inspector.tsx`. Tailwind palette is the standard `slate` / `indigo` / `emerald` / `rose` / `amber` from `tailwind.config.js`.
```

- [ ] **Step 2: Commit**

```bash
git add docs/customizing.md
git commit -m "Add docs/customizing.md — domain swap + row filter + branding"
```

---

## Task 7: Write `docs/future-directions.md`

Pattern B + N5/N6/N7 callouts (rate limits, multi-Genie-space UI, cost tracking). What's intentionally not built and why.

**Files:**
- Create: `docs/future-directions.md`

- [ ] **Step 1: Create `docs/future-directions.md`**

```markdown
# Future Directions

What this reference does not include — and where to add it later.

Each section names the gap, the mechanism, and the localized place to add the implementation. Nothing here is planned for the reference itself; these are starting points if your deployment grows past what's in scope.

## Pattern B — Shared SP + custom claims

**The idea:** instead of one Service Principal per tenant, run *one* SP and pass the tenant's identity as a custom claim on the OAuth token. UC's `current_oauth_custom_identity_claims()` reads the claim inside the row filter. Result: O(1) SP management instead of O(N).

**Why not in the reference:** at the time of writing, Genie's Conversation API surfaces don't reliably honor custom identity claims. Pattern A works today on GA primitives; Pattern B is a future swap when the Genie surfaces validate.

**Where it lands when ready:**
- Replace `tenant_row_filter` SQL: read `current_oauth_custom_identity_claims()` instead of joining `sp_tenant_mapping` on `session_user()`.
- Replace `server/lib/sp_manager.py:onboard_tenant`: skip the SP creation; insert into `client_registry` only.
- Replace `server/lib/genie_client.py:ask`: mint the token with a custom claim per request instead of using the tenant's per-SP credentials.

This is a 1-day swap when Genie's surfaces support it. The data model already has space for the registry-only path.

## Per-tenant rate limits / quotas

**The idea:** budget each tenant's requests per minute / per hour. Reject (or queue) overshoot.

**Where it lands:**
- Add a token bucket in `server/lib/rate_limiter.py` keyed on `tenant_id`. In-memory works for single-instance Apps deploys; Lakebase-backed counters work for multi-instance.
- Read the tenant's budget from `client_registry.rate_limit_per_min` (column already exists).
- Wrap `_ask_sync` in `server/routers/genie.py` with the limiter check.
- Surface the budget + current usage in the Admin tab — extend `NumbersStrip` or add a per-tenant column.

The hard part is not the limiter; it's deciding what to do on overshoot (429 vs queue vs degrade to cached answer).

## Multi-Genie-space UI

**The idea:** different tenants ask against different Genie Spaces (e.g., per-vertical tuning, per-region content).

**Where it lands:**
- The data model is already there: `client_registry.genie_space_id` is a nullable column. Null → use the workspace global; set → use the override.
- Surface in the UI: in `web/src/components/AdminPage.tsx`, add a per-tenant Genie space picker to the row actions or onboard dialog.
- Update `server/routers/genie.py:_ask_sync` to read the override (it currently uses `CONFIG.genie_space_id` unconditionally).

The platform reason this is interesting: each Genie Space caps at 10,000 conversations. Splitting tenants across spaces is the documented scaling story.

## Cost / token tracking per tenant

**The idea:** show what each tenant costs in Genie API tokens. Bill or alert.

**Where it lands:**
- Genie's Conversation API doesn't currently surface per-call token cost in its response shape. Watch the API release notes for this.
- When it lands: extend `audit_log` with `tokens_in INTEGER, tokens_out INTEGER`, populate from the response, surface in `NumbersStrip` and the per-tenant history drawer.

This is gated entirely on the upstream API. Don't build the UI until the backend has data to fill it.

## Reverse-ETL of `audit_log` to UC

**The idea:** keep `audit_log` hot in Lakebase but mirror it to UC for analytics tooling.

**Where it lands:**
- Lakebase Synced Tables — define a sync from `mtg.audit_log` (Postgres) to `<catalog>.<schema>.audit_log_uc` (Delta).
- Set up the sync once via the Lakebase UI or CLI. The proxy doesn't need to know.

This is operational, not code-resident.

## Background-job runner for bulk onboard

**The idea:** the in-process job runner (`server/jobs/bulk_onboard.py`) is fine for hundreds of tenants in a single shot. For tens of thousands, swap to a Databricks Job that the API kicks off and polls.

**Where it lands:**
- `server/jobs/bulk_onboard.py:JobRunner.submit` already returns a `job_id` — replace its body to call `databricks.sdk.WorkspaceClient.jobs.run_now(...)` and return the run_id.
- `server/routers/jobs.py:get_job` reads job state from Databricks instead of the in-process dict.
- The Job task itself runs `scripts/bulk_onboard.py --input <list>` against the tenant list passed via job parameters.

The interface is small — the swap is contained to two files.

## E2E browser tests

**The idea:** Playwright specs in CI.

**Why not now:** browser tests are high-leverage for product apps; for a reference repo, the maintenance cost typically outweighs the value. The proxy contract is unit-tested (30 tests run without infra), and the Architecture tab's live mapping table + verify endpoint are the credibility moments — not the Demo tab buttons.

If you fork for production: Playwright is already a dev dependency in `web/package.json`. Add specs to `web/tests/` and wire them into CI.
```

- [ ] **Step 2: Commit**

```bash
git add docs/future-directions.md
git commit -m "Add docs/future-directions.md — Pattern B, rate limits, multi-space, cost"
```

---

## Task 8: Write `docs/migration-from-poc.md`

For anyone who cloned the original BCD POC version of this repo before the rewrite.

**Files:**
- Create: `docs/migration-from-poc.md`

- [ ] **Step 1: Create `docs/migration-from-poc.md`**

```markdown
# Migrating from the POC

The original repo was a working POC for one specific account (BCD Travel / Advito). This page is for anyone who cloned that version and wants to move to the generalized reference.

## What changed

| Layer | Before | After |
|---|---|---|
| Top-level layout | `api/`, `src/lib/`, `src/scripts/`, `src/sql/` | `server/`, `scripts/`, `sql/`, `domain/` |
| Metadata store | UC `tenants` table + `.demo-secrets.env` flat file | Lakebase: `client_registry`, `sp_credentials` (AES-GCM), `audit_log` |
| `sp_tenant_mapping` | UC Delta (unchanged) | UC Delta (unchanged — required by row filter) |
| Domain data | Hardcoded in `seed_demo.py` | `domain/<name>/` swappable layer |
| API surface | `/tenants/audit`, `/tenants/mapping` | `/audit`, `/audit/mapping`; new `/tenants/bulk`, `/tenants/{id}/{reactivate,history}`, `DELETE /tenants/{id}`, `/verify` |
| `/genie/ask` | Returns answer only | Optionally returns a six-step `inspector` block when `?inspect=true` |
| UI | Single page (Client View) | Three tabs (Demo / Admin / Architecture), Inspector hero feature |
| Branding | BCD/Advito copy throughout | Generic "tenant" copy |

## Migration path

For most users: start fresh.

```bash
git stash       # if you have local changes
git pull        # or re-clone
./bootstrap.sh --demo
```

The data model is incompatible with the old version (different tables, different store), so an in-place migration would be more work than re-onboarding from scratch. The demo tenants take ~30 seconds to onboard.

## If you have production tenants on the old version

The two stores you care about are the UC `tenants` table (old) and the new Lakebase `client_registry`. The data shape is different but the SP IDs are stable.

```sql
-- 1. Dump the old UC tenants table to a CSV
SELECT tenant_id, tenant_name, sp_app_id, sp_display_name, status,
       created_at, updated_at
FROM your_catalog.your_schema.tenants;
```

Then write a one-shot script to insert into Lakebase `client_registry`:

```python
import csv, psycopg
from server.lib import db

with psycopg.connect(db.database_url()) as conn:
    with open("old-tenants.csv") as f:
        reader = csv.DictReader(f)
        for row in reader:
            conn.execute(
                "INSERT INTO client_registry "
                "(tenant_id, display_name, sp_app_id, sp_display_name, status) "
                "VALUES (%s, %s, %s, %s, %s) "
                "ON CONFLICT DO NOTHING",
                (row["tenant_id"], row["tenant_name"], row["sp_app_id"],
                 row["sp_display_name"], row["status"]),
            )
        conn.commit()
```

For SP credentials — the old version stored secrets in the Databricks secret scope under each SP's app ID. The new version stores them in `sp_credentials` (Lakebase, encrypted with AES-GCM). Easiest path: rotate every tenant via the Admin tab after migration, which mints fresh secrets and stores them correctly.

## What you can delete

After migrating, the legacy UC `tenants` table is no longer used. The `audit_log` UC table is no longer written to (audit goes to Lakebase). You can drop both:

```sql
DROP TABLE IF EXISTS your_catalog.your_schema.tenants;
DROP TABLE IF EXISTS your_catalog.your_schema.audit_log;
```

Don't drop `sp_tenant_mapping` — the row filter still joins it.

## What stayed the same

- `sp_tenant_mapping` schema unchanged.
- `tenant_row_filter` function unchanged.
- The bookings/customers governed-data tables (now defined in `domain/travel/schema.sql`) — unchanged structure.
- OAuth M2M flow — unchanged.
- The Pattern A core idea (SP per tenant) — unchanged.

If you want a deeper technical-decision summary, see `docs/superpowers/specs/2026-04-28-generalize-and-scale-design.md`.
```

- [ ] **Step 2: Commit**

```bash
git add docs/migration-from-poc.md
git commit -m "Add docs/migration-from-poc.md — for users of the original POC"
```

---

## Task 9: Rename `pattern-a-sp-per-client.md` → `pattern.md`, edit it

The spec calls for `docs/pattern.md` as the canonical "how the isolation works" doc, with `poc-flow.md` content folded in. `poc-flow.md` was deleted in Phase 1; the existing `pattern-a-sp-per-client.md` already has the bones — rename + light edit.

**Files:**
- Rename: `docs/pattern-a-sp-per-client.md` → `docs/pattern.md`
- Edit: replace any "client organization" / BCD residue if any remains; update title

- [ ] **Step 1: Rename**

```bash
git mv docs/pattern-a-sp-per-client.md docs/pattern.md
```

- [ ] **Step 2: Edit the file**

Open `docs/pattern.md`. At minimum:

- Update the H1 title to `# The Pattern: SP per Tenant + UC Row Filters`.
- Replace any remaining "client organization" / "client SP" / "per-client" with "tenant" / "tenant SP" / "per-tenant".
- Replace any "BCD" / "Advito" / "FEVM" references.
- Drop any "Status: pending validation" / "TODO" / "future" sections that are now resolved.

Run a final grep:

```bash
grep -ni "client\|bcd\|advito" docs/pattern.md | head -20
```

Address every prose hit. Identifiers like `client_id`, `client_secret`, `client_credentials` are correct — leave them.

- [ ] **Step 3: Commit**

```bash
git add docs/pattern.md
git commit -m "Rename pattern-a-sp-per-client.md → pattern.md; tenant-generic copy"
```

---

## Task 10: Edit existing docs (scaling, security-rbac, code-snippets, architecture)

Pass over the four remaining docs:
- `docs/scaling.md` — drop POC framing, add Lakebase scaling notes, mention 10k Genie cap pointer
- `docs/security-rbac.md` — keep AES-at-rest + admin-bypass; drop POC paragraphs
- `docs/code-snippets.md` — drop POC specifics; verify path references match new layout
- `docs/architecture.md` — Lakebase-vs-UC split; cleaner diagram pointer

**Files:**
- Modify: `docs/scaling.md`
- Modify: `docs/security-rbac.md`
- Modify: `docs/code-snippets.md`
- Modify: `docs/architecture.md`

- [ ] **Step 1: For each file, run a sweep grep**

```bash
for f in docs/scaling.md docs/security-rbac.md docs/code-snippets.md docs/architecture.md; do
  echo "=== $f ==="
  grep -ni "client\|bcd\|advito\|fevm\|src/" "$f" | head -10
done
```

For each hit, decide:
- **prose hit ("client organization", "BCD")** → replace with the tenant-generic equivalent
- **path hit ("src/lib", "src/scripts", "api/")** → update to the new layout (`server/lib`, `scripts/`, `server/`)
- **identifier hit (`client_id`, `client_credentials`)** → leave alone

- [ ] **Step 2: Specific edit — `docs/scaling.md`**

Add a new section (or update existing) titled `## Scaling beyond a single Genie Space`:

```markdown
## Scaling beyond a single Genie Space

Each Genie Space currently caps at ~10,000 conversations. For deployments exceeding that:

- The data model accommodates per-tenant overrides via `client_registry.genie_space_id` (nullable; null → workspace global).
- Surface a Genie space picker in the Admin tab when you need it. See [docs/future-directions.md](future-directions.md#multi-genie-space-ui) for the localized change list.
- Operationally: split tenants across spaces by tier, region, or vertical. Each space gets its own tuning + content.

## Lakebase scaling

The metadata store (`client_registry`, `sp_credentials`, `audit_log`) is single-Postgres-instance. Lakebase auto-scales the underlying compute; for the reference workload (read on every request, write on every onboard / query), a base instance handles thousands of tenants.

Hot paths:
- Tenant lookup on `/api/genie/ask`: indexed `client_registry.tenant_id`.
- Audit append: append-only writes to `audit_log`, indexed on `(tenant_id, created_at DESC)`.

For multi-instance proxy deployments, the in-memory token cache (`TokenMinter`) becomes a per-replica cache — the `token_cache` Postgres table can be enabled to share token state across replicas. Schema is in place; the cache reader is not yet wired.
```

- [ ] **Step 3: Specific edit — `docs/security-rbac.md`**

If the file references `.demo-secrets.env` or "secret scope" patterns from the POC, replace with: "SP credentials are stored in Lakebase `sp_credentials`, AES-GCM encrypted at rest with a 32-byte key from `AES_KEY_BASE64`."

If the file mentions BCD's specific groups, replace with the generic `${admin_group}` env var reference.

If a section is titled "Pattern B" or "Custom claims", check it's still relevant; if not, delete or move the content to `docs/future-directions.md`.

- [ ] **Step 4: Specific edit — `docs/code-snippets.md`**

Path updates:
- `src/lib/` → `server/lib/`
- `src/scripts/` → `scripts/`
- `src/sql/setup.sql` → `sql/setup.sql`
- `src/sql/lakebase_schema.sql` → `sql/lakebase/V001__initial.sql`
- `api/` → `server/`

Drop any code snippet that's specific to the original POC (BCD-named SPs, FEVM workspace, etc.).

- [ ] **Step 5: Specific edit — `docs/architecture.md`**

If the file's diagram still shows the POC architecture (UC tenants table as the metadata store, `.demo-secrets.env` for credentials), update to:
- Lakebase as the metadata store (`client_registry`, `sp_credentials`, `audit_log`)
- UC Delta as the governed-data store (`bookings`, `customers`, `sp_tenant_mapping`)
- Mention the request-flow inspector as the demo-time artifact

If you don't want to redraw an ASCII or Mermaid diagram, point at the `web/src/pages/ArchitecturePage.tsx` rendered version instead:

> The live architecture diagram is rendered in the app's Architecture tab. The Mermaid source is in [web/src/pages/ArchitecturePage.tsx](../web/src/pages/ArchitecturePage.tsx) (search for `ARCH_DIAGRAM`).

- [ ] **Step 6: Final cross-doc grep**

```bash
grep -rni "bcd\|advito\|fevm" docs/ --include="*.md" | grep -v "docs/superpowers/"
```

Expected: empty.

```bash
grep -rn "src/lib\|src/scripts\|src/sql\|^api/" docs/ --include="*.md" | grep -v "docs/superpowers/" | grep -v migration-from-poc
```

Expected: empty (no stale path refs outside the migration doc, which intentionally references old paths).

- [ ] **Step 7: Commit**

```bash
git add docs/
git commit -m "Pass over scaling, security-rbac, code-snippets, architecture docs"
```

---

## Task 11: Delete `docs/implementation-guide.md`

The spec retires this file (split into `deploy.md` + `local-dev.md`).

**Files:**
- Delete: `docs/implementation-guide.md`

- [ ] **Step 1: Confirm nothing references it**

```bash
grep -rn "implementation-guide" --include="*.md" --include="*.py" --include="*.tsx" --include="*.ts" . | grep -v "docs/superpowers/"
```

Expected: empty (the README rewrite already dropped its link).

- [ ] **Step 2: Delete**

```bash
git rm docs/implementation-guide.md
```

- [ ] **Step 3: Commit**

```bash
git commit -m "Delete docs/implementation-guide.md (split into deploy.md + local-dev.md)"
```

---

## Task 12: End-to-end smoke + final verification

**Files:** none (verification only)

- [ ] **Step 1: Backend tests against Postgres**

```bash
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/mtg \
  MT_GENIE_HOST=https://example.cloud.databricks.com \
  MT_GENIE_CATALOG=test_catalog \
  MT_GENIE_SPACE_ID=00000000000000000000000000000000 \
  pytest tests/ 2>&1 | tail -3
```

Expected: 48 PASSED.

- [ ] **Step 2: TypeScript clean + production build**

```bash
cd web && npx tsc --noEmit 2>&1 | grep -v zoxide
cd web && npm run build 2>&1 | tail -5
```

Expected: zero errors; build completes.

- [ ] **Step 3: Confirm app.yaml parses**

```bash
python -c "import yaml; yaml.safe_load(open('app.yaml').read()); print('ok')"
```

Expected: `ok`.

- [ ] **Step 4: Confirm doc set is complete**

```bash
ls docs/*.md
```

Expected:
```
docs/architecture.md
docs/code-snippets.md
docs/customizing.md
docs/deploy.md
docs/future-directions.md
docs/local-dev.md
docs/migration-from-poc.md
docs/pattern.md
docs/references.md
docs/scaling.md
docs/security-rbac.md
```

11 markdown files. No `implementation-guide.md`, no `pattern-a-sp-per-client.md`.

- [ ] **Step 5: Confirm no stale customer/POC references**

```bash
grep -rni "bcd\|advito\|fevm" \
  --include="*.py" --include="*.tsx" --include="*.ts" --include="*.sql" \
  --include="*.md" --include="*.yml" --include="*.yaml" --include="*.sh" \
  --exclude-dir=node_modules --exclude-dir=.git \
  . 2>/dev/null \
  | grep -v "docs/superpowers/" \
  | grep -v "docs/migration-from-poc.md" \
  && echo "FOUND" || echo "clean"
```

Expected: `clean`.

- [ ] **Step 6: README links resolve**

```bash
grep -oE "docs/[a-z-]+\.md" README.md | sort -u | while read p; do test -f "$p" || echo "MISSING: $p"; done
```

Expected: empty (every referenced doc exists).

- [ ] **Step 7: Phase 4 summary paragraph**

Write a one-paragraph close-out covering:
- Deploy path: `app.yaml` written, `docs/deploy.md` walks through the Databricks Apps deploy.
- Documentation: README rewritten; six new/edited docs (`deploy.md`, `local-dev.md` rewrite, `customizing.md`, `future-directions.md`, `migration-from-poc.md`, `pattern.md` rename); four legacy docs edited (`scaling`, `security-rbac`, `code-snippets`, `architecture`); one deleted (`implementation-guide.md`).
- Test posture: 48 backend tests + TypeScript clean + production build green; `app.yaml` parses.
- What's NOT verified locally: an actual Databricks Apps deploy. Suggested smoke: `databricks apps create` + `databricks apps deploy` against your dev workspace.
- Suggested next step: record a 60-90 second demo video of the Demo tab inspector → Admin tab onboarding → Architecture tab Live mapping table. Embed in the README.

## Phase 4 done

When all 12 tasks are checked, the repo:
- Has an `app.yaml` that defines the Databricks Apps deploy.
- Has a complete documentation set: README + 11 markdown docs covering deploy, local-dev, customizing, future directions, migration, pattern, scaling, security, code snippets, architecture, references.
- Has zero stale customer/POC references outside the migration-from-poc.md narrative.
- Builds clean (TypeScript, Python tests, YAML parse).

The only remaining "polish" item is a recorded demo video — out of scope for the implementation plan; that's a one-shot screen-recording exercise.
