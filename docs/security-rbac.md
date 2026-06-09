# Security & RBAC

This describes the security posture of the reference as implemented. See
[`architecture.md`](architecture.md) for the system view and
[`pattern.md`](pattern.md) for the isolation pattern.

## Authentication layers

A **two-layer model**: a user identity layer (your product) and a Databricks
access layer (Service Principals). They are independent.

### Layer 1: End-user authentication (the app's own login)

End users sign in to *your* product, never to Databricks. This repo ships a
self-contained app login (`server/lib/auth.py`):

- Passwords hashed with **PBKDF2-HMAC-SHA256** (Python stdlib `hashlib`), with a
  per-user salt.
- A **signed session cookie** (HMAC) carries the authenticated identity; the
  signing key is `MT_GENIE_SESSION_SECRET` (falls back to a stable value derived
  from `AES_KEY_BASE64`).
- Users live in the Lakebase `app_users` table (see
  `sql/lakebase/V002__app_users.sql`); roles are `user` and `operator`.

This login is intentionally demo-grade and pluggable. For production, swap it
for your own identity provider (OIDC SSO via Okta / Auth0 / Entra ID, mTLS for
machine clients, etc.) — the rest of the system is unchanged because the only
thing it needs from this layer is "which tenant is this request for?".

### Layer 2: Databricks authentication (Service Principals)

The app authenticates to Databricks using Service Principal OAuth M2M
credentials; end users never see them. This repo implements **Pattern A:
one Service Principal per tenant**. The SP's own identity (`session_user()`)
is what Unity Catalog keys the row filter on — there is no `custom_claim`.

> Pattern B (a single shared SP carrying a `custom_claim` per request) is a
> valid alternative but is **not** implemented here; Pattern A keeps identity in
> the platform rather than in a token the app constructs.

## Service Principals: roles & privilege separation

The reference uses SPs at three distinct privilege levels. Keeping them separate
is the point — a compromise of one does not grant the others' powers.

| SP / identity | Privilege | Where the secret lives |
|---|---|---|
| **Provisioning identity** | Create SPs, apply UC grants, set the row filter (admin ops in `scripts/`, `deploy.sh`) | Operator's CLI profile / secrets manager — **never** in the app DB |
| **Per-tenant data SP** | Run Genie queries; read only its own rows (UC enforces) | Lakebase `sp_credentials`, **AES-256-GCM encrypted at rest** |
| **Edge "doorman" SP** *(optional)* | Only CAN_USE on the Databricks App, to clear the Apps OAuth proxy at the front door (`edge/`) | `edge/.env` (gitignored) / secrets manager |

The per-tenant data SP cannot create catalogs, change permissions, or reach
another tenant's rows — Unity Catalog enforces that regardless of the app. The
edge SP is deliberately minimal: it admits traffic to the app and nothing more;
the per-tenant SPs do the data work. This edge-SP / data-SP split is this
project's adaptation for fronting a Databricks App — not a Firefly requirement.

## Encryption

### In transit

TLS on all network paths: user → app, app → Lakebase, app → Databricks OIDC,
app → Genie / Managed MCP, and (if used) client → edge → app.

### At rest

Per-tenant SP secrets are stored in Lakebase `sp_credentials`, AES-256-GCM
encrypted with a 32-byte key from `AES_KEY_BASE64`
(`server/lib/repository/credential.py`):

```python
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import os, base64

class CredentialEncryptor:
    def __init__(self, key: bytes):
        """key is 32 bytes (256-bit), base64-decoded from AES_KEY_BASE64."""
        self.aesgcm = AESGCM(key)

    def encrypt(self, plaintext: str) -> str:
        nonce = os.urandom(12)  # 96-bit nonce
        ct = self.aesgcm.encrypt(nonce, plaintext.encode(), None)
        return base64.b64encode(nonce + ct).decode()

    def decrypt(self, ciphertext: str) -> str:
        data = base64.b64decode(ciphertext)
        nonce, ct = data[:12], data[12:]
        return self.aesgcm.decrypt(nonce, ct, None).decode()
```

