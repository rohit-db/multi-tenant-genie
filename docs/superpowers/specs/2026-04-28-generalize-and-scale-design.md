# Generalize & Scale — Design Spec

**Date:** 2026-04-28
**Branch:** `generalize-and-scale`
**Author:** Rohit Bhagwat
**Status:** Draft, awaiting user review

## 1. Goal

Convert the BCD/Advito-flavored multi-tenant Genie POC into a credible reference solution that any Databricks SA, SE, or customer engineering team can fork, deploy as a Databricks App, and adapt. The repo today is a working POC for one named account; the target is a polished reference that works out of the box, demos the isolation pattern visibly, and has a hardenable production core.

## 2. Decisions locked during brainstorm

| # | Decision | Rationale |
|---|---|---|
| 1 | Tier the audience: SAs primary (default landing experience), customer engineering teams secondary. Demo mode is a thin layer on a production-grade core, not a watered-down version. | SAs are who finds and forks first; customer eng won't take it seriously without real production wiring. |
| 2 | Pattern A only (SP-per-client). Pattern B (custom claims) gets one paragraph in `docs/future-directions.md`. No stubs, no toggles. | Pattern B is blocked on Genie surface support; investing now wastes cycles. |
| 3 | Keep travel as the demo domain. Factor for one-folder swap (`domain/<name>/`). | The USP is the isolation pattern, not the domain. Travel is concrete and credible enough. |
| 4 | UI shape: "Demo Theater" — three tabs (Demo, Admin, Architecture). | Story-first beats operator-first for the primary audience. Operator depth fits inside Admin without a dedicated tab. |
| 5 | Hero feature: request-flow inspector with **six** steps (F2). Step ④ "Apply row filter" is first-class because it is the educational payoff. | The whole demo answers "how do you stop tenant A seeing tenant B's data?" — the row filter is that answer. |
| 6 | Deploy story: Databricks Apps as canonical (R3); local dev is secondary, supported, but not where the polish goes. | Aligns with the platform; lets us use Apps resources (Lakebase, warehouse, Genie space) natively. |
| 7 | New feature surface: N1 (bulk onboard UI) + N2 (tenant lifecycle UI: rotate, deactivate, reactivate, hard-delete) + N3 (isolation verifier panel) + N4 (per-tenant query history). N5 (rate-limit / quotas) and N7 (cost tracking) deferred to a future spec. N6 (multi-Genie-space) is **architected for** (`tenants.genie_space_id` column) but not surfaced in UI. | Each shipped feature polishes existing surface; deferred items each open a multi-day rabbit hole and aren't blocking the demo audience. |
| 8 | Lakebase as the OLTP metadata backend. UC Delta stays the home of governed customer data and the row-filter join target. | Today the metadata sits in UC Delta; that's slow on the request hot path and the wrong tool. Lakebase is the modern Databricks pattern for OLTP and is already provisioned natively by Apps. The repo's existing `lakebase_schema.sql` confirms this was original intent. |
| 9 | DELETE is hard-delete with a confirmation dialog. SP is removed from the workspace. | Soft-delete clutters the workspace and the registry without earning anything. |
| 10 | Bulk onboarding runs as an in-process job with progress polling. Documented swap-path to a real Databricks Job runner for production scale. | Reference-grade complexity is correct; production swap is a localized change later. |
| 11 | Inspector is **not gimmicky**: amber accent on step ④ is static, no pulses. Animations capped at 100 ms fades. Inspector is collapsed by default. Plain copy. | Credibility beats theatre. |
| 12 | Old POC docs (`bcd-context.md`, `followup-email.md`, `poc.md`, `poc-flow.md`, `pattern-b-custom-claims.md`) are **deleted**, not archived. Git history preserves them for anyone who cares. | Cleaner repo. |

## 3. Repo identity & structure

**Project name:** `multi-tenant-genie` (unchanged).
**Subtitle:** *"A reference solution for delivering Databricks Genie to thousands of isolated tenants."*

**Target structure:**

