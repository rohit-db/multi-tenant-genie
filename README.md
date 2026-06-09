# Multi-Tenant Genie — *Databricks is all you need*

A reference **embedded-analytics product** built end to end on Databricks: a branded customer app (**SkyDesk Analytics**) with its own login, your-own-Genie chat, live AI/BI dashboards, and a back-office operator console — delivering Databricks Genie to thousands of isolated tenants with one Service Principal per tenant and UC row filters for hard data isolation.

The point of the demo: **you don't assemble a data stack — Databricks *is* the stack.** Storage + governance (Unity Catalog), per-tenant isolation (SP + OAuth M2M + row filters), embedded BI (AI/BI dashboards), natural-language analytics (Genie + Managed MCP), OLTP metadata + the app's own users (Lakebase), and hosting (Databricks Apps). The only thing you bring is the skin.

## What it is

A FastAPI + React app with two surfaces behind a thin app-level login:

- **The product** (`/`, `/ask`, `/dashboards`) — the customer-facing SkyDesk skin: a branded Home with your-own-Genie hero and glance KPIs, a Genie chat (REST **and** Managed MCP transports) with auto-charting, and curated tenant-scoped dashboards. Every query runs as the tenant's Service Principal, so Unity Catalog row filters scope the data — not prompts, not application logic.
- **The operator console** (`/console`) — back-office for operators only: Service Principal lifecycle (onboard / rotate / deactivate / bulk), audit log, isolation verification, and an architecture showcase.

The isolation is enforced by Unity Catalog row filters joined against `sp_tenant_mapping` on `session_user()`. The repo is opinionated: Pattern A (SP-per-tenant), Lakebase for OLTP metadata + app users, UC Delta for governed data, an in-process bulk onboard runner, and a request-flow inspector that makes the six-step request path visible.

## App surfaces & demo logins

A thin authentication layer (PBKDF2 passwords + signed session cookie, all stdlib) gates the app. Two demo accounts are seeded automatically on first boot:

| Email | Password | Role | Sees |
|---|---|---|---|
| `analyst@skydesk.app` | `skydesk` | user | The product (Home / Ask / Dashboards) |
| `operator@skydesk.app` | `skydesk` | operator | The product **+** `/console` |

This app login is intentionally separate from Databricks workspace identity — it models how a real embedded SaaS authenticates *its own* end users before the backend ever touches Databricks. Rebrand the whole skin from `web/src/brand/brand.ts` + the `--brand*` variables in `web/src/brand/theme.css`. Seed password override: `MT_GENIE_DEMO_PASSWORD`. Session signing key: `MT_GENIE_SESSION_SECRET` (falls back to a stable value derived from the bound `AES_KEY_BASE64`).

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

## Deploy

`scripts/deploy.sh` is the canonical, end-to-end deploy. It builds the
frontend, provisions/binds Lakebase + the AES secret, applies the UC grants,
fills `app.yaml` with your workspace values, and syncs + deploys the
Databricks App:

```bash
CATALOG=<your-catalog> GENIE_SPACE_ID=<space-id> WAREHOUSE_ID=<wh-id> \
  scripts/deploy.sh
```

> `app.yaml` ships with **blank** workspace-scoped values on purpose — nothing
> workspace-specific is committed. `deploy.sh` populates `MT_GENIE_HOST`,
> `MT_GENIE_CATALOG`, `MT_GENIE_SPACE_ID`, `MT_GENIE_DASHBOARD_ID`, etc. from
> your inputs before syncing. To deploy by hand, set those values yourself.

A `databricks.yml` Asset Bundle stub is included (`databricks bundle deploy
--target dev`) but it is minimal — it declares the app only and does **not**
provision Lakebase, the secret scope, or the UC grants, so `deploy.sh` remains
the recommended path until the bundle covers those resources declaratively.

See [docs/deploy.md](docs/deploy.md) for the full walkthrough, and
[docs/edge-gateway.md](docs/edge-gateway.md) for the optional external front
door (a Firefly-style reverse proxy in `edge/` that lets end users reach the
embedded app without Databricks SSO).

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
├── databricks.yml               # Asset Bundle stub (app declaration only)
├── resources/                   # bundle resources (app, etc.)
├── app.yaml                     # Databricks Apps manifest (values filled by deploy.sh)
├── docker-compose.yml           # local Postgres for dev (local-only)
├── bootstrap.sh                 # one-shot local-dev setup
├── scripts/deploy.sh            # canonical end-to-end deploy
├── docs/
│   ├── pattern.md               # how the isolation pattern works (authoritative)
│   ├── architecture.md          # system design
│   ├── deploy.md                # deploy walkthrough
│   ├── local-dev.md             # local dev guide
│   ├── customizing.md           # swap the demo domain, change schema
│   ├── scaling.md               # workspace caps, Genie 10k cap, Lakebase
│   ├── security-rbac.md         # app login, AES-at-rest, admin bypass, audit
│   ├── edge-gateway.md          # optional external front door (edge/)
│   ├── code-snippets.md         # annotated code walk-through
│   └── migration-from-poc.md    # for anyone who cloned the original POC
├── server/                      # FastAPI backend
│   ├── app.py
│   ├── routers/                 # auth, genie, tenants, audit, jobs, verify, agent, workspace
│   ├── services/                # runtime singletons, genie_service, embed_service, tenant_service
│   ├── primitives/              # sp_manager, identity, genie, managed_mcp, unity_catalog, aibi_embed
│   ├── lib/                     # config, db, auth (app login), inspector, repository/ (Lakebase)
│   ├── agent/                   # optional LLM insights
│   └── jobs/                    # in-process bulk onboard runner
├── edge/                        # optional Firefly-style front door (reverse proxy + token broker)
├── web/                         # React + Vite + Tailwind UI
│   └── src/
│       ├── brand/               # brand.ts + theme.css — the rebrand layer
│       ├── pages/               # Home, Ask, Dashboards, Login, console (Admin/Diagnostics/Architecture)
│       ├── components/          # ask/, console/, dashboards/, ui/, ProductShell
│       └── lib/                 # api/ (http + per-domain modules), auth, tenant
├── sql/                         # UC schema + Lakebase migrations
│   ├── setup.sql                # UC: schema, tenants, sp_tenant_mapping, row filter fn
│   └── lakebase/V*.sql          # Lakebase migrations applied on startup (incl. app_users)
├── domain/                      # swappable demo data
│   └── travel/                  # bookings, customers, sample questions
├── scripts/                     # CLI: seed_demo, bulk_onboard, verify_isolation, publish_dashboard, ...
├── tests/                       # pytest unit + integration
└── diagrams/                    # Mermaid sources
```

## Adapting it

- **Different demo data?** Copy `domain/travel/` → `domain/<your-domain>/`, edit, set `DOMAIN=<your-domain>`. See [docs/customizing.md](docs/customizing.md).
- **Different Genie space per tenant?** The `client_registry.genie_space_id` column already exists — surface it in the UI when you need it.
- **Pattern B (custom claims)?** A future direction; not implemented in this reference.

## Status

Reference solution that runs on a Databricks workspace via Databricks Apps. 57 unit/integration tests; isolation enforced by UC row filters; AES-GCM at rest for SP credentials; in-process bulk onboard runner with a documented swap-path to a Databricks Job for production scale.

What's intentionally not in this reference (each is a future direction): per-tenant rate limits, cost/token tracking per tenant, multi-Genie-space UI, and Pattern B (shared SP + custom claims).