### Key management

- Bind `AES_KEY_BASE64` from a Databricks secret (the deploy binds a Secret
  resource); for production back it with a secrets manager (KMS / Key Vault /
  Vault).
- Use a separate key per environment (dev / staging / prod).
- Document a rotation cadence; never commit keys.

## Multi-tenant isolation (defense in depth)

Any single layer failing does not expose other tenants' data:

| Layer | Mechanism | What it prevents |
|---|---|---|
| **1. User auth** | App session login (PBKDF2 + signed cookie) | Unauthenticated access |
| **2. Tenant resolution** | App maps the signed-in user → tenant_id | Tenant spoofing |
| **3. Per-tenant SP** | Each tenant's queries run as its own SP token | Cross-tenant token reuse |
| **4. Unity Catalog row filter** | `tenant_row_filter` joins `sp_tenant_mapping` on `session_user()` | Data leakage even if the app layer is compromised |

Layer 4 is load-bearing: it runs in the warehouse, so even a bug in the app
cannot return another tenant's rows.

## RBAC model

### Application roles

| Role | Permissions | Use case |
|---|---|---|
| **operator** | The product **+** `/console`: SP lifecycle, audit, isolation verify | Your ops team |
| **user** | The product only (Home / Ask / Dashboards) | End users |

### Unity Catalog grants (Pattern A — per-tenant SP)

Onboarding grants each tenant SP the minimum it needs; the row filter does the
isolation:

```sql
GRANT USE CATALOG  ON CATALOG  <catalog>          TO `<sp-application-id>`;
GRANT USE SCHEMA   ON SCHEMA   <catalog>.<schema> TO `<sp-application-id>`;
GRANT SELECT       ON TABLE    <catalog>.<schema>.bookings  TO `<sp-application-id>`;
GRANT SELECT       ON TABLE    <catalog>.<schema>.customers TO `<sp-application-id>`;
-- plus CAN_RUN on the Genie space (and CAN_RUN on the published dashboard)
```

The SP can read the tables, but `tenant_row_filter` trims every result to the
SP's own tenant. Admins in `MT_GENIE_ADMIN_GROUP` bypass the filter for
verification.

## Audit trail

### Application audit (Lakebase)

Every query is appended to the Lakebase `audit_log` with tenant, actor, action,
SP, question, status, and latency (`server/lib/repository/audit.py`). The
operator console surfaces it.

### Databricks / Unity Catalog audit (system tables)

`system.access.audit` records the SP identity, the Genie space, the SQL
executed, the objects touched, and row-filter evaluation — correlate to the
app audit by SP application id and timestamp:

```sql
SELECT a.event_time, a.service_name, a.action_name, a.request_params
FROM system.access.audit a
WHERE a.user_identity.email = '<sp-application-id>'
  AND a.event_time BETWEEN '2026-03-25T14:29:00' AND '2026-03-25T14:31:00'
ORDER BY a.event_time;
```

## Security checklist

- [ ] Per-tenant SP secrets encrypted at rest (AES-256-GCM)
- [ ] `AES_KEY_BASE64` from a secret/KMS, not an env file in the repo
- [ ] App passwords hashed (PBKDF2), session cookie signed; demo password overridden
- [ ] TLS on all network paths
- [ ] Row filter applied to every table with tenant data
- [ ] Provisioning identity separated from per-tenant data SPs (and edge SP)
- [ ] Audit logged in the app **and** verified in `system.access.audit`
- [ ] Token cache with proactive refresh (refresh ahead of expiry)
- [ ] Tenant offboarding tested (deactivate + verify no data access)
- [ ] Key rotation cadence documented
- [ ] Cross-tenant isolation verified (`/console` isolation check / `scripts/verify_isolation.py`)
