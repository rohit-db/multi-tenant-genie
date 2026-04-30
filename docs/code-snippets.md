# Code Snippets — Multi-Tenant Genie

Lift-and-use code examples for the moving pieces of the architecture. Every snippet here is pulled from working code in this repo — links to the canonical source file are included so you can read the full context.

**Pattern note:** snippets that depend on identity propagation come in two flavors:
- **Pattern A — SP-per-tenant** (uses `session_user()`). Working today on any Databricks workspace. Shown by default.
- **Pattern B — Shared SP + custom claims** (uses `current_oauth_custom_identity_claims()`). Pending Genie surface validation; shown where it differs.

---

## 1. Authentication & Tokens

### 1.1 OAuth M2M token mint (per-tenant)

The proxy exchanges an SP's `client_id` / `client_secret` for an access token at the workspace's OIDC endpoint. Cache tokens per-SP and refresh ~5 min before expiry.

```python
import requests
import threading
import time


class TokenMinter:
    def __init__(self, host: str):
        self.host = host.rstrip("/")
        self._cache: dict[str, tuple[str, float]] = {}
        self._lock = threading.Lock()

    def get_token(self, client_id: str, client_secret: str) -> str:
        now = time.time()
        with self._lock:
            cached = self._cache.get(client_id)
            if cached and cached[1] - 300 > now:
                return cached[0]

        token, expires_in = self._fetch(client_id, client_secret)
        with self._lock:
            self._cache[client_id] = (token, now + expires_in)
        return token

    def invalidate(self, client_id: str) -> None:
        with self._lock:
            self._cache.pop(client_id, None)

    def _fetch(self, client_id: str, client_secret: str) -> tuple[str, int]:
        resp = requests.post(
            f"{self.host}/oidc/v1/token",
            data={"grant_type": "client_credentials", "scope": "all-apis"},
            auth=(client_id, client_secret),
            timeout=30,
        )
        resp.raise_for_status()
        body = resp.json()
        return body["access_token"], int(body.get("expires_in", 3600))
```

**Pattern B variant** — add `custom_claim` to the request to mint a token carrying a tenant identifier:

```python
data = {
    "grant_type": "client_credentials",
    "scope": "all-apis",
    "custom_claim": f"tenant={tenant_id}",
}
```

The returned JWT carries the claim; UC reads it at query time via `current_oauth_custom_identity_claims()`.

Source: [`server/lib/token_minter.py`](../server/lib/token_minter.py)

### 1.2 Initializing the Databricks SDK from a profile

```python
from databricks.sdk import WorkspaceClient

w = WorkspaceClient(profile="my-profile")        # ~/.databrickscfg profile
# or
w = WorkspaceClient(host="https://...", token="dapi...")
```

---

## 2. Service Principal Lifecycle

### 2.1 Onboard a tenant — create SP, mint secret, register in mapping

End-to-end onboarding for one tenant: create the workspace SP, mint its OAuth secret, persist the secret in a Databricks secret scope, and insert the SP→tenant mapping row that the UC row filter joins against.

```python
from datetime import datetime, timezone
from databricks.sdk import WorkspaceClient

w = WorkspaceClient(profile=PROFILE)

# 1. Create SP
sp = w.service_principals.create(
    display_name=f"mt-genie-{tenant_id}",
    active=True,
)
sp_app_id = sp.application_id
sp_db_id  = sp.id  # numeric workspace-internal id, used for secret APIs

# 2. Mint OAuth secret (returned ONCE — store immediately)
secret = w.service_principal_secrets_proxy.create(
    service_principal_id=sp_db_id
)
client_id     = sp_app_id
client_secret = secret.secret
secret_id     = secret.id

# 3. Persist in a Databricks secret scope
w.secrets.put_secret(
    scope="mt-genie-secrets",
    key=sp_app_id,
    string_value=client_secret,
)

# 4. Register SP→tenant mapping (the row-filter join target)
now = datetime.now(timezone.utc).isoformat()
w.statement_execution.execute_statement(
    warehouse_id=WAREHOUSE_ID,
    statement=f"""
        INSERT INTO {CATALOG}.{SCHEMA}.sp_tenant_mapping (sp_app_id, tenant_id, active)
        VALUES ('{sp_app_id}', '{tenant_id}', true)
    """,
    wait_timeout="30s",
)
```

