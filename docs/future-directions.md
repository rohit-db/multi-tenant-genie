# Future Directions

What this reference does not include — and where to add it later.

Each section names the gap, the mechanism, and the localized place to add the implementation. Nothing here is planned for the reference itself; these are starting points if your deployment grows past what's in scope.

## Pattern B — Shared SP + custom claims

**The idea:** instead of one Service Principal per tenant, run *one* SP and pass the tenant's identity as a custom claim on the OAuth token. UC's `current_oauth_custom_identity_claims()` reads the claim inside the row filter. Result: O(1) SP management instead of O(N).

**Why not in the reference:** at the time of writing, Genie's Conversation API surfaces don't reliably honor custom identity claims. Pattern A works today on GA primitives; Pattern B is a future swap when the Genie surfaces validate.

**Where it lands when ready:**
- Replace `tenant_row_filter` SQL: read `current_oauth_custom_identity_claims()` instead of joining `sp_tenant_mapping` on `session_user()`.
- Replace `server/lib/sp_manager.py:onboard_tenant`: skip the SP creation; insert into `client_registry` only.
- Replace `server/lib/genie_client.py:ask`: mint the token with a custom claim per request instead of using the tenant's per-SP credentials.

This is a 1-day swap when Genie's surfaces support it. The data model already has space for the registry-only path.

## Per-tenant rate limits / quotas

**The idea:** budget each tenant's requests per minute / per hour. Reject (or queue) overshoot.

**Where it lands:**
- Add a token bucket in `server/lib/rate_limiter.py` keyed on `tenant_id`. In-memory works for single-instance Apps deploys; Lakebase-backed counters work for multi-instance.
- Read the tenant's budget from `client_registry.rate_limit_per_min` (column already exists).
- Wrap `_ask_sync` in `server/routers/genie.py` with the limiter check.
- Surface the budget + current usage in the Admin tab — extend `NumbersStrip` or add a per-tenant column.

The hard part is not the limiter; it's deciding what to do on overshoot (429 vs queue vs degrade to cached answer).

## Multi-Genie-space UI

**The idea:** different tenants ask against different Genie Spaces (e.g., per-vertical tuning, per-region content).

**Where it lands:**
- The data model is already there: `client_registry.genie_space_id` is a nullable column. Null → use the workspace global; set → use the override.
- Surface in the UI: in `web/src/components/AdminPage.tsx`, add a per-tenant Genie space picker to the row actions or onboard dialog.
- Update `server/routers/genie.py:_ask_sync` to read the override (it currently uses `CONFIG.genie_space_id` unconditionally).

The platform reason this is interesting: each Genie Space caps at 10,000 conversations. Splitting tenants across spaces is the documented scaling story.

## Cost / token tracking per tenant

**The idea:** show what each tenant costs in Genie API tokens. Bill or alert.

**Where it lands:**
- Genie's Conversation API doesn't currently surface per-call token cost in its response shape. Watch the API release notes for this.
- When it lands: extend `audit_log` with `tokens_in INTEGER, tokens_out INTEGER`, populate from the response, surface in `NumbersStrip` and the per-tenant history drawer.

This is gated entirely on the upstream API. Don't build the UI until the backend has data to fill it.

## Reverse-ETL of `audit_log` to UC

**The idea:** keep `audit_log` hot in Lakebase but mirror it to UC for analytics tooling.

**Where it lands:**
- Lakebase Synced Tables — define a sync from `mtg.audit_log` (Postgres) to `<catalog>.<schema>.audit_log_uc` (Delta).
- Set up the sync once via the Lakebase UI or CLI. The proxy doesn't need to know.

This is operational, not code-resident.

## Background-job runner for bulk onboard

**The idea:** the in-process job runner (`server/jobs/bulk_onboard.py`) is fine for hundreds of tenants in a single shot. For tens of thousands, swap to a Databricks Job that the API kicks off and polls.

**Where it lands:**
- `server/jobs/bulk_onboard.py:JobRunner.submit` already returns a `job_id` — replace its body to call `databricks.sdk.WorkspaceClient.jobs.run_now(...)` and return the run_id.
- `server/routers/jobs.py:get_job` reads job state from Databricks instead of the in-process dict.
- The Job task itself runs `scripts/bulk_onboard.py --input <list>` against the tenant list passed via job parameters.

The interface is small — the swap is contained to two files.

## E2E browser tests

**The idea:** Playwright specs in CI.

**Why not now:** browser tests are high-leverage for product apps; for a reference repo, the maintenance cost typically outweighs the value. The proxy contract is unit-tested (30 tests run without infra), and the Architecture tab's live mapping table + verify endpoint are the credibility moments — not the Demo tab buttons.

If you fork for production: Playwright is already a dev dependency in `web/package.json`. Add specs to `web/tests/` and wire them into CI.