```
multi-tenant-genie/
├── README.md                        # one-screen pitch · 5-min quickstart · deploy link
├── app.yaml                         # Databricks Apps manifest (canonical deploy)
├── docker-compose.yml               # local Postgres for dev mode
├── bootstrap.sh                     # local-dev one-shot setup
├── pyproject.toml
├── requirements.txt
├── docs/
│   ├── architecture.md
│   ├── pattern.md                   # was pattern-a-sp-per-client.md (poc-flow.md folded in)
│   ├── deploy.md                    # NEW — Databricks Apps deploy guide
│   ├── local-dev.md                 # NEW — local dev guide
│   ├── customizing.md               # NEW — swap domain, change schema, point at your data
│   ├── scaling.md                   # edited — Lakebase scaling notes + 10k Genie cap pointer
│   ├── security-rbac.md             # edited — drop BCD specifics
│   ├── code-snippets.md             # edited — drop BCD specifics
│   ├── future-directions.md         # NEW — Pattern B + N5/N6/N7 callouts
│   ├── migration-from-poc.md        # NEW — for anyone who already cloned the POC
│   └── references.md                # edited — drop internal-only links
├── server/                          # was api/ — FastAPI proxy
│   ├── app.py
│   ├── routers/
│   │   ├── tenants.py               # CRUD + bulk + lifecycle
│   │   ├── genie.py                 # ask, sweep, with inspector payload
│   │   ├── verify.py                # isolation verifier
│   │   ├── audit.py                 # global audit + per-tenant history
│   │   ├── jobs.py                  # bulk-onboard job polling
│   │   └── workspace.py
│   ├── lib/                         # was src/lib/
│   │   ├── config.py
│   │   ├── db.py                    # NEW — Lakebase / Postgres connection
│   │   ├── repository/              # NEW — repo pattern
│   │   │   ├── tenant.py            # client_registry CRUD (Lakebase)
│   │   │   ├── audit.py             # audit_log writes/reads (Lakebase)
│   │   │   ├── credential.py        # sp_credentials encrypt/get/put (Lakebase, AES-GCM)
│   │   │   └── mapping.py           # sp_tenant_mapping CRUD (UC Delta — for row filter)
│   │   ├── sp_manager.py            # orchestrates: Databricks SP API + tenant_repo + mapping_repo
│   │   ├── token_minter.py          # OAuth M2M token cache
│   │   ├── genie_client.py          # Genie Conversation API wrapper
│   │   ├── inspector.py             # NEW — assembles the six-step inspector payload
│   │   └── domain.py                # NEW — domain registry, loads domain/<name>/
│   └── jobs/
│       └── bulk_onboard.py          # in-process job runner with progress
├── web/                             # unchanged shape, richer content
│   └── src/
│       ├── App.tsx
│       ├── pages/
│       │   ├── DemoPage.tsx         # was ClientPage.tsx — renamed
│       │   ├── AdminPage.tsx        # rewired
│       │   └── ArchitecturePage.tsx # rewritten
│       ├── components/
│       │   ├── Inspector.tsx        # NEW — six-step strip + expansion panel
│       │   ├── BulkOnboardDialog.tsx
│       │   ├── VerifyIsolationModal.tsx
│       │   ├── TenantHistoryDrawer.tsx
│       │   ├── NumbersStrip.tsx
│       │   ├── Mermaid.tsx
│       │   └── ui/                  # shadcn primitives
│       └── lib/
├── sql/                             # was src/sql/
│   ├── setup.sql                    # UC schema (data + sp_tenant_mapping + row filter)
│   └── lakebase/
│       ├── V001__initial.sql        # client_registry, sp_credentials, audit_log, token_cache
│       └── V002__future.sql         # placeholder; later migrations land here
├── scripts/                         # was src/scripts/
│   ├── seed_demo.py                 # uses domain registry
│   ├── bulk_onboard.py              # CLI wrapper around the same job runner
│   └── verify_isolation.py          # the isolation test (also CI + UI)
├── domain/                          # NEW — swappable
│   ├── travel/
│   │   ├── seed.py
│   │   ├── schema.sql
│   │   └── sample_questions.json
│   └── README.md                    # how to swap
└── diagrams/                        # cleaned up; only what's used
```

**Renames / moves:**
- `api/` → `server/`
- `src/lib/` → `server/lib/`
- `src/scripts/` → `scripts/`
- `src/sql/setup.sql` → `sql/setup.sql`
- `src/sql/row_filters.sql` → folded into `sql/setup.sql`
- `src/sql/lakebase_schema.sql` → `sql/lakebase/V001__initial.sql` (versioned migration)
- `src/ui/` → deleted (unused)
- `web/src/pages/ClientPage.tsx` → `web/src/pages/DemoPage.tsx`

**Deletes (POC residue):**
- `docs/poc.md`
- `docs/poc-flow.md` (content folded into `docs/pattern.md`)
- `docs/bcd-context.md`
- `docs/followup-email.md`
- `docs/pattern-b-custom-claims.md` (one-paragraph callout in `docs/future-directions.md` replaces it)

