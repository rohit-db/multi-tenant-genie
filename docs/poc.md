# Multi-Tenant Genie — Service Principal Management POC

**Status:** Working demo on FEVM Serverless workspace
**Author:** Rohit Bhagwat (rohit.bhagwat@databricks.com)
**For:** BCD / Advito / Persistent engineering teams
**Companion:** [Data Isolation Architecture](../../obsidian/Accounts/bcd-travel/Data%20Isolation%20Architecture.md) · [Apr 14 decision meeting](../../obsidian/Accounts/bcd-travel/meeting-notes/2026-04-14%20-%20SP%20Architecture%20%26%20Databricks%20Apps%20Decision.md)

---

## What this POC proves

A production-shape answer to the Apr 14 decision: **one Service Principal per client organization, row-level isolation via Unity Catalog, zero dependence on Genie's prompt behavior.** The demo lets an admin onboard/rotate/deactivate tenants through a UI, then query Genie as any tenant and see that the SP identity flows all the way into UC row filters.

Run the `Isolation sweep` on the Client tab to watch four SPs ask the same question over the same table and get four different answers — the numbers differ because of UC row filters, not because Genie did something smart. A brand-new tenant with no seeded data truthfully reports **0 bookings**, confirming the filter denies by default.

## Environment

| | |
|---|---|
| Workspace | `fevm-serverless-jsr0s9.cloud.databricks.com` |
| Catalog / Schema | `serverless_jsr0s9_catalog.mt_genie_demo` |
| Genie Space | `01f13e70745b1ce5b9cf8d9e6a46e23f` — *Multi-Tenant Bookings Demo* |
| Warehouse | `Serverless Starter Warehouse` (`c6b96882e77fb51e`) |
| Secret scope | `mt-genie-demo` (Databricks-backed) |
| Tenant pattern | SP per client org (Pattern A) |
| Isolation | UC row filter + mapping table joined on `session_user()` |

## Architecture in one picture

```
 ┌────────────── Admin UI (React) ──────────────┐         ┌──────────── FEVM Workspace ─────────┐
 │ onboard / rotate / deactivate / audit        │         │                                     │
 │                                              │──────►  │  Workspace SCIM  ─ creates SP       │
 │                                              │         │  SP secret API    ─ mints secret    │
 │  stores secret in secret scope               │         │  Secret scope     ─ holds secret    │
 └───────────────┬──────────────────────────────┘         │  UC Delta         ─ tenants,        │
                 │                                        │                    sp_tenant_mapping│
                 │ update mapping via SQL Warehouse       │                    bookings, audit  │
                 ▼                                        │  UC Row Filter    ─ enforcement     │
 ┌────────────── Client UI (React) ─────────────┐         │  Genie Space      ─ tenant_scoped   │
 │ pick tenant → question → Ask Genie           │         │                    SQL              │
 │                                              │         │                                     │
 │ Token minter ──► /oidc/v1/token              │──────►  └─────────────────────────────────────┘
 │ (cached per SP, 55 min TTL)                  │               ▲
 │ Genie Client ──► /api/2.0/genie/spaces/...   │───────────────┘
 └──────────────────────────────────────────────┘          session_user() = <sp_app_id>
```

## Repo layout

```
multi-tenant-genie/
├── src/
│   ├── lib/                  # reusable Python modules (used by scripts AND api/)
│   │   ├── config.py         # single source of truth for names/IDs
│   │   ├── sp_manager.py     # create / list / rotate / deactivate / grant*
│   │   ├── token_minter.py   # per-SP OAuth M2M token cache
│   │   └── genie_client.py   # /api/2.0/genie/spaces ask+poll
│   ├── scripts/
│   │   ├── seed_demo.py      # idempotent bootstrap (schema + tables + 3 SPs + 600 bookings)
│   │   └── verify_isolation.py  # headless isolation proof (runs SELECTs as each SP)
│   └── sql/
│       ├── setup.sql         # DDL + row filter (reference — scripts also run it)
│       └── lakebase_schema.sql  # target schema if we move audit/secrets to Lakebase later
├── api/                      # FastAPI — thin wrapper around src/lib
│   ├── app.py
│   └── routers/
│       ├── tenants.py        # SP lifecycle + audit + mapping
│       ├── genie.py          # ask / sweep
│       └── workspace.py      # UI config bootstrap
├── web/                      # Vite + React + shadcn/ui + Tailwind + @tanstack/react-query
│   ├── src/App.tsx           # tabbed shell
│   ├── src/pages/
│   │   ├── AdminPage.tsx     # stat cards + tenants table + audit feed
│   │   ├── ClientPage.tsx    # Ask as tenant + Isolation sweep
│   │   └── ArchitecturePage.tsx  # live mapping + live row-filter SQL
│   └── src/lib/api.ts        # typed FastAPI client
└── docs/
    ├── architecture.md       # original pattern write-up
    ├── pattern-a-sp-per-client.md
    ├── pattern-b-custom-claims.md
    └── poc.md                # (this document)
```