**Important:** `secret.secret` is shown exactly once. If you lose it, you must rotate.

For account-level SPs (preferred in production so the same identity works across workspaces), use `AccountClient(...).service_principals` instead — the API surface is identical.

Source: [`server/lib/sp_manager.py`](../server/lib/sp_manager.py)

### 2.2 Rotate an SP's OAuth secret

Zero-downtime rotation pattern. Databricks allows up to 5 active secrets per SP, so you can mint the new one before deleting the old.

```python
existing = list(w.service_principal_secrets_proxy.list(service_principal_id=sp_db_id))

# Mint new secret
fresh = w.service_principal_secrets_proxy.create(service_principal_id=sp_db_id)

# Persist new one BEFORE deleting old (so in-flight token exchanges keep working)
w.secrets.put_secret(
    scope="mt-genie-secrets",
    key=sp_app_id,
    string_value=fresh.secret,
)

# Delete prior secrets
for s in existing:
    w.service_principal_secrets_proxy.delete(
        service_principal_id=sp_db_id,
        secret_id=s.id,
    )
```

For true zero-downtime overlap, hold both secrets active for a window (e.g. 5 min) so any caller still using the old credentials migrates successfully.

Source: [`server/lib/sp_manager.py`](../server/lib/sp_manager.py)

### 2.3 Deactivate a tenant

Disable the SP, delete its OAuth secrets (so no new tokens can be minted), and flip the mapping row to inactive (so any cached tokens stop returning rows).

```python
# 1. Mark SP inactive (don't delete — audit trail needs the SP to resolve)
w.service_principals.update(
    id=sp_db_id,
    active=False,
    application_id=sp_app_id,
    display_name=display_name,
)

# 2. Remove all OAuth secrets
for s in w.service_principal_secrets_proxy.list(service_principal_id=sp_db_id):
    w.service_principal_secrets_proxy.delete(
        service_principal_id=sp_db_id, secret_id=s.id
    )

# 3. Delete from secret scope
try:
    w.secrets.delete_secret(scope="mt-genie-secrets", key=sp_app_id)
except Exception:
    pass

# 4. Flip mapping row off (the row filter immediately stops returning data)
w.statement_execution.execute_statement(
    warehouse_id=WAREHOUSE_ID,
    statement=f"UPDATE {CATALOG}.{SCHEMA}.sp_tenant_mapping "
              f"SET active = false WHERE sp_app_id = '{sp_app_id}'",
    wait_timeout="30s",
)
```

**Caveat:** JWTs already issued before deactivation remain valid until their natural TTL (~1h). The mapping `active=false` flip is what stops them from returning rows, not the secret deletion. The secret deletion only prevents new tokens.

Source: [`server/lib/sp_manager.py`](../server/lib/sp_manager.py)

### 2.4 Bulk onboarding at scale

