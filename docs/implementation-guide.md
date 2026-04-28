# Implementation Guide

Step-by-step setup for the multi-tenant Genie architecture.

## Prerequisites

- Databricks workspace with Unity Catalog enabled
- Account admin access (for SP creation)
- Serverless SQL warehouse
- Lakebase (or external PostgreSQL) for client registry
- Python 3.11+ with `databricks-sdk`, `fastapi`, `cryptography`

## Phase 1: Databricks Setup

### 1.1 Create the Service Principal

```python
from databricks.sdk import AccountClient, WorkspaceClient
from databricks.sdk.service import iam, catalog

a = AccountClient(
    host="https://accounts.cloud.databricks.com",
    account_id="<ACCOUNT_ID>",
)

# Create shared SP for data access
sp = a.service_principals.create(
    display_name="genie-multi-tenant-sp",
    active=True
)

# Generate OAuth secret — STORE IMMEDIATELY
secret = a.service_principal_secrets.create(
    service_principal_id=sp.id
)

print(f"SP ID: {sp.id}")
print(f"Application ID: {sp.application_id}")
print(f"Client ID: {secret.client_id}")
print(f"Client Secret: {secret.secret}")  # Only shown once!
```

### 1.2 Assign SP to Workspace

```python
WORKSPACE_ID = 123456789  # From account console or URL

a.workspace_assignment.update(
    workspace_id=WORKSPACE_ID,
    principal_id=int(sp.id),
    permissions=[iam.WorkspacePermission.USER]
)
```

### 1.3 Grant Unity Catalog Permissions

```python
w = WorkspaceClient()

CATALOG = "main"
SCHEMA = "analytics"

# Catalog access
w.grants.update(
    securable_type="catalog",
    full_name=CATALOG,
    changes=[catalog.PermissionsChange(
        add=["USE_CATALOG"],
        principal=sp.application_id
    )]
)

# Schema access
w.grants.update(
    securable_type="schema",
    full_name=f"{CATALOG}.{SCHEMA}",
    changes=[catalog.PermissionsChange(
        add=["USE_SCHEMA", "SELECT"],
        principal=sp.application_id
    )]
)

# SQL Warehouse access
# Grant CAN_USE on the warehouse via workspace permissions API
w.api_client.do(
    method="PATCH",
    path=f"/api/2.0/permissions/sql/warehouses/{WAREHOUSE_ID}",
    body={
        "access_control_list": [{
            "service_principal_name": sp.application_id,
            "all_permissions": [{"permission_level": "CAN_USE"}]
        }]
    }
)
```

### 1.4 Set Up Row Filters

```sql
-- Create the filter function (one function, reuse across all tables)
CREATE OR REPLACE FUNCTION main.analytics.tenant_filter(tenant_id STRING)
RETURN IF(
    tenant_id = current_oauth_custom_identity_claims()
    OR is_account_group_member('admin'),
    true, false
);

-- Apply to every table that contains tenant data
ALTER TABLE main.analytics.orders
SET ROW FILTER main.analytics.tenant_filter ON (tenant_id);

ALTER TABLE main.analytics.customers
SET ROW FILTER main.analytics.tenant_filter ON (tenant_id);

ALTER TABLE main.analytics.products
SET ROW FILTER main.analytics.tenant_filter ON (tenant_id);

-- Verify: without a custom claim, queries should return 0 rows
-- With a valid claim, only that tenant's rows are returned
```

### 1.5 Configure Genie Space

1. Create a Genie Space in the workspace UI
2. Point it at the tables with row filters applied
3. Add the shared SP with **CAN_RUN** permission
4. Configure a serverless SQL warehouse
5. Add instructions and sample questions for the analytics domain
6. Note the Space ID from the URL

## Phase 2: Lakebase Setup

### 2.1 Create Lakebase Database

Use the Databricks CLI or UI to create a Lakebase instance, then connect and create tables:

```sql
-- Client Registry
CREATE TABLE client_registry (
    id SERIAL PRIMARY KEY,
    tenant_id VARCHAR(255) UNIQUE NOT NULL,
    display_name VARCHAR(255) NOT NULL,
    api_key_hash VARCHAR(255) UNIQUE NOT NULL,
    tier VARCHAR(50) DEFAULT 'standard',
    rate_limit_per_min INTEGER DEFAULT 5,
    active BOOLEAN DEFAULT true,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Audit Log
CREATE TABLE audit_log (
    id BIGSERIAL PRIMARY KEY,
    tenant_id VARCHAR(255) NOT NULL,
    client_ip INET,
    question TEXT NOT NULL,
    genie_space_id VARCHAR(255),
    genie_conversation_id VARCHAR(255),
    status VARCHAR(50) NOT NULL,
    latency_ms INTEGER,
    rows_returned INTEGER,
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- SP Credentials (encrypted)
CREATE TABLE sp_credentials (
    id SERIAL PRIMARY KEY,
    label VARCHAR(255) UNIQUE NOT NULL,
    client_id_encrypted TEXT NOT NULL,
    client_secret_encrypted TEXT NOT NULL,
    workspace_url VARCHAR(500) NOT NULL,
    is_admin BOOLEAN DEFAULT false,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes
CREATE INDEX idx_client_api_key ON client_registry(api_key_hash);
CREATE INDEX idx_client_tenant ON client_registry(tenant_id);
CREATE INDEX idx_audit_tenant_time ON audit_log(tenant_id, created_at DESC);
CREATE INDEX idx_audit_created ON audit_log(created_at DESC);

-- Partitioning for audit log (if high volume)
-- Consider partitioning by month for audit_log
```

### 2.2 Seed Initial Clients

```python
import bcrypt
import secrets

def create_client(tenant_id: str, display_name: str) -> tuple[str, str]:
    """Create a client and return (tenant_id, api_key)."""
    api_key = secrets.token_urlsafe(32)
    api_key_hash = bcrypt.hashpw(api_key.encode(), bcrypt.gensalt()).decode()

    # Insert into Lakebase
    db.execute(
        """INSERT INTO client_registry (tenant_id, display_name, api_key_hash)
           VALUES (%s, %s, %s)""",
        (tenant_id, display_name, api_key_hash)
    )

    return tenant_id, api_key  # Return API key to give to client
```

## Phase 3: Proxy App

### 3.1 FastAPI Application

See `src/proxy/` for the full implementation. Core structure:

```
src/proxy/
├── main.py              # FastAPI app, routes
├── auth.py              # API key validation
├── token_minter.py      # Databricks OAuth token management
├── genie_client.py      # Genie Conversation API client
├── db.py                # Lakebase connection
├── encryption.py        # AES-256-GCM credential encryption
├── config.py            # Environment configuration
└── requirements.txt
```

### 3.2 Core Configuration

```python
# config.py
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Proxy
    host: str = "0.0.0.0"
    port: int = 8000

    # Databricks
    databricks_workspace_url: str
    genie_space_id: str

    # Encryption
    encryption_key: str  # 32-byte hex-encoded key

    # Lakebase
    database_url: str  # postgresql://...

    class Config:
        env_file = ".env"
```

### 3.3 Deployment Options

| Option | Pros | Cons |
|--------|------|------|
| **Databricks App** | Built-in OAuth, same network, managed | Less control over infra |
| **AWS ECS / Azure Container Apps** | Full control, auto-scaling | Network setup, more ops |
| **Kubernetes** | Maximum flexibility | Complexity |

## Phase 4: Verification

### 4.1 Verify Custom Claims

```python
# Test that custom claims work through to UC
token = minter.get_token("test-tenant")

response = requests.post(
    f"{WORKSPACE_URL}/api/2.0/sql/statements",
    headers={"Authorization": f"Bearer {token}"},
    json={
        "warehouse_id": WAREHOUSE_ID,
        "statement": "SELECT current_oauth_custom_identity_claims() AS claim",
        "wait_timeout": "30s"
    }
)

result = response.json()
assert result["result"]["data_array"][0][0] == "test-tenant"
```

### 4.2 Verify Row Filters

```python
# Insert test data for two tenants
# Query as tenant-a: should only see tenant-a rows
# Query as tenant-b: should only see tenant-b rows
# Query without claim: should see 0 rows (or error)
```

### 4.3 Verify Genie End-to-End

```python
# Full flow: API key → tenant resolution → token with claim → Genie → filtered results
response = requests.post(
    "http://localhost:8000/api/v1/ask",
    headers={"X-API-Key": "<client-api-key>"},
    json={"question": "How many orders do I have?"}
)

# Verify the count matches only that tenant's data
```

## Phase 5: Monitoring & Operations

### 5.1 Dashboards

- Client usage: queries/day per tenant, latency percentiles
- Error rates: Genie failures, auth failures, timeout rates
- Token cache hit rate
- Genie throughput vs. rate limits

### 5.2 Alerts

- Auth failure spike (possible key compromise)
- Genie error rate > 5%
- Latency p99 > 30s
- Token refresh failures (SP secret may be expiring)

### 5.3 Client Onboarding Runbook

1. `INSERT INTO client_registry` with tenant_id and API key hash
2. Ensure tenant's data exists in base tables with matching `tenant_id`
3. Provide client with: API key, endpoint URL, API documentation
4. Verify with test query