## What happens in each lifecycle step

### Onboarding
1. `w.service_principals.create(display_name=<slug>, active=True)` — SCIM create, returns `application_id`.
2. `w.service_principal_secrets_proxy.create(service_principal_id=<sp_db_id>)` — mints an OAuth `client_secret`. Returned **exactly once**; rotate if lost.
3. `w.secrets.put_secret(scope="mt-genie-demo", key=<app_id>, string_value=<secret>)` — persists it in a workspace-scoped secret scope.
4. `INSERT INTO tenants …` + `INSERT INTO sp_tenant_mapping …` via the SQL Warehouse.
5. `GRANT USE CATALOG / USE SCHEMA / SELECT` on the demo objects to the SP.
6. `PATCH /api/2.0/permissions/genie/<space_id>` to grant `CAN_RUN` on the Genie Space.

Everything above is idempotent except step 2 — re-onboarding returns the existing SP but a fresh rotation is still needed.

### Rotation
1. Create a new secret first — the SDK returns it as plaintext.
2. Persist the new secret to the scope.
3. **Then** delete the prior secret(s). Any access token minted from the old secret keeps working until it naturally expires (~55 min), so in-flight Genie calls aren't interrupted. Databricks allows up to 5 concurrent secrets per SP, so overlap is safe.

### Deactivation
1. `SP.update(active=False)` — immediately blocks new token exchanges.
2. Delete every SP secret so even cached secrets stop resolving.
3. `UPDATE sp_tenant_mapping SET active=false WHERE sp_app_id=…` so even if a stale token somehow reaches UC, the row filter rejects it.
4. `UPDATE tenants SET status='deactivated'`.
5. Audit the event.

## The isolation enforcement

```sql
CREATE OR REPLACE FUNCTION mt_genie_demo.tenant_row_filter(tenant_param STRING)
RETURN
  is_account_group_member('admins')
  OR EXISTS (
    SELECT 1 FROM mt_genie_demo.sp_tenant_mapping m
    WHERE m.sp_app_id = session_user()
      AND m.active = true
      AND m.tenant_id = tenant_param
  );

ALTER TABLE mt_genie_demo.bookings
  SET ROW FILTER mt_genie_demo.tenant_row_filter ON (tenant_id);
```

Key facts:
* `session_user()` on a Databricks OAuth M2M token returns the SP's `application_id`. Verified on FEVM: each tenant's `session_user()` is a distinct UUID.
* The filter is bound to the column `tenant_id`. UC evaluates it once per row and short-circuits.
* The admin bypass uses `is_account_group_member('admins')` so the platform team retains full visibility without a separate grant path.
* We use a **mapping table, not groups**. Groups have a hard 5K limit; mapping tables scale linearly.

## Answers to the Apr 14 open questions

