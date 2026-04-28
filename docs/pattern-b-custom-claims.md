# Pattern B: Shared SP + Custom Claims (Recommended)

## Overview

A single Service Principal serves all clients. Per-client data isolation is achieved by embedding a `custom_claim` (the tenant identifier) in each OAuth token. Unity Catalog reads the claim at query time via `current_oauth_custom_identity_claims()` to enforce row-level security.

**Use this pattern when:**
- You have hundreds to millions of clients
- You want O(1) SP management (no per-client Databricks provisioning)
- Custom claims are supported on the Genie surface (verify current status)

## Architecture

```
Client A ──► Proxy ──► SP token (custom_claim=acme)   ──► Genie ──► UC: claim = "acme"
Client B ──► Proxy ──► SP token (custom_claim=globex)  ──► Genie ──► UC: claim = "globex"
Client C ──► Proxy ──► SP token (custom_claim=initech) ──► Genie ──► UC: claim = "initech"
                ↑
          Same SP credentials for all,
          only the custom_claim differs
```

## How Custom Claims Work

### Token Exchange

The proxy requests a token from the Databricks OIDC endpoint with an additional `custom_claim` parameter:

```
POST {workspace_url}/oidc/v1/token
Authorization: Basic {sp_client_id}:{sp_client_secret}
Content-Type: application/x-www-form-urlencoded

grant_type=client_credentials&scope=all-apis&custom_claim=acme-corp
```

The returned JWT contains the custom claim. When this token is used to execute SQL, `current_oauth_custom_identity_claims()` returns `"acme-corp"`.

### Python Token Minter

```python
import requests
import threading
import time

class TokenMinter:
    """Thread-safe token minter with per-tenant caching and auto-refresh."""

    def __init__(self, workspace_url: str, client_id: str, client_secret: str):
        self.workspace_url = workspace_url.rstrip("/")
        self.client_id = client_id
        self.client_secret = client_secret
        self._cache = {}  # tenant_id -> (token, expiry_timestamp)
        self._lock = threading.Lock()

    def get_token(self, tenant_id: str) -> str:
        """Get a valid token for a tenant, refreshing if needed."""
        with self._lock:
            if tenant_id in self._cache:
                token, expiry = self._cache[tenant_id]
                if time.time() < expiry - 300:  # Refresh 5 min before expiry
                    return token

        # Fetch new token
        response = requests.post(
            f"{self.workspace_url}/oidc/v1/token",
            data={
                "grant_type": "client_credentials",
                "scope": "all-apis",
                "custom_claim": tenant_id,
            },
            auth=(self.client_id, self.client_secret),
        )
        response.raise_for_status()
        data = response.json()

        token = data["access_token"]
        expires_in = data.get("expires_in", 3600)

        with self._lock:
            self._cache[tenant_id] = (token, time.time() + expires_in)

        return token
```

## Row-Level Security

### Option 1: Row Filters (Preferred)

Row filters are transparent to Genie — it sees the original table name, which improves NL-to-SQL quality.

```sql
-- Row filter function
CREATE OR REPLACE FUNCTION main.analytics.tenant_filter(tenant_id STRING)
RETURN IF(
    tenant_id = current_oauth_custom_identity_claims()
    OR is_account_group_member('admin'),
    true, false
);

-- Apply to table
ALTER TABLE main.analytics.orders
SET ROW FILTER main.analytics.tenant_filter ON (tenant_id);

-- Apply to all tables with tenant_id column
ALTER TABLE main.analytics.customers
SET ROW FILTER main.analytics.tenant_filter ON (tenant_id);

ALTER TABLE main.analytics.products
SET ROW FILTER main.analytics.tenant_filter ON (tenant_id);

ALTER TABLE main.analytics.transactions
SET ROW FILTER main.analytics.tenant_filter ON (tenant_id);
```

### Option 2: Dynamic Views

```sql
CREATE OR REPLACE VIEW main.analytics.orders_v AS
SELECT * FROM main.analytics.orders
WHERE tenant_id = current_oauth_custom_identity_claims()
   OR is_account_group_member('admin');
```

### Option 3: Column Masking (for sensitive fields)

