# Architecture Overview

## System Design

The architecture follows the **SSO-SPN (Single Sign-On to Service Principal)** pattern from the [Firefly Analytics](https://www.firefly-analytics.com/) reference implementation, adapted for external API clients querying Databricks Genie.

### Core Principle

External clients never interact with Databricks directly. A proxy application authenticates clients, maps them to the correct data scope, and proxies requests to the Genie API using a service principal with embedded identity claims. Unity Catalog enforces row-level security at query time.

## High-Level Flow

```
┌─────────────────────────────────────────────────────────┐
│                    TENANT TIER                           │
│  Tenant A    Tenant B    Tenant C    ...    Tenant N    │
│  (API key)   (API key)   (API key)          (API key)   │
└─────────┬───────┬───────┬───────────────────┬───────────┘
          │       │       │                   │
          ▼       ▼       ▼                   ▼
┌─────────────────────────────────────────────────────────┐
│              PROXY / GATEWAY APP                         │
│  (FastAPI, Next.js, or Databricks App)                  │
│                                                          │
│  1. Authenticate tenant (API key / OAuth)                │
│  2. Look up tenant → tenant_id in Lakebase registry      │
│  3. Request SP token WITH custom_claim=<tenant_id>       │
│  4. Call Genie Conversation API with claims-bearing token │
│  5. Return results to tenant                             │
│  6. Write audit log                                      │
└──────┬──────────┬───────────────────┬───────────────────┘
       │          │                   │
       ▼          ▼                   ▼
┌──────────┐ ┌────────────┐ ┌─────────────────────────────┐
│ Lakebase │ │ Databricks │ │     DATABRICKS WORKSPACE     │
│ (Postgres)│ │   OIDC     │ │                              │
│          │ │  Endpoint   │ │  Genie Space                 │
│ • Tenant │ │             │ │    ↓                         │
│   Registry│ │ POST /token│ │  Serverless SQL Warehouse    │
│ • SP Creds│ │ + custom   │ │    ↓                         │
│   (AES256)│ │   _claim   │ │  Unity Catalog               │
│ • Audit  │ │             │ │  ┌─────────────────────┐     │
│   Logs   │ │             │ │  │ Dynamic View (RLS)  │     │
│ • Token  │ │             │ │  │ WHERE tenant_id =   │     │
│   Cache  │ │             │ │  │ current_oauth_      │     │
└──────────┘ └────────────┘ │  │ custom_identity_    │     │
                             │  │ claims()            │     │
                             │  └─────────────────────┘     │
                             └──────────────────────────────┘
```

## Components

### 1. Tenant Tier

External tenants (thousands) that consume analytics via API. Each tenant:
- Authenticates with an API key or OAuth token issued by **your** identity system (not Databricks)
- Sends natural language questions to your proxy endpoint
- Receives structured answers (text, SQL, data rows)
- Has no knowledge of Databricks, service principals, or Unity Catalog

### 2. Proxy / Gateway App

The central orchestration layer. Responsibilities:
- **Tenant authentication** — validate API keys against Lakebase registry
- **Tenant resolution** — map authenticated tenant to a `tenant_id`
- **Token exchange** — request a Databricks OAuth token for the shared SP with `custom_claim=<tenant_id>`
- **Token caching** — cache tokens per tenant (1hr lifetime, refresh at 55min)
- **Genie proxying** — forward questions to the Genie Conversation API, poll for completion, return results
- **Rate limiting** — enforce per-tenant and global rate limits (Genie: 5 questions/min/workspace)
- **Audit logging** — record every request with tenant identity, question, latency, status

Technology options:
- **FastAPI** (Python) — lightweight, async, good Databricks SDK integration
- **Next.js** (TypeScript) — if you want a UI as well (Firefly pattern)
- **Databricks App** — deployed on Databricks, automatic OAuth, simplified networking

### 3. Lakebase (PostgreSQL) — Metadata Store

Persistent storage for the proxy app. Lakebase auto-scales the underlying compute and is the single source of truth for proxy-operational data:
- `client_registry` — tenant_id, API key hash, tier, active status, optional `genie_space_id` override
- `sp_credentials` — encrypted SP client_id/secret (AES-256-GCM, key from `AES_KEY_BASE64`)
- `token_cache` — cached access tokens per tenant with expiry (sharable across proxy replicas)
- `audit_log` — every query with tenant, question, status, latency

### 3b. Unity Catalog Delta — Governed Data Store

The customer analytics data lives in UC, **not** in Lakebase:
- `bookings`, `customers` — base Delta tables with tenant row filters applied
- `sp_tenant_mapping` — maps SP application_id → tenant_id (joined in the UC row filter)

This split means the proxy's operational data (Lakebase) is fully isolated from the governed analytics data (UC Delta). Rotate or swap one without touching the other.

See [Implementation Guide](implementation-guide.md) for full schema.

> The live architecture diagram is rendered in the app's Architecture tab. The Mermaid source is in [web/src/pages/ArchitecturePage.tsx](../web/src/pages/ArchitecturePage.tsx) (search for `ARCH_DIAGRAM`).

### 4. Databricks OIDC Token Endpoint

The proxy exchanges SP credentials + a custom claim for an OAuth access token:

```
POST {workspace_url}/oidc/v1/token
Authorization: Basic {client_id}:{client_secret}
Content-Type: application/x-www-form-urlencoded

grant_type=client_credentials&scope=all-apis&custom_claim=<tenant_id>
```

The returned JWT contains the custom claim, which Unity Catalog reads at query time.

### 5. Genie Space

A configured Genie Space pointing at **secured views/filtered tables** (not base tables). The Space:
- Has the shared SP added with CAN_RUN permission
- Uses a serverless SQL warehouse
- Contains instructions and sample questions relevant to the analytics domain

### 6. Unity Catalog — Dynamic Views & Row Filters

The enforcement layer. Two approaches:

**Option A: Dynamic Views**
```sql
CREATE VIEW catalog.schema.orders_secure AS
SELECT * FROM catalog.schema.orders
WHERE tenant_id = current_oauth_custom_identity_claims()
   OR is_account_group_member('admin');
```

**Option B: Row Filters (preferred — no separate view needed)**
```sql
CREATE FUNCTION catalog.schema.filter_by_tenant(tenant_id STRING)
RETURN IF(
    tenant_id = current_oauth_custom_identity_claims()
    OR is_account_group_member('admin'),
    true, false
);

ALTER TABLE catalog.schema.orders
SET ROW FILTER catalog.schema.filter_by_tenant ON (tenant_id);
```

Row filters are preferred because Genie sees the original table name (better NL understanding) while UC silently applies the filter.

## Data Flow — Single Request

```
1. Tenant sends: POST /api/v1/ask { "question": "Top 10 orders last month" }
2. Proxy validates API key → resolves tenant_id = "acme-corp"
3. Proxy checks token cache for "acme-corp"
   - Cache miss: POST /oidc/v1/token with custom_claim=acme-corp → cache token
   - Cache hit: use cached token
4. Proxy calls: POST /api/2.0/genie/spaces/{id}/start-conversation
   - Header: Authorization: Bearer <token-with-acme-corp-claim>
   - Body: { "content": "Top 10 orders last month" }
5. Genie generates SQL: SELECT * FROM orders ORDER BY amount DESC LIMIT 10
6. SQL Warehouse executes query
7. Unity Catalog evaluates row filter: tenant_id = "acme-corp" (from JWT claim)
   → Only acme-corp's orders are returned
8. Proxy returns results to tenant
9. Proxy writes audit log: { tenant: "acme-corp", question: "...", latency: 3200ms }
```

## Diagram

The live architecture diagram is rendered in the app's Architecture tab. The Mermaid source is in [web/src/pages/ArchitecturePage.tsx](../web/src/pages/ArchitecturePage.tsx) (search for `ARCH_DIAGRAM`).
