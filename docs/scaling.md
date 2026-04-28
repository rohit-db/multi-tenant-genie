# Rate Limits & Scaling

## Genie API Limits

| Constraint | Limit | Source |
|---|---|---|
| Questions per minute per workspace | 5 | [Genie API docs](https://docs.databricks.com/aws/en/genie/conversation-api) |
| Max rows per query result | 5,000 | Genie API docs |
| Conversations per space | 10,000 | Genie API docs |
| Polling interval (recommended) | 1-5s with exponential backoff | Genie API docs |

### Implications at Scale

With 5 questions/min/workspace and thousands of clients:
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
    HIGH = 1      # Paid tier clients
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
- **Reuse conversations** for follow-up questions from the same client session

## Token Caching

OAuth tokens last 1 hour. Caching avoids redundant OIDC calls:

| Strategy | Description | When to Use |
|----------|-------------|-------------|
| **Per-tenant in-memory** | Dict of tenant_id → (token, expiry) | Single proxy instance |
| **Redis** | Shared cache across proxy instances | Multi-instance deployment |
| **Proactive refresh** | Refresh 5 min before expiry | Always (avoid request-time latency) |

```python
# Per-tenant token with proactive refresh
# See pattern-b-custom-claims.md for TokenMinter implementation
```

## Per-Client Rate Limiting

Enforce limits in the proxy to prevent a single client from consuming all Genie capacity:

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

Client tiers:

| Tier | Rate Limit | Use Case |
|------|-----------|----------|
| Enterprise | 10/min | High-value clients with SLAs |
| Standard | 3/min | Most clients |
| Basic | 1/min | Low-usage / trial clients |

## Cost Management

### Compute Attribution

- **Pattern B (single SP):** All queries attributed to one SP in system tables. Use app-level audit logs for per-tenant cost allocation.
- **Pattern A (SP-per-client):** Each SP's compute is separately visible in `system.billing.usage` and `system.access.audit`.

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