## 4. Backend & data model

### 4.1 Storage split

| Table | Store | Why |
|---|---|---|
| `client_registry` | Lakebase | Read on every request — Postgres latency. Has `genie_space_id` (nullable, N6 design-for-it) and `metadata` JSONB (free-form per-tenant fields). |
| `sp_credentials` | Lakebase | Encrypted at rest with AES-GCM; small, hot, secret. |
| `audit_log` | Lakebase | Hot writes per request; Postgres throughput. Reverse-ETL to UC for analytics is a documented future option, not built. |
| `token_cache` | Lakebase (optional) | Multi-instance proxy support. Single-instance uses in-memory cache and skips this table. |
| `sp_tenant_mapping` | UC Delta | **Required** here — the row filter SQL joins it from inside the warehouse. |
| Domain data (e.g. `bookings`, `customers`) | UC Delta | Genie queries this; row-filter applies. |

`server/lib/repository/mapping.py` is the only repository that talks to UC Delta (via SQL warehouse statement execution); the other three repositories (`tenant`, `audit`, `credential`) talk to Lakebase via `server/lib/db.py`. The repository pattern intentionally hides this split from callers — `sp_manager.py` and the routers don't know or care which store backs which repo.

### 4.2 Onboarding transactional contract

Onboarding a tenant must succeed in three places or fully roll back:
1. Create SP via Databricks workspace API.
2. Insert into `sp_tenant_mapping` (UC Delta) — the row filter join.
3. Insert into `client_registry` and `sp_credentials` (Lakebase).

If any step fails, the SP is deleted and any partial writes are reversed. This is implemented in `server/lib/sp_manager.py` with explicit try/finally cleanup, not relying on distributed transactions.

### 4.3 Endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/tenants` | List tenants. (existing) |
| `POST` | `/api/tenants` | Onboard one. (existing) |
| `POST` | `/api/tenants/bulk` | **N1** Bulk onboard from JSON list or CSV. Returns `{ job_id }`. |
| `GET` | `/api/jobs/{job_id}` | Poll bulk-onboard progress. Returns `{ status, processed, total, errors[] }`. |
| `POST` | `/api/tenants/{id}/rotate` | **N2** Rotate OAuth secret. Returns new secret once. |
| `POST` | `/api/tenants/{id}/deactivate` | **N2** Deactivate (mapping `active=false`, status=`deactivated`). |
| `POST` | `/api/tenants/{id}/reactivate` | **N2** Reactivate; reissues secret. |
| `DELETE` | `/api/tenants/{id}` | **N2** Hard delete: removes SP, deletes registry rows. Confirmation guarded at UI. |
| `GET` | `/api/tenants/{id}/history?limit=K` | **N4** Per-tenant query history from `audit_log`. |
| `POST` | `/api/verify` | **N3** Run isolation verifier across all active tenants. Returns per-tenant pass/fail with row-count detail. |
| `POST` | `/api/genie/ask?inspect=true` | Ask + inspector payload (six-step `inspector` block). |
| `POST` | `/api/genie/sweep` | Same question across all active tenants (existing). |
| `GET` | `/api/audit?limit=K` | Global audit tail (existing). |
| `GET` | `/api/workspace` | Workspace metadata (existing). |

### 4.4 Inspector payload contract

```jsonc
// Response of POST /api/genie/ask?inspect=true
{
  "answer": { /* existing fields */ },
  "inspector": {
    "request_id": "req_01HXY…",
    "steps": [
      { "n": 1, "name": "Authenticate",     "duration_ms": 3,    "summary": "API key matched tenant_id=nike", "code_snippet": "...",  "payload_in": {...}, "payload_out": {...} },
      { "n": 2, "name": "Resolve tenant",   "duration_ms": 2,    "summary": "Lakebase lookup → genie_space_id=null → use global", "code_snippet": "SELECT * FROM client_registry WHERE tenant_id = $1", "payload_in": {...}, "payload_out": {...} },
      { "n": 3, "name": "Mint token",       "duration_ms": 0,    "summary": "Cache hit; token expires in 38 min", "code_snippet": "...", "payload_in": {...}, "payload_out": {...} },
      { "n": 4, "name": "Apply row filter", "duration_ms": 0,    "summary": "Filter resolves to tenant_id='nike' for sp_app_id=3f8a2c…", "code_snippet": "<row_filter SQL>", "payload_in": {...}, "payload_out": {...} },
      { "n": 5, "name": "Ask Genie",        "duration_ms": 2113, "summary": "Genie returned 1 row, 4 cols", "code_snippet": "...", "payload_in": {...}, "payload_out": {...} },
      { "n": 6, "name": "Audit",            "duration_ms": 1,    "summary": "audit_log row id=4711 written", "code_snippet": "...", "payload_in": {...}, "payload_out": {...} }
    ]
  }
}
```

