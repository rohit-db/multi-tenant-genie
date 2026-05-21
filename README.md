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

## Deploy (Databricks Asset Bundle)

The repo ships as a Databricks Asset Bundle. The minimal flow:

```bash
databricks bundle deploy --target dev
```

That wraps the Databricks App defined in `app.yaml`. The Lakebase + warehouse + Genie space + secret-scope bindings still need to be wired — `scripts/deploy.sh` does that end-to-end, including the UC grants and the AES key setup, and is the recommended fallback until the bundle covers those resources declaratively.

See [docs/deploy.md](docs/deploy.md) for the full walkthrough.

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
├── databricks.yml               # Asset Bundle root
├── resources/                   # bundle resources (app, etc.)
├── app.yaml                     # Databricks Apps manifest (used by the bundle)
├── docker-compose.yml           # local Postgres for dev
├── bootstrap.sh                 # one-shot local-dev setup
├── docs/
│   ├── architecture.md          # full system design
│   ├── pattern.md               # how the isolation pattern works
│   ├── deploy.md                # bundle + Databricks Apps deploy guide
│   ├── local-dev.md             # local dev guide
│   ├── customizing.md           # swap the demo domain, change schema
│   ├── scaling.md               # workspace caps, Genie 10k cap, Lakebase
│   ├── security-rbac.md         # AES-at-rest, admin bypass, audit
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
- **Different Genie space per tenant?** The `client_registry.genie_space_id` column already exists — surface it in the UI when you need it.
- **Pattern B (custom claims)?** A future direction; not implemented in this reference.

## Status

Reference solution shipping today on a Databricks workspace via Databricks Apps. 48 unit/integration tests; isolation enforced by UC row filters; AES-GCM at rest for SP credentials; in-process bulk onboard runner with a documented swap-path to a Databricks Job for production scale.

What's intentionally not in this reference (each is a future direction): per-tenant rate limits, cost/token tracking per tenant, multi-Genie-space UI, and Pattern B (shared SP + custom claims).