For 100s–1000s of tenants, the [Account SCIM API rate limits](https://docs.databricks.com/aws/en/resources/limits) (5 POST/sec) become the binding constraint. The pattern:

1. **Bounded concurrency** — workers ≈ POST/sec budget (default 5).
2. **429 retry with exponential backoff** — 1s → 2s → 4s → 8s + jitter.
3. **Idempotency** — pre-load existing tenants, skip already-onboarded ids.
4. **Chunked grants** — call `grant_genie_access(ids)` once per chunk, not per tenant. Each call is one PATCH for the whole ACL.
5. **Persist secrets per chunk** — so a mid-run crash never loses a secret.

```python
from concurrent.futures import ThreadPoolExecutor, as_completed
import random, time

def onboard_one(mgr, tenant_id, tenant_name, max_retries=4):
    for attempt in range(1, max_retries + 1):
        try:
            return mgr.onboard_tenant(tenant_id, tenant_name)
        except Exception as e:
            if "429" in str(e) and attempt < max_retries:
                time.sleep((2 ** (attempt - 1)) + random.uniform(0, 0.5))
                continue
            raise

def bulk_onboard(mgr, tenants, workers=5, chunk=50):
    existing = {t.tenant_id for t in mgr.list_tenants()}
    new = [t for t in tenants if t.tenant_id not in existing]

    for i in range(0, len(new), chunk):
        batch = new[i : i + chunk]
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(onboard_one, mgr, t.tenant_id, t.tenant_name): t
                       for t in batch}
            successes = []
            for f in as_completed(futures):
                try:
                    successes.append(f.result().tenant.tenant_id)
                except Exception as e:
                    print(f"  failed: {futures[f].tenant_id}: {e}")
        # Batched grants for the chunk's successes
        mgr.grant_data_access(successes)
        mgr.grant_genie_access(successes)  # one PATCH for all SPs in this batch
```

Wall-time expectations (5 workers, no 429s):

| Tenants | Realistic |
|---|---|
| 100 | 1–2 min |
| 500 | 4–7 min |
| 1,000 | 8–15 min |
| 4,000 | 30–60 min |

Source: [`scripts/bulk_onboard.py`](../scripts/bulk_onboard.py) — production-style script with dry-run, per-tenant outcome JSON, and progress reporting.

---

## 3. Unity Catalog — Row-Level Security

### 3.1 Row filter — Pattern A (SP-per-tenant, `session_user()`)

The filter joins to a mapping table by the SP's `application_id` (which `session_user()` returns when the caller authenticated via OAuth M2M).

```sql
CREATE OR REPLACE FUNCTION main.analytics.tenant_row_filter(tenant_id STRING)
RETURN
  is_account_group_member('admins')
  OR EXISTS (
    SELECT 1
    FROM main.analytics.sp_tenant_mapping m
    WHERE m.sp_app_id = session_user()
      AND m.active = true
      AND m.tenant_id = tenant_row_filter.tenant_id
  );

ALTER TABLE main.analytics.bookings
  SET ROW FILTER main.analytics.tenant_row_filter ON (tenant_id);
```

The `tenant_row_filter.tenant_id` reference inside `EXISTS` disambiguates the function parameter from the column being filtered.

Source: [`sql/lakebase/V001__initial.sql`](../sql/lakebase/V001__initial.sql)

### 3.2 Row filter — Pattern B (shared SP, custom claims)

No mapping table needed. The tenant identifier is read directly from the JWT.

```sql
CREATE OR REPLACE FUNCTION main.analytics.tenant_filter(tenant_id STRING)
RETURN IF(
    tenant_id = current_oauth_custom_identity_claims():tenant
    OR is_account_group_member('admins'),
    true, false
);

ALTER TABLE main.analytics.bookings
  SET ROW FILTER main.analytics.tenant_filter ON (tenant_id);
```

`current_oauth_custom_identity_claims()` returns a STRUCT — index into it (`:tenant` here) for the specific claim you set during token exchange.

Source: This file has been removed. Pattern B is not shipping; Pattern A (above) is the active row-filter implementation.

### 3.3 Grant data access to a tenant SP (Pattern A only)

Pattern A requires each SP to have catalog/schema/table privileges. The row filter is the *isolation* layer; these GRANTs are the *visibility* layer.

```python
for sp_app_id in tenant_sp_app_ids:
    for stmt in (
        f"GRANT USE CATALOG ON CATALOG main TO `{sp_app_id}`",
        f"GRANT USE SCHEMA ON SCHEMA main.analytics TO `{sp_app_id}`",
        f"GRANT SELECT ON TABLE main.analytics.bookings TO `{sp_app_id}`",
        f"GRANT SELECT ON TABLE main.analytics.sp_tenant_mapping TO `{sp_app_id}`",
    ):
        w.statement_execution.execute_statement(
            warehouse_id=WAREHOUSE_ID, statement=stmt, wait_timeout="30s"
        )
```

In Pattern B, only the shared SP needs grants — far simpler.

Source: [`server/lib/sp_manager.py`](../server/lib/sp_manager.py)

### 3.4 Schema for the SP→tenant mapping table

```sql
CREATE TABLE main.analytics.sp_tenant_mapping (
    sp_app_id STRING NOT NULL,
    tenant_id STRING NOT NULL,
    active    BOOLEAN NOT NULL
) USING DELTA
COMMENT 'Lookup table joined in the tenant row filter';
```

Keep this minimal — every row-filter evaluation joins it. Multi-tenant fan-out (one SP serving multiple tenants) is supported by inserting multiple rows.

Source: [`sql/lakebase/V001__initial.sql`](../sql/lakebase/V001__initial.sql)

---

## 4. Genie Conversation API

### 4.1 Grant a tenant SP CAN_RUN on a Genie space

```python
import requests

acl = [
    {"service_principal_name": sp_app_id, "permission_level": "CAN_RUN"}
    for sp_app_id in tenant_sp_app_ids
]

token = w.config.oauth_token().access_token  # admin OAuth token
r = requests.patch(
    f"{HOST}/api/2.0/permissions/genie/{SPACE_ID}",
    headers={"Authorization": f"Bearer {token}"},
    json={"access_control_list": acl},
    timeout=30,
)
r.raise_for_status()
```

`PATCH` adds to the ACL; `PUT` replaces it. Use `PATCH` when onboarding incrementally.

Source: [`server/lib/sp_manager.py`](../server/lib/sp_manager.py)

### 4.2 Ask Genie a question end-to-end (start, poll, fetch result)

The full request lifecycle: start a conversation, poll the message until terminal status, then fetch the query-result attachment for SQL + rows.

```python
import requests
import time

HOST     = "https://<workspace>.cloud.databricks.com"
SPACE_ID = "01f1..."

def ask(token: str, question: str, conversation_id: str | None = None) -> dict:
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Start (or continue) a conversation
    if conversation_id:
        r = requests.post(
            f"{HOST}/api/2.0/genie/spaces/{SPACE_ID}/conversations/{conversation_id}/messages",
            headers=headers, json={"content": question}, timeout=30,
        )
    else:
        r = requests.post(
            f"{HOST}/api/2.0/genie/spaces/{SPACE_ID}/start-conversation",
            headers=headers, json={"content": question}, timeout=30,
        )
    r.raise_for_status()
    body = r.json()
    conversation_id = body.get("conversation_id") or conversation_id
    message_id = (body.get("message") or body)["id"]

    # 2. Poll until terminal
    deadline = time.time() + 120
    while True:
        if time.time() > deadline:
            raise TimeoutError("Genie did not return within timeout")
        r = requests.get(
            f"{HOST}/api/2.0/genie/spaces/{SPACE_ID}/conversations/{conversation_id}/messages/{message_id}",
            headers=headers, timeout=30,
        )
        r.raise_for_status()
        msg = r.json()
        if msg.get("status") in ("COMPLETED", "FAILED", "CANCELLED"):
            break
        time.sleep(1.5)

    # 3. Pull SQL + result rows from attachments
    sql, rows, columns, answer_text = None, [], [], None
    for att in msg.get("attachments", []) or []:
        if "query" in att:
            sql = att["query"].get("query")
            attachment_id = att.get("attachment_id") or att.get("id")
            if attachment_id:
                rr = requests.get(
                    f"{HOST}/api/2.0/genie/spaces/{SPACE_ID}/conversations/"
                    f"{conversation_id}/messages/{message_id}/attachments/"
                    f"{attachment_id}/query-result",
                    headers=headers, timeout=60,
                )
                if rr.ok:
                    sr = (rr.json().get("statement_response") or {})
                    columns = [c["name"] for c in sr.get("manifest", {}).get("schema", {}).get("columns", [])]
                    rows = (sr.get("result") or {}).get("data_array") or []
        if "text" in att:
            answer_text = att["text"].get("content") or answer_text

    return {
        "status": msg.get("status"),
        "conversation_id": conversation_id,
        "message_id": message_id,
        "sql": sql,
        "answer_text": answer_text,
        "columns": columns,
        "rows": rows,
    }
```

**Rate limit:** Genie enforces ~5 questions/min per workspace. For high-fan-out use cases (isolation sweeps, multi-tenant batch), throttle calls or distribute across workspaces.

Source: [`server/lib/genie_client.py`](../server/lib/genie_client.py)

### 4.3 Identify which SP a token represents

Useful for sanity checks ("am I really calling Genie as the right tenant?"):

```python
r = requests.get(
    f"{HOST}/api/2.0/preview/scim/v2/Me",
    headers={"Authorization": f"Bearer {token}"},
    timeout=30,
)
r.raise_for_status()
print(r.json())  # contains application_id, display_name, etc.
```

Source: [`server/lib/genie_client.py`](../server/lib/genie_client.py)

---

## 5. Audit & Observability

### 5.1 Audit log table schema

```sql
CREATE TABLE main.analytics.audit_log (
    event_time  TIMESTAMP NOT NULL,
    actor       STRING,        -- the human/admin/proxy that triggered the action
    tenant_id   STRING,
    action      STRING,        -- onboard | rotate | deactivate | query
    sp_app_id   STRING,
    question    STRING,        -- populated on action='query'
    latency_ms  INT,
    status      STRING,        -- ok | error
    detail      STRING         -- e.g. error message, secret_id, genie_status
) USING DELTA;
```

Source: [`sql/lakebase/V001__initial.sql`](../sql/lakebase/V001__initial.sql)

### 5.2 Insert an audit row from the proxy

```python
def audit(action: str, tenant_id: str, sp_app_id: str, *,
          question: str | None = None,
          latency_ms: int | None = None,
          status: str = "ok",
          detail: str | None = None) -> None:
    now = datetime.now(timezone.utc).isoformat()
    actor = w.current_user.me().user_name or "unknown"

    def _q(v: str | None) -> str:
        return "NULL" if v is None else f"'{v.replace(chr(39), chr(39)*2)}'"

    latency_sql = "NULL" if latency_ms is None else str(int(latency_ms))
    w.statement_execution.execute_statement(
        warehouse_id=WAREHOUSE_ID,
        statement=f"""
            INSERT INTO {CATALOG}.{SCHEMA}.audit_log
              (event_time, actor, tenant_id, action, sp_app_id, question,
               latency_ms, status, detail)
            VALUES (TIMESTAMP'{now}', '{actor}', '{tenant_id}', '{action}',
                    '{sp_app_id}', {_q(question)}, {latency_sql}, '{status}', {_q(detail)})
        """,
        wait_timeout="30s",
    )
```

**Production note:** the string interpolation here is fine for a sandbox demo but should be replaced with parameterized statements or a Lakebase append for high-volume audit ingestion.

Source: [`server/lib/sp_manager.py`](../server/lib/sp_manager.py)

### 5.3 Useful audit queries

Top tenants by query volume in the last 24h:

```sql
SELECT tenant_id, COUNT(*) AS queries, AVG(latency_ms) AS avg_ms
FROM main.analytics.audit_log
WHERE action = 'query' AND event_time > NOW() - INTERVAL 1 DAY
GROUP BY tenant_id
ORDER BY queries DESC;
```

Failed queries per tenant:

```sql
SELECT tenant_id, status, COUNT(*) AS n, MAX(event_time) AS last_seen
FROM main.analytics.audit_log
WHERE action = 'query' AND status <> 'ok'
GROUP BY tenant_id, status
ORDER BY n DESC;
```

Cross-tenant attempts (detect via `detail` mismatch — audit captures intent, UC enforces):

```sql
SELECT actor, tenant_id, question, detail
FROM main.analytics.audit_log
WHERE action = 'query'
  AND status = 'error'
  AND detail LIKE '%PERMISSION_DENIED%'
ORDER BY event_time DESC;
```

---

## 6. End-to-End Request — Putting It All Together

```python
def handle_request(api_key: str, question: str) -> dict:
    # 1. Authenticate the API client (your IdP, NOT Databricks)
    tenant_id = lookup_tenant_by_api_key(api_key)        # Lakebase / your registry

    # 2. Resolve the tenant's SP credentials
    sp_app_id, sp_secret = lookup_sp_creds(tenant_id)    # secret scope or Lakebase

    # 3. Mint (or reuse cached) OAuth M2M token
    token = minter.get_token(sp_app_id, sp_secret)

    # 4. Call Genie
    started = time.time()
    try:
        result = ask(token, question)
        latency_ms = int((time.time() - started) * 1000)
        audit("query", tenant_id, sp_app_id,
              question=question, latency_ms=latency_ms,
              status="ok" if result["status"] == "COMPLETED" else "error",
              detail=None if result["status"] == "COMPLETED" else f"genie_status={result['status']}")
        return result
    except Exception as e:
        audit("query", tenant_id, sp_app_id,
              question=question, status="error", detail=str(e))
        raise
```

The pieces:
1. **Your auth layer** validates the customer (API key, JWT, mTLS — whatever fits).
2. **Tenant resolution** maps the authenticated identity to a tenant_id.
3. **SP credential lookup** retrieves the SP's OAuth credentials.
4. **Token mint** exchanges credentials → workspace token (cache aggressively).
5. **Genie call** with the per-tenant token. UC's row filter handles isolation.
6. **Audit** captures every request — same code path on success and failure.

The tenant never knows about Databricks. Onboarding a new tenant = create SP + register mapping (Pattern A) or just add a row to your tenant registry (Pattern B).
