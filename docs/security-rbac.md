# Security & RBAC

## Authentication Layers

The architecture uses a **two-layer authentication model** (following the Firefly SSO-SPN pattern):

### Layer 1: Client Authentication (Your System)

Clients authenticate against your proxy — never against Databricks.

| Method | Use Case | Implementation |
|--------|----------|----------------|
| API Keys | Server-to-server, backend clients | Hash with bcrypt, store in Lakebase |
| OAuth 2.0 | Browser-based or mobile clients | Use your IdP (Okta, Auth0, Azure AD) |
| mTLS | High-security / regulated clients | Client certificates for mutual auth |

```python
# API key validation example
from passlib.hash import bcrypt

async def verify_api_key(api_key: str) -> dict:
    """Validate API key and return client record."""
    # Query Lakebase for matching hash
    client = await db.fetch_one(
        "SELECT * FROM client_registry WHERE api_key_hash = $1 AND active = true",
        bcrypt.hash(api_key)
    )
    if not client:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return client
```

### Layer 2: Databricks Authentication (Service Principal)

The proxy authenticates to Databricks using SP OAuth credentials. Clients never see these credentials.

**Pattern B (Custom Claims):** Single SP, `custom_claim` in token embeds tenant identity.
**Pattern A (SP-per-Client):** Per-client SP, `session_user()` identifies the tenant.

## Two-Tier SP Design

Following the Firefly security model, maintain two SPs with different privilege levels:

### Admin SP (Environment Variables Only)

Used exclusively by provisioning scripts and admin operations:
- Create/delete catalogs and schemas
- Manage UC grants
- SCIM group management
- Schema/volume operations

**Never stored in a database.** Lives only in environment variables or a secrets manager.

### Data SP (Database Storage, Encrypted)

Used for client-facing data access:
- Execute SQL queries via Genie
- Browse catalogs and schemas scoped by row filters
- Cannot create catalogs, modify permissions, or access other tenants' data (enforced by UC)

**Stored encrypted** (AES-256-GCM) in Lakebase with per-environment encryption keys.

## Encryption

### In Transit

All network paths use TLS 1.3:
- Client → Proxy App
- Proxy App → Lakebase (PostgreSQL)
- Proxy App → Databricks OIDC endpoint
- Proxy App → Genie API

### At Rest

SP credentials and tokens encrypted in Lakebase using AES-256-GCM:

```python
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import os, base64

class CredentialEncryptor:
    def __init__(self, key: bytes):
        """key should be 32 bytes (256-bit) from env/KMS."""
        self.aesgcm = AESGCM(key)

    def encrypt(self, plaintext: str) -> str:
        nonce = os.urandom(12)  # 96-bit IV
        ct = self.aesgcm.encrypt(nonce, plaintext.encode(), None)
        return base64.b64encode(nonce + ct).decode()

    def decrypt(self, ciphertext: str) -> str:
        data = base64.b64decode(ciphertext)
        nonce, ct = data[:12], data[12:]
        return self.aesgcm.decrypt(nonce, ct, None).decode()
```

### Key Management

- Store encryption keys in a secrets manager (AWS KMS, Azure Key Vault, HashiCorp Vault)
- Rotate keys quarterly
- Use separate keys per environment (dev/staging/prod)
- Never commit keys to code

## Multi-Tenant Isolation (4 Layers)

Defense in depth — any single layer compromise does not expose other tenants' data:

| Layer | Mechanism | What It Prevents |
|-------|-----------|------------------|
| **1. Client Auth** | API key/OAuth validation in proxy | Unauthenticated access |
| **2. Tenant Resolution** | Proxy maps client → tenant_id (immutable) | Tenant spoofing |
| **3. Token Claims** | `custom_claim=<tenant_id>` embedded in JWT | Cross-tenant token reuse |
| **4. Unity Catalog RLS** | `current_oauth_custom_identity_claims()` in row filters | Data leakage even if app layer is compromised |

## RBAC Model

### Application-Level Roles

| Role | Permissions | Use Case |
|------|-------------|----------|
| **Platform Admin** | Manage clients, view all data, configure Genie spaces | Your ops team |
| **Client Admin** | Manage users within their tenant, view usage stats | Client's admin |
| **Client User** | Query Genie, view results | End users |

### Unity Catalog Permissions

For the shared SP (Pattern B):

```sql
-- Minimum required grants
GRANT USE_CATALOG ON CATALOG main TO `<sp-application-id>`;
GRANT USE_SCHEMA ON SCHEMA main.analytics TO `<sp-application-id>`;
GRANT SELECT ON SCHEMA main.analytics TO `<sp-application-id>`;

-- Row filters handle per-tenant isolation — the SP sees all rows
-- but UC filters based on the JWT claim
```

For the group (Pattern A):

```sql
GRANT USE_CATALOG ON CATALOG main TO genie_clients;
GRANT USE_SCHEMA ON SCHEMA main.analytics TO genie_clients;
GRANT SELECT ON SCHEMA main.analytics TO genie_clients;
```

## Audit Trail (3 Levels)

### Level 1: Application Audit (Proxy)

```json
{
    "timestamp": "2026-03-25T14:30:00Z",
    "tenant_id": "acme-corp",
    "client_ip": "203.0.113.42",
    "question": "What were top 10 orders last month?",
    "genie_space_id": "abc123",
    "status": "completed",
    "latency_ms": 3200,
    "rows_returned": 10
}
```

### Level 2: Databricks API Audit

Logged automatically in `system.access.audit`:
- SP identity making the API call
- Genie space accessed
- Timestamp and duration

### Level 3: Unity Catalog Data Access Audit

Logged in `system.access.audit`:
- Tables/views accessed
- SQL executed
- Row filter evaluation
- Data objects touched

### Correlating Across Levels

```sql
-- Find all data access by a specific tenant
SELECT
    a.event_time,
    a.service_name,
    a.action_name,
    a.request_params,
    a.response.status_code
FROM system.access.audit a
WHERE a.user_identity.email = '<sp-application-id>'
    -- Correlate with app-level logs using timestamp
    AND a.event_time BETWEEN '2026-03-25T14:29:00' AND '2026-03-25T14:31:00'
ORDER BY a.event_time;
```

## Security Checklist

- [ ] SP credentials encrypted at rest (AES-256-GCM)
- [ ] Encryption keys in secrets manager, not env files
- [ ] API keys hashed with bcrypt, never stored plaintext
- [ ] TLS 1.3 on all network paths
- [ ] Row filters applied to all tables with tenant data
- [ ] Admin SP separated from data SP
- [ ] Rate limiting per client in proxy
- [ ] Audit logging at all three levels
- [ ] Token cache with proactive refresh (not on-demand expiry)
- [ ] Client offboarding tested (deactivate + verify no data access)
- [ ] Quarterly key rotation procedure documented
- [ ] Penetration test: verify cross-tenant isolation