Step ④ never has a runtime `duration_ms > 0` because the row filter is enforced in-warehouse — but the inspector shows it as a step anyway because *it is the central concept*. The `summary` resolves the filter to a concrete tenant_id for the demo.

## 5. Frontend

Three tabs: **Demo · Admin · Architecture**. Tab order matches expected use frequency.

### 5.1 Demo tab
- Left column: tenant picker (active tenants only), ask textarea (default sample question), 5 sample-question chips, primary "Ask" button + secondary "Sweep across all tenants" button.
- Right top: result card. Single-row aggregates render large; multi-row renders a table; the SQL Genie generated is shown in a small monospace caption below the result.
- Right bottom: `Inspector` component. Six-step horizontal strip. Step ④ rendered with a static amber accent. Inspector collapsed by default; one click on a step expands the detail panel below the strip.
- Sweep view: result card swaps for a grid (one tile per active tenant). The inspector binds to the focused tile; click another tile to swap inspector context.

### 5.2 Admin tab
- Top: `NumbersStrip` — *Active tenants · Queries (last hour) · p95 latency (last hour) · Errors (last hour)*. Computed from Lakebase `audit_log`.
- Action row (right-aligned): `[+ Onboard one]` `[Bulk onboard…]` `[Verify isolation]`.
- Tenant table: `tenant_id`, `name`, `status` (badge), `sp_app_id` (truncated, copyable), `created_at`, `last_query_at`, actions menu (rotate / deactivate / reactivate / delete / view history). Destructive actions confirm. Rotate shows the new secret once with a copy button.
- Per-tenant `TenantHistoryDrawer`: opens from "view history" — last K queries, latency sparkline, status counts.
- `BulkOnboardDialog`: paste-JSON or CSV upload → preview row count → "Run" → progress bar with per-row outcome → downloadable report (gitignored, contains plaintext secrets — same constraint as today's CLI).
- `VerifyIsolationModal`: runs `/api/verify`, returns a green/red row per active tenant with "expected N, got N" detail.
- Audit log section at the bottom: last 50 rows, filterable by tenant + action.

### 5.3 Architecture tab
- Updated Mermaid diagram (cleaner; calls out Lakebase + UC + Genie explicitly).
- Pattern walkthrough: six numbered steps mirroring the inspector's six steps.
- "Future directions" callout: links `docs/future-directions.md`.
- "What's intentionally not in this reference" callout: rate-limits, multi-Genie-space UI, cost tracking, with rationale.

### 5.4 Net-new components
- `Inspector` — the hero. Static amber accent on step ④; no pulses; 100 ms fade on expansion.
- `BulkOnboardDialog`
- `VerifyIsolationModal`
- `TenantHistoryDrawer`
- `NumbersStrip`

### 5.5 Component design rule
Inspector and dialogs are credible, not theatrical. No animations beyond 100 ms fades. Plain copy ("Apply row filter", not "✨ The magic happens here"). Default-collapsed inspector. Static color accents only.

## 6. Configuration, deployment, first-run

### 6.1 Single config source
`server/lib/config.py` produces a typed frozen `Config`. Both deploy surfaces populate the same env-var names:

```python
@dataclass(frozen=True)
class Config:
    workspace_host: str
    catalog: str
    schema: str
    genie_space_id: str
    warehouse_id: str
    admin_group: str
    database_url: str
    aes_key: bytes | None  # None permitted only when auth_mode == "pat"
    domain: str = "travel"
    auth_mode: Literal["pat", "oauth-app"] = "oauth-app"
```

`auth_mode` is selected at startup based on which env vars are present. PAT mode is local-dev only; Apps deploy uses OAuth.

### 6.2 Surface 1: Databricks Apps (canonical)
`app.yaml` declares: Lakebase resource, SQL warehouse permission, Genie space permission, AES-key secret. The runtime injects env vars; the proxy reads `Config` from env. First deploy provisions Lakebase (a few minutes); subsequent deploys reuse it. Schema migrations run via a startup hook reading `sql/lakebase/V*.sql` in version order; idempotent.

The app's SP needs `CAN_MANAGE_SERVICE_PRINCIPALS` workspace-level — documented as a one-time grant in `docs/deploy.md`.

If `AES_KEY_REF` is unset in Apps deploy mode, bootstrap fails closed with a clear error.

### 6.3 Surface 2: Local dev
`./bootstrap.sh`:
1. Prompts for `.env.local` values if missing (workspace host, PAT, catalog, Genie space ID).
2. `docker compose up -d postgres` (Postgres 16 container).
3. Applies `sql/lakebase/V*.sql` to local Postgres.
4. Applies `sql/setup.sql` to user's UC workspace; seeds the active domain.
5. Starts FastAPI on `:8000` and Vite on `:5173`.

Idempotent. Target ≤ 90s on a warm machine.

### 6.4 Surface 3: One-shot demo mode
`./bootstrap.sh --demo` runs Surface 2 + auto-onboards the three demo tenants (Nike / CloudVenture / Acme Industrial) and seeds bookings. This is the path the README's recording uses.

### 6.5 AES key in local dev
Optional. Storing demo SP credentials plaintext on a local Postgres is acceptable for a throwaway demo. The proxy logs a loud `WARN` on startup when `aes_key is None` and `auth_mode == "pat"`. In Apps deploy, the absence of an AES key is a hard startup failure.

## 7. Domain layer

`server/lib/domain.py` resolves the active domain at startup from `DOMAIN` env var (default `travel`) and exposes:

```python
class Domain:
    name: str
    sample_questions: list[str]
    row_filter_column: str           # e.g. "tenant_id"
    def schema_sql(self) -> str: ...
    def seed(self, conn) -> None: ...
```

Routers and UI fetch `sample_questions` and the human-readable display label via the API; nothing in `server/` or `web/` references the word "travel" or "bookings". Swapping domain is: copy `domain/travel/` to `domain/mydomain/`, edit, set `DOMAIN=mydomain`. Documented in `docs/customizing.md` and `domain/README.md`.

`scripts/seed_demo.py` is the runner invoked by `bootstrap.sh --demo`; it loads the active domain via `domain.load(name)` and calls `domain.schema_sql()` and `domain.seed(conn)`. The travel-specific seed logic that lives in `src/scripts/seed_demo.py` today moves into `domain/travel/seed.py`; the runner becomes a thin orchestrator.

## 8. Documentation

### 8.1 Docs to keep / rewrite
- `README.md` — rewrite as one-screen pitch + 5-min quickstart + deploy link.
- `docs/architecture.md` — strip BCD framing; add Lakebase-vs-UC split; cleaner diagram.
- `docs/pattern.md` — renamed from `pattern-a-sp-per-client.md`; folds in `poc-flow.md`. The canonical "how the isolation works" doc.
- `docs/scaling.md` — keep numbers, drop BCD context, add Lakebase scaling notes + 10k Genie cap pointer.
- `docs/security-rbac.md` — keep AES-at-rest + admin-group bypass; drop BCD specifics.
- `docs/code-snippets.md` — drop BCD specifics.
- `docs/references.md` — drop internal-only escalation links; keep public refs.

### 8.2 Docs to add
- `docs/deploy.md` — Databricks Apps deploy guide (canonical).
- `docs/local-dev.md` — local dev guide (secondary).
- `docs/customizing.md` — swap domain, change schema, point at your data.
- `docs/future-directions.md` — Pattern B + N5/N6/N7 callouts; what's intentionally not here, why, how to add it.
- `docs/migration-from-poc.md` — for anyone who already cloned the POC: schema delta + rename map.
- `domain/README.md` — swap-the-domain instructions.

### 8.3 Docs to delete
`docs/poc.md`, `docs/poc-flow.md` (folded into `pattern.md`), `docs/bcd-context.md`, `docs/followup-email.md`, `docs/pattern-b-custom-claims.md`. Git history preserves them.

## 9. Testing

### 9.1 Unit tests (~15)
- `tenant_repo` CRUD round-trip
- `audit_repo` append + read-by-tenant
- `credential_repo` AES-GCM encrypt/decrypt round-trip
- `inspector.assemble()` with a fake genie response — verifies all six steps populate
- `domain.load("travel")` returns expected sample questions and schema
- `bulk_onboard` job state transitions: success / partial-failure / total-failure
- `sp_manager.onboard()` rolls back SP creation if Lakebase write fails

Run against a Postgres testcontainer; warehouse + Genie are mocked at the boundary.

### 9.2 Isolation test (two flavors, honest framing)

The row filter runs *inside* a SQL warehouse, so a CI run that mocks the warehouse cannot prove the filter actually enforces. Two flavors:

- **CI flavor — proxy contract.** `tests/test_isolation_contract.py` runs in CI against a Postgres testcontainer and a mocked warehouse. It seeds three tenants, asserts the proxy hands the correct SP credentials per request, asserts cross-tenant credential leaks are impossible, asserts the row-filter SQL the proxy *would* apply matches the expected shape. Validates the proxy contract; does not validate the filter itself. Blocks PR merges.
- **Release-gate flavor — real UC.** `scripts/verify_isolation.py` runs against a real workspace. It seeds tenants, executes queries through the actual warehouse, asserts each tenant sees only its own rows, asserts admin bypass works. This is the test that proves the filter holds. Runs (a) manually before any release tag, (b) in the runtime `VerifyIsolationModal` when an SA wants to demo the credibility moment, (c) optionally as a nightly GitHub Action against a dedicated test workspace if `DATABRICKS_HOST` + `DATABRICKS_TOKEN` are configured as repo secrets.

The `VerifyIsolationModal` runs the release-gate flavor against the live workspace — that's the credibility moment for the demo audience.

### 9.3 No E2E browser tests
Playwright stays as a dev dependency for ad-hoc debugging; no CI specs.

### 9.4 CI pipeline
Single GitHub Actions workflow: lint (ruff + eslint) + unit + isolation test against a Postgres service container. No workspace required for CI. A separate lightweight job checks markdown links in `docs/`.

## 10. Sequencing

This spec is too big for a single implementation plan. Four phased plans:

1. **Phase 1 — Foundation refactor.** Branding scrub *across the entire working tree* (server, web, docs, scripts) + repo restructure (`api/` → `server/`, flatten `src/`, create `domain/` + `sql/lakebase/`) + Lakebase wiring (`db.py`, four repositories, `V001__initial.sql` migration runner, transactional onboard in `sp_manager.py`) + `bootstrap.sh` + `docker-compose.yml`. UI is unchanged in functionality but BCD strings are gone and any moved imports updated. End state: same features as today, new shape, no BCD/Advito strings anywhere.
2. **Phase 2 — Backend feature surface.** New endpoints (`/api/tenants/bulk`, `/api/jobs/{id}`, lifecycle ops, `/api/verify`, `/api/tenants/{id}/history`) + inspector payload on `/api/genie/ask?inspect=true`. The in-process bulk job runner. End state: API complete; UI still consuming only the old endpoints.
3. **Phase 3 — UI rebuild.** Rename `ClientPage.tsx` → `DemoPage.tsx`; build `Inspector`, `BulkOnboardDialog`, `VerifyIsolationModal`, `TenantHistoryDrawer`, `NumbersStrip`; rewire `AdminPage.tsx` to consume the new endpoints; rewrite `ArchitecturePage.tsx` content. End state: feature-complete app on the new IA.
4. **Phase 4 — Deploy + docs.** `app.yaml` finalized, AES-key secret wiring tested end-to-end against a real Apps deployment, all docs rewritten per §8, README polished, demo recording captured. End state: shippable.

Each phase ends with the app demonstrably working — no broken-in-the-middle states. Each gets its own writing-plans pass when we're ready for it.

## 11. Definition of done (whole spec)

- No "BCD" or "Advito" strings anywhere in the working tree.
- `./bootstrap.sh` brings up a working demo in under 2 minutes on a clean machine.
- Deploy to a Databricks Apps instance succeeds following only `docs/deploy.md`.
- Isolation test green in CI; runs in under 30 seconds.
- README has a screen-recording (or animated GIF) of the inspector in action.
- `docs/customizing.md` walks an SA through swapping the domain in under 10 minutes.

## 12. Out of scope (and where to find it)

- **Pattern B (custom claims)** — one-paragraph callout in `docs/future-directions.md`.
- **Per-tenant rate limits / quotas (N5)** — future spec.
- **Cost / token tracking per tenant (N7)** — future spec.
- **Multi-Genie-space UI (N6)** — data model accommodates it (`tenants.genie_space_id`); UI surface is a future spec.
- **Background-job runner** — current is in-process; documented swap-path to a Databricks Job.
- **Reverse-ETL of `audit_log` to UC** — documented option, not built.
- **E2E browser tests** — Playwright stays as a dep; no CI specs.