### 1. How will SP credentials be stored?
**POC:** Databricks-backed secret scope (`mt-genie-demo`), one key per SP (`<application_id>`). Scope ACL'd to admins.
**Prod recommendation:** Keep the secret scope as the source of truth — app code reads directly from `dbutils.secrets.get(...)` inside a Databricks App / Job, or via the `GET /api/2.0/secrets/get` API from an external host using an admin SP. AWS Secrets Manager is an option, but auto-rotation needs a custom Lambda (it doesn't speak the Databricks SP API natively), so it adds ops burden without buying much. The prod story worth investing in is **OIDC federation** so the app never has long-lived secrets at all.

### 2. SP lifecycle automation — SDK vs Terraform?
**Both, for different phases:**
* **SDK / Python** (this repo) for event-driven flows: onboard on customer signup, rotate on schedule, deactivate on churn. These are called from app code.
* **Terraform** for baseline/compliance: catalog, schema, row filter, audit table, the admin SP, group memberships. Drift-detect those weekly.

Don't split per-tenant resources across IaC states — a customer onboarding via Terraform workflow can't complete in one commit, and the state file becomes a shared bottleneck at 100+ tenants.

### 3. SP-to-org mapping schema
See `src/sql/setup.sql`. Deliberately minimal so the row-filter join is O(1):
```sql
sp_tenant_mapping (sp_app_id STRING, tenant_id STRING, active BOOLEAN)
```
`tenants` holds everything non-enforcement (display name, status, timestamps). If you later need attribute-based access (regions, tiers, products), widen `sp_tenant_mapping` and update the row filter — the schema isn't load-bearing for correctness.

### 4. Does `@databricks/aibi-client` SDK work with SP-scoped tokens?
**Out of scope for this POC** (we deliberately skipped dashboards). The Databricks Solutions reference `aibi-dashboards-external-embedding` confirms the pattern works end-to-end with user tokens and `__aibi_external_value`; validating the exact SP-scoped token flow is the next follow-up.

### 5. Conversation history / agent SP
App owns it. The Genie Conversation API returns `conversation_id` + `message_id` per call; the app maps those to real users in its own DB (Lakebase recommended). Genie's native "conversations per space" (10K limit) is a global pool — don't depend on it for per-user history.

## Scaling math — thousands of SPs

| Constraint | Limit | Reality at 3K SPs |
|---|---|---|
| Account identity limit | 10K (soft, raisable) | 3K + internal users fits; support ticket if combined with CSS/Decision Source |
| OAuth secrets per SP | 5 | Ample headroom for zero-downtime rotation |
| Max secret lifetime | 730 days | Target 90-day rotation |
| Genie QPS per workspace | 5 questions/min | Multi-workspace + caching — see `docs/scaling.md` |
| Row filter overhead | join on 3K-row mapping | Delta + Z-order on `sp_app_id` — sub-10ms |
| Bootstrap time | SCIM + secret + grants per SP | ~12s / SP serially, ~1s / SP in parallel (measured) |

## Why not Pattern B (shared SP + custom claims)?

`docs/pattern-b-custom-claims.md` describes it: one SP total, tenant ID passed in a custom JWT claim, read via `current_oauth_custom_identity_claims()`. It's cleaner on paper — **O(1) SP lifecycle**, no rotation fanout, no identity limit pressure.

**Why we built Pattern A instead:**
1. Apr 14 meeting decision — the team committed to per-org SPs.
2. Genie API support for `current_oauth_custom_identity_claims()` is unverified on the target workspace.
3. Pattern A works today with GA primitives.

**Migration plan if B becomes viable:**
* Keep the same UI and mapping table.
* Replace the Pattern A filter with the Pattern B claim-based version.
* SPs collapse to a single shared identity; rotation goes from N to 1.
* Token minter signature changes from `(client_id, client_secret)` → `(shared_client_id, shared_client_secret, custom_claim=tenant_id)`.

The rest of the codebase (onboarding UI, audit, scaling strategy) doesn't move.

## How to run it locally

```bash
# 1. Bootstrap (once — idempotent)
cd ~/Documents/github/multi-tenant-genie
python -m src.scripts.seed_demo

# 2. Headless isolation proof
python -m src.scripts.verify_isolation

# 3. Start the UI
uvicorn api.app:app --host 127.0.0.1 --port 8000 --reload  # terminal A
cd web && npm install && npm run dev                       # terminal B
open http://localhost:5173
```

## What's still open

- [ ] **Terraform module** for baseline infra (catalog, schema, row filter, admin SP, Genie space).
- [ ] **Rotation worker** (Databricks Job) that rotates any secret older than 90 days.
- [ ] **Load test harness** — prove 1K SPs sustain 5 QPS without violating Genie limits.
- [ ] **Pattern B viability test** — does `current_oauth_custom_identity_claims()` surface inside Genie-generated SQL?
- [ ] **Dashboard embed** — bind the same SP tokens to `@databricks/aibi-client` and retest.
- [ ] **Lakebase migration** — move the audit log + token cache (not the mapping table) to a Lakebase instance; reverse-sync back to UC if needed.

## Pointers

* Full pattern: [`docs/pattern-a-sp-per-client.md`](pattern-a-sp-per-client.md)
* Scaling: [`docs/scaling.md`](scaling.md)
* Security / RBAC: [`docs/security-rbac.md`](security-rbac.md)
* BCD context: [`docs/bcd-context.md`](bcd-context.md)
* Reference external-embedding code (lifted token-minter pattern): <https://github.com/databricks-solutions/aibi-dashboards-external-embedding>
* Reference Genie-as-code governance: <https://github.com/databricks-solutions/genierails>
