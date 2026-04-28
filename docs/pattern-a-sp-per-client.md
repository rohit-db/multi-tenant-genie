# Pattern A: SP-per-Client

## Overview

Each client gets its own Databricks Service Principal. Row-level security is enforced via dynamic views that filter on `session_user()`, which returns the SP's application ID.

**Use this pattern when:**
- Custom claims (`current_oauth_custom_identity_claims()`) are not yet supported on the Genie surface
- You need per-client compute attribution / chargeback
- You have hundreds (not thousands) of clients and can manage the SP lifecycle

## Architecture

```
Client A ──► Proxy ──► SP-A token ──► Genie ──► UC: session_user() = SP-A app_id
Client B ──► Proxy ──► SP-B token ──► Genie ──► UC: session_user() = SP-B app_id
Client C ──► Proxy ──► SP-C token ──► Genie ──► UC: session_user() = SP-C app_id
```

## Service Principal Lifecycle

### Provisioning (Account-Level)

```python
from databricks.sdk import AccountClient
from databricks.sdk.service import iam

a = AccountClient(
    host="https://accounts.cloud.databricks.com",
    account_id="<account-id>",
)

def provision_client(account_client: AccountClient, tenant_id: str,
                     workspace_id: int, group_id: str) -> dict:
    """Create SP, generate secret, assign to workspace and group."""

    # 1. Create service principal
    sp = account_client.service_principals.create(
        display_name=f"genie-{tenant_id}",
        active=True
    )

    # 2. Generate OAuth secret
    secret = account_client.service_principal_secrets.create(
        service_principal_id=sp.id
    )

    # 3. Add to workspace
    account_client.workspace_assignment.update(
        workspace_id=workspace_id,
        principal_id=int(sp.id),
        permissions=[iam.WorkspacePermission.USER]
    )

    # 4. Add to group (inherits UC permissions)
    account_client.groups.patch(
        id=group_id,
        operations=[
            iam.Patch(
                op=iam.PatchOp.ADD,
                value={"members": [{"value": sp.id}]}
            )
        ],
        schemas=[iam.PatchSchema.URN_IETF_PARAMS_SCIM_API_MESSAGES_2_0_PATCH_OP]
    )

    # STORE THESE SECURELY — only time you see the secret
    return {
        "tenant_id": tenant_id,
        "sp_id": sp.id,
        "application_id": sp.application_id,
        "client_id": secret.client_id,
        "client_secret": secret.secret,
    }
```

### Bulk Provisioning

```python
import time

clients = ["acme-corp", "globex", "initech", ...]  # thousands
WORKSPACE_ID = 123456789

# Create a group first — UC grants go to the group
genie_group = a.groups.create(display_name="genie-clients")

credentials = []
for i, tenant_id in enumerate(clients):
    creds = provision_client(a, tenant_id, WORKSPACE_ID, genie_group.id)
    credentials.append(creds)

    # Rate limiting: ~50/min is safe for account API
    if i % 50 == 49:
        time.sleep(60)

# Store credentials in Lakebase (encrypted) — see implementation-guide.md
```

### Offboarding

```python
def offboard_client(account_client: AccountClient, sp_id: str):
    """Deactivate SP (soft delete) or hard delete."""
    # Soft delete — preserves audit trail
    account_client.service_principals.patch(
        id=sp_id,
        operations=[
            iam.Patch(
                op=iam.PatchOp.REPLACE,
                path="active",
                value="false"
            )
        ],
        schemas=[iam.PatchSchema.URN_IETF_PARAMS_SCIM_API_MESSAGES_2_0_PATCH_OP]
    )

    # Or hard delete
    # account_client.service_principals.delete(id=sp_id)
```

## Row-Level Security

### SP-to-Tenant Mapping Table

```sql
CREATE TABLE main.analytics.sp_tenant_mapping (
    sp_application_id STRING NOT NULL,
    tenant_id STRING NOT NULL
);

-- Populate during provisioning
INSERT INTO main.analytics.sp_tenant_mapping VALUES
    ('<sp-a-app-id>', 'acme-corp'),
    ('<sp-b-app-id>', 'globex'),
    ('<sp-c-app-id>', 'initech');
```

### Dynamic View

```sql
CREATE OR REPLACE VIEW main.analytics.orders_secure AS
SELECT o.*
FROM main.analytics.orders o
JOIN main.analytics.sp_tenant_mapping m
    ON o.tenant_id = m.tenant_id
WHERE m.sp_application_id = session_user()
   OR is_account_group_member('admin');
```

### Row Filter (Alternative)

```sql
CREATE FUNCTION main.analytics.filter_by_sp_tenant(tenant_id STRING)
RETURN IF(
    EXISTS (
        SELECT 1 FROM main.analytics.sp_tenant_mapping
        WHERE sp_application_id = session_user()
        AND tenant_id = filter_by_sp_tenant.tenant_id
    )
    OR is_account_group_member('admin'),
    true, false
);

ALTER TABLE main.analytics.orders
SET ROW FILTER main.analytics.filter_by_sp_tenant ON (tenant_id);
```

## UC Permissions (Group-Based)

```python
from databricks.sdk import WorkspaceClient
from databricks.sdk.service import catalog

w = WorkspaceClient()

# Grant to the group — all SPs in the group inherit
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
                principal="genie-clients"  # group name
            )
        ]
    )
```

## Operational Considerations

| Concern | Impact | Mitigation |
|---------|--------|------------|
| SP count | Account may have limits on SP count | Check with Databricks — some accounts have soft limits |
| Secret rotation | Each SP has max 5 secrets, 730-day expiry | Automate: create new secret, update registry, delete old |
| Provisioning latency | Account API rate limits (~50/min) | Batch provisioning during onboarding, not real-time |
| Cost attribution | Each SP's queries are separately auditable | Query `system.access.audit` by SP identity |
| Mapping table maintenance | Must stay in sync with SP provisioning | Automate: provisioning script updates both Databricks and the mapping table |

## When to Use This Pattern

- Custom claims not yet supported on Genie surface
- Per-client compute isolation needed (dedicated warehouses per SP)
- Client count is manageable (hundreds, not tens of thousands)
- Need per-SP cost attribution via system tables
