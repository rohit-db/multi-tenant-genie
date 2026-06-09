# Architecture Overview

> [`pattern.md`](pattern.md) is the authoritative description of the isolation
> pattern. This page is the system-level companion: the tiers, the components,
> and a single request end to end. [`code-snippets.md`](code-snippets.md) maps
> each step to the code.

## System design

The reference follows the **SSO-SPN (Single Sign-On to Service Principal)**
shape popularized by the [Firefly Analytics](https://www.firefly-analytics.com/)
multi-tenant reference: end users sign in to *your* product, and every
Databricks call runs as a Service Principal whose identity Unity Catalog uses
to scope the data.

This repo implements **Pattern A: one Service Principal per tenant**. There is
no shared SP and no custom identity claim. Each tenant's queries run as that
tenant's SP, and a Unity Catalog row filter trims rows by joining
`sp_tenant_mapping` on `session_user()` — so isolation is enforced in the
warehouse, by Unity Catalog, not by application logic or prompts.

## High-level flow

```
┌──────────────────────────────────────────────────────────────┐
│                        END USERS                              │
│   sign in to the product (app-level login: app_users)        │
│   — separate from Databricks workspace identity              │
└───────────────┬──────────────────────────────────────────────┘
                │ session cookie (PBKDF2 + signed)
                ▼
┌──────────────────────────────────────────────────────────────┐
│                   APP (FastAPI + React)                       │
│                                                              │
│  1. Authenticate end user (app session) → resolve tenant     │
│  2. Look up the tenant's Service Principal                    │
│  3. Mint an OAuth M2M token AS that tenant SP (cache-aware)   │
│  4. Call Genie (REST or Managed MCP) as the tenant SP        │
│  5. Return results; write the audit log                      │
└──────┬───────────────────────┬───────────────────────────────┘
       │                        │
       ▼                        ▼
┌─────────────┐   ┌──────────────────────────────────────────────┐
│  Lakebase   │   │              DATABRICKS WORKSPACE            │
│ (Postgres)  │   │                                              │
│ • tenant    │   │  Genie Space (per tenant SP: CAN_RUN)        │
│   registry  │   │     ↓                                        │
│ • SP creds  │   │  Serverless SQL Warehouse                    │
│   (AES-256) │   │     ↓                                        │
│ • audit log │   │  Unity Catalog                               │
│ • app_users │   │   ┌────────────────────────────────────┐    │
└─────────────┘   │   │ ROW FILTER tenant_row_filter       │    │
                  │   │   JOIN sp_tenant_mapping            │    │
       ┌──────────┤   │   ON session_user()  (= tenant SP) │    │
       ▼          │   └────────────────────────────────────┘    │
┌─────────────┐   └──────────────────────────────────────────────┘
│  Databricks │
│  OIDC       │   POST /oidc/v1/token
│  endpoint   │   grant_type=client_credentials & scope=all-apis
└─────────────┘   (per-tenant SP credentials — no custom claim)
```

## Components

### 1. End users & the app login

End users are customers of *your* product. They authenticate against the app's
own login (`server/lib/auth.py`: PBKDF2 password hashing + a signed session
cookie, all stdlib; users live in the Lakebase `app_users` table). This is
deliberately separate from Databricks workspace identity — it models how a real
embedded SaaS authenticates its own users before the backend ever touches
Databricks. The demo seeds two accounts; see the README.

### 2. App (FastAPI + React)

The orchestration layer. Per request it:
- **Resolves the tenant** for the signed-in user.
- **Looks up the tenant's SP** and **mints an OAuth M2M token** as that SP
  (`server/primitives/identity.py`, cached and refreshed ahead of expiry).
- **Calls Genie** over REST (`/api/2.0/genie/...`) or the Managed MCP server
  (`/api/2.0/mcp/genie/{space}`) — both as the tenant SP. Transport is selected
  by `MT_GENIE_TRANSPORT` (`rest` default | `mcp`).
- **Audits** the request to Lakebase.

The React frontend has two surfaces: the customer **product** (`/`, `/ask`,
`/dashboards`) and the operator **console** (`/console`).

### 3. Lakebase (PostgreSQL) — operational store

Auto-scaling Postgres for the app's own data (`server/lib/repository/`):
- tenant registry — tenant_id, SP application id, status, optional per-tenant
  `genie_space_id`
- SP credentials — encrypted SP client_id/secret (AES-256-GCM, key from
  `AES_KEY_BASE64`)
- audit log — every query with tenant, question, status, latency
- `app_users` — the app's own end-user accounts

### 4. Unity Catalog (Delta) — governed data store

The analytics data lives in UC, not Lakebase:
- `bookings`, `customers` — base Delta tables with the tenant row filter applied
- `sp_tenant_mapping` — maps SP application_id → tenant_id, joined by the filter

This split keeps the app's operational data fully separate from the governed
analytics data. See [`sql/setup.sql`](../sql/setup.sql) and
[`sql/lakebase/`](../sql/lakebase/).

### 5. Databricks OIDC token endpoint

The app exchanges each tenant SP's credentials for an OAuth access token:

```
POST {workspace_url}/oidc/v1/token
Authorization: Basic base64(client_id:client_secret)
Content-Type: application/x-www-form-urlencoded

grant_type=client_credentials&scope=all-apis
```

There is **no** `custom_claim`. Identity *is* the SP — `session_user()` in the
warehouse resolves to the tenant SP, and that is what the row filter keys on.

### 6. Genie + Unity Catalog row filter

A Genie Space (serverless SQL warehouse) is granted CAN_RUN to each tenant SP.
The row filter is the enforcement layer:

```sql
CREATE FUNCTION {catalog}.{schema}.tenant_row_filter(tenant_id STRING)
RETURN EXISTS (
  SELECT 1 FROM {catalog}.{schema}.sp_tenant_mapping m
  WHERE m.sp_app_id = session_user()
    AND m.tenant_id = tenant_id
    AND m.active
) OR is_account_group_member('{admin_group}');

ALTER TABLE {catalog}.{schema}.bookings
SET ROW FILTER {catalog}.{schema}.tenant_row_filter ON (tenant_id);
```

Row filters (rather than per-tenant views) let Genie see the original table
names — better natural-language understanding — while UC silently trims rows.
Admins in the configured group bypass the filter for verification.

## Data flow — single request

```
1. End user (signed in) asks: POST /api/genie/ask { "question": "..." }
2. App resolves the tenant → looks up its Service Principal
3. App mints/loads an OAuth M2M token as that tenant SP (cache-aware)
4. App calls Genie as the tenant SP:
     REST: POST /api/2.0/genie/spaces/{id}/start-conversation
     MCP:  the managed Genie MCP server for the space
5. Genie generates SQL; the serverless warehouse executes it
6. Unity Catalog applies tenant_row_filter: session_user() = tenant SP
     → only that tenant's rows are returned
7. App returns results and writes the audit log
```

The six steps are visible live in the product's **Request Flow Inspector**.

## Diagram

The live architecture diagram renders in the operator console's **Architecture**
view (`/console/architecture`). The Mermaid source is in
[web/src/pages/ArchitecturePage.tsx](../web/src/pages/ArchitecturePage.tsx)
(search for `ARCH_DIAGRAM`).

## Optional: external front door (edge gateway)

For embedding the app to end users who should never see Databricks SSO, the
`edge/` package is a Firefly-style reverse proxy: it owns your public origin,
keeps the app session cookie, and injects an *edge* Service Principal token to
clear the Databricks Apps OAuth proxy. The edge SP is a minimal "doorman" — it
only clears the proxy; the per-tenant data SPs are unchanged. See
[`edge-gateway.md`](edge-gateway.md).
