# Rate Limits & Scaling

## Service Principal & Account API Limits

Sourced from the [Databricks resource limits page](https://docs.databricks.com/aws/en/resources/limits).

| Operation | Limit | Notes |
|---|---|---|
| Account SCIM `POST` / `PUT` / `DELETE` | **5 / second** | SP create, OAuth secret create, SP delete |
| Account SCIM `PATCH` | **2 / second** | Updates to SPs, group memberships |
| Account SCIM `GET` | **20 / second** | Lookups |
| Workspace API (general) | Per-endpoint, see docs | E.g. `workspace/list` is 50/sec |
| OAuth `/oidc/v1/token` | Not formally documented | Generally generous; back off on 429 |

### Implications for Bulk Onboarding

At 5 POST/sec, the theoretical floor for **N tenants** is `N / 5` seconds (just SP create), but each tenant also needs a secret mint (POST), a secret-scope put (POST), and 2-3 UC inserts (warehouse-bound, separate budget). Realistic per-tenant time: **2–4 seconds** at 5 concurrent workers.

| Tenants | Best-case | Realistic |
|---|---|---|
| 100 | ~20s | 1–2 min |
| 500 | ~100s | 4–7 min |
| 1,000 | ~200s | 8–15 min |
| 4,000 | ~13 min | 30–60 min |

For >5,000 tenants, parallelize across multiple account-API hosts (uncommon) or run in off-hours batches.

### Bulk Onboarding Script

[`scripts/bulk_onboard.py`](../scripts/bulk_onboard.py) implements the rate-limit-aware pattern:
- Default `--workers 5` matches the POST budget
- 429s retried with exponential backoff (1s → 2s → 4s → 8s + jitter)
- Idempotent: existing `tenant_id`s are skipped
- Chunked grants (one `PATCH` per chunk for Genie permissions, batched UC GRANTs)
- Per-tenant outcome JSON for post-run reconciliation

```bash
# Dry-run plan
python scripts/bulk_onboard.py --count 500 --dry-run

# Real run from CSV
python scripts/bulk_onboard.py --input tenants.csv --workers 5

# Tighter concurrency for shared-account environments
python scripts/bulk_onboard.py --input tenants.csv --workers 3 --chunk 25
```

## Genie API Limits

| Constraint | Limit | Source |
|---|---|---|
| Questions per minute per workspace | 5 | [Genie API docs](https://docs.databricks.com/aws/en/genie/conversation-api) |
| Max rows per query result | 5,000 | Genie API docs |
| Conversations per space | 10,000 | Genie API docs |
| Polling interval (recommended) | 1-5s with exponential backoff | Genie API docs |

### Implications at Scale

With 5 questions/min/workspace and thousands of tenants:
- **1 workspace** → 300 questions/hour → ~7,200/day
- **5 workspaces** → 1,500 questions/hour → ~36,000/day
- **10 workspaces** → 3,000 questions/hour → ~72,000/day

## Scaling Strategies

### 1. Multi-Workspace Round-Robin

Distribute requests across multiple workspaces to multiply throughput:

```python
import itertools

class WorkspacePool:
    def __init__(self, workspace_configs: list[dict]):
        self.workspaces = workspace_configs
        self._cycle = itertools.cycle(self.workspaces)
        self._per_workspace_count = {}  # track per-minute usage

    def get_next(self) -> dict:
        """Get next available workspace under rate limit."""
        for _ in range(len(self.workspaces)):
            ws = next(self._cycle)
            if self._under_limit(ws["url"]):
                return ws
        raise RateLimitExceeded("All workspaces at capacity")
```

Requirements:
- Same UC metastore across all workspaces
- Same SP assigned to all workspaces
- Same Genie Space replicated (or use a single space if same workspace)
- Row filters work identically across workspaces

### 2. Request Queue with Priority

```python
import asyncio
from enum import IntEnum

class Priority(IntEnum):
    HIGH = 1      # Paid tier tenants
    STANDARD = 2  # Standard tier
    LOW = 3       # Free tier / internal

class RequestQueue:
    def __init__(self, max_per_minute: int = 5):
        self.queue = asyncio.PriorityQueue()
        self.semaphore = asyncio.Semaphore(max_per_minute)

    async def enqueue(self, priority: Priority, request: dict):
        await self.queue.put((priority, request))

    async def process(self):
        while True:
            priority, request = await self.queue.get()
            async with self.semaphore:
                await self._execute(request)
```

### 3. Response Caching

Cache frequent/identical questions per tenant:

```python
import hashlib
from datetime import timedelta

def cache_key(tenant_id: str, question: str) -> str:
    normalized = question.strip().lower()
    return f"genie:{tenant_id}:{hashlib.sha256(normalized.encode()).hexdigest()}"

# Cache for 15 minutes — balances freshness with throughput
CACHE_TTL = timedelta(minutes=15)
```

### 4. Conversation Limit Management

Genie spaces have a 10,000 conversation limit. At scale:

- **Monitor** conversation count via the Genie API
- **Archive/rotate** spaces when approaching the limit
- **Multiple spaces** for different analytics domains (reduces per-space load)
- **Reuse conversations** for follow-up questions from the same tenant session

## Token Caching

OAuth tokens last 1 hour. Caching avoids redundant OIDC calls:

| Strategy | Description | When to Use |
|----------|-------------|-------------|
| **Per-tenant in-memory** | Dict of tenant_id → (token, expiry) | Single proxy instance |
| **Redis** | Shared cache across proxy instances | Multi-instance deployment |
| **Proactive refresh** | Refresh 5 min before expiry | Always (avoid request-time latency) |

```python
# Per-tenant token with proactive refresh
# See server/primitives/identity.py for the TokenMinter implementation
```

## Per-Tenant Rate Limiting

Enforce limits in the proxy to prevent a single tenant from consuming all Genie capacity:

```python
from collections import defaultdict
import time

class ClientRateLimiter:
    def __init__(self):
        self._requests = defaultdict(list)  # tenant_id -> [timestamps]

    def check(self, tenant_id: str, limit_per_min: int) -> bool:
        now = time.time()
        window = [t for t in self._requests[tenant_id] if now - t < 60]
        self._requests[tenant_id] = window
        if len(window) >= limit_per_min:
            return False
        self._requests[tenant_id].append(now)
        return True
```

Tenant tiers:

| Tier | Rate Limit | Use Case |
|------|-----------|----------|
| Enterprise | 10/min | High-value tenants with SLAs |
| Standard | 3/min | Most tenants |
| Basic | 1/min | Low-usage / trial tenants |

## Cost Management

### Compute Attribution

- **Pattern B (single SP):** All queries attributed to one SP in system tables. Use app-level audit logs for per-tenant cost allocation.
- **Pattern A (SP-per-tenant):** Each SP's compute is separately visible in `system.billing.usage` and `system.access.audit`.

### Serverless SQL Cost

Genie uses a SQL warehouse. Serverless pricing is per-query:
- Scales to zero when idle
- No per-client compute isolation (shared warehouse)
- Cost attribution via audit logs, not compute isolation

### Optimization

- Use **serverless SQL** (scales to zero, pay-per-query)
- Cache responses aggressively for repeated questions
- Set `auto_stop_mins` on non-serverless warehouses
- Monitor `system.billing.usage` for cost trends

## Scaling beyond a single Genie Space

Each Genie Space currently caps at ~10,000 conversations. For deployments exceeding that:

- The data model accommodates per-tenant overrides via `client_registry.genie_space_id` (nullable; null → workspace global).
- Surface a Genie space picker in the Admin tab when you need it. See [docs/future-directions.md](future-directions.md#multi-genie-space-ui) for the localized change list.
- Operationally: split tenants across spaces by tier, region, or vertical. Each space gets its own tuning + content.

## Lakebase scaling

The metadata store (`client_registry`, `sp_credentials`, `audit_log`) is single-Postgres-instance. Lakebase auto-scales the underlying compute; for the reference workload (read on every request, write on every onboard / query), a base instance handles thousands of tenants.

Hot paths:
- Tenant lookup on `/api/genie/ask`: indexed `client_registry.tenant_id`.
- Audit append: append-only writes to `audit_log`, indexed on `(tenant_id, created_at DESC)`.

For multi-instance proxy deployments, the in-memory token cache (`TokenMinter`) becomes a per-replica cache — the `token_cache` Postgres table can be enabled to share token state across replicas. Schema is in place; the cache reader is not yet wired.