```sql
-- Mask columns that shouldn't be visible across tenants
CREATE FUNCTION main.analytics.mask_email(email STRING, tenant_id STRING)
RETURN IF(
    tenant_id = current_oauth_custom_identity_claims(),
    email,
    '***@***.com'
);

ALTER TABLE main.analytics.customers
SET COLUMN MASK main.analytics.mask_email ON (email) USING COLUMNS (tenant_id);
```

## Service Principal Setup

Only **one SP** is needed for all clients:

```python
from databricks.sdk import AccountClient, WorkspaceClient
from databricks.sdk.service import iam, catalog

a = AccountClient()
w = WorkspaceClient()

# 1. Create single SP
sp = a.service_principals.create(
    display_name="genie-shared-sp",
    active=True
)

# 2. Generate OAuth secret
secret = a.service_principal_secrets.create(
    service_principal_id=sp.id
)
# STORE: secret.client_id, secret.secret

# 3. Assign to workspace
a.workspace_assignment.update(
    workspace_id=WORKSPACE_ID,
    principal_id=int(sp.id),
    permissions=[iam.WorkspacePermission.USER]
)

# 4. Grant UC permissions
for grant in [
    ("catalog", "main", ["USE_CATALOG"]),
    ("schema", "main.analytics", ["USE_SCHEMA", "SELECT"]),
]:
    w.grants.update(
        securable_type=grant[0],
        full_name=grant[1],
        changes=[
            catalog.PermissionsChange(
                add=grant[2],
                principal=sp.application_id
            )
        ]
    )

# 5. Grant Genie Space access
# (via UI or API — add the SP with CAN_RUN on the space)
```

## Supported Surfaces

As of the Identity Claim User Guide, `current_oauth_custom_identity_claims()` is supported for:

| Surface | Supported |
|---------|-----------|
| JDBC to SQL Warehouse | Yes |
| SQL Execution API (`/api/2.0/sql/statements`) | Yes |
| Interactive clusters (JDBC) | Yes |
| Genie Conversation API | **Verify** — active escalation tracking this |
| SQL Editor UI | No (no OAuth) |
| Jobs / DLT | No (non-interactive) |

### Verification Step

Before committing to this pattern, verify custom claims flow through Genie:

```python
# 1. Get token with custom claim
token = minter.get_token("test-tenant")

# 2. Start Genie conversation
resp = requests.post(
    f"{WORKSPACE_URL}/api/2.0/genie/spaces/{SPACE_ID}/start-conversation",
    headers={"Authorization": f"Bearer {token}"},
    json={"content": "SELECT current_oauth_custom_identity_claims()"}
)

# 3. Check if the claim is returned correctly
# If it returns "test-tenant", custom claims work through Genie
```

## Client Onboarding

With this pattern, onboarding is purely in **your** system — no Databricks operations:

```sql
-- Lakebase: add new client
INSERT INTO client_registry (tenant_id, display_name, api_key_hash, tier)
VALUES ('new-client', 'New Client Corp', '<bcrypt-hash>', 'standard');
```

No SP creation, no UC grants, no group management. The tenant_id just needs to match the `tenant_id` column in your data tables.

## Advantages Over Pattern A

| Aspect | Pattern A (SP-per-Client) | Pattern B (Custom Claims) |
|--------|---------------------------|---------------------------|
| Onboarding | Create SP, secret, workspace assignment, group membership | Insert row in Lakebase |
| Offboarding | Deactivate/delete SP, clean up groups | Set `active=false` in registry |
| Secret rotation | Per-SP (thousands of rotations) | Single SP rotation |
| UC grants | Group-based (manageable) | Single SP grant |
| Blast radius if SP compromised | One client's data | All clients' data (mitigate with proxy security) |
| Scaling | O(N) operational overhead | O(1) |

## Security Considerations

Since a single SP has access to all tenants' data (the row filter is the isolation boundary):

1. **Never expose SP credentials** — they live only in the proxy's encrypted store
2. **Validate tenant_id** — the proxy must ensure the authenticated client maps to exactly one tenant_id
3. **Audit aggressively** — log every token exchange with the tenant_id claim
4. **Defense in depth** — the proxy authenticates the client AND UC enforces the claim; compromising one layer alone isn't sufficient
5. **Monitor for claim abuse** — alert if a single client IP requests tokens with different tenant_ids
