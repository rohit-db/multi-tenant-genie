# Demo Script + Blog Draft

Two artifacts for sharing the multi-tenant Genie reference with your team:

- **Section 1** — a 6-7 minute screen-recording script with stage directions and narration.
- **Section 2** — a long-form blog draft you can adapt for an internal post.

---

## Section 1 — 6-7 Minute Demo Script

**Format:** screen recording with voiceover. App URL: `https://multi-tenant-genie-7474655568396905.aws.databricksapps.com` (FEVM deploy). Default tenant: Acme Industrial.

**Before recording:**
- Open the app on Portal tab, Acme selected, dashboard loaded.
- Have the repo URL ready.
- Close notification windows.

**Flow:** Hook → Demo (all together) → Isolation → Architecture → Wrap.

---

### 0:00 — 0:30 · Hook

**On screen:** Portal tab, dashboard loaded.

> "Most teams asking about embedding Genie are building something that looks like this — a branded portal, charts on their data, a chat assistant. The dashboard's easy. The hard part is making sure tenant A never sees tenant B's data, on a shared workspace, shared warehouse, shared Genie space.
>
> This is a reference that solves that. Let me show you."

---

### 0:30 — 3:30 · Demo

**On screen:** Portal tab, Acme selected. Switch tenants via "Acting as" dropdown — Nike, then CloudVenture, back to Acme.

> "Signed in as Acme. 250 bookings, half a million in spend, top route Austin–Denver.
>
> Switch to Nike. Same dashboard, same queries — different numbers. CloudVenture, different again. No code changed, no prompts changed. The proxy minted a different OAuth token per tenant, UC's row filter did the rest. Isolation lives in the warehouse, not the model."

**Click the Chat button in the header. Panel slides in. Type "what was my busiest month?" Send.**

> "Chat panel is Genie. Tenant asks in English, Genie writes the SQL, UC trims it to Acme's rows. Answer's grounded in real data."

**Close chat. Click the Insights agent button. Panel slides in.**

> "Custom agents follow the same pattern. This one's three steps — plan, execute, synthesize. Foundation Model picks the SQL, each query runs as Acme's SP, Foundation Model writes the recommendation."

**Pick or type a focus area like "Where am I spending the most and what's growing fastest?" Click Run insights.**

> "Plan up top. Three tool calls."

**Expand a tool call.**

> "Actual SQL the agent wrote. Result rows — Acme only. Switch to Nike, rerun, you get Nike. The agent could be LangGraph, the OpenAI Agents SDK, anything. The guarantee comes from the SP token, not the framework."

**Close panel. Switch to Admin tab.**

> "Admin tab is the operator surface. Live numbers from the audit log. Onboard creates the SP, mints the OAuth secret, encrypts it in Lakebase, inserts the UC mapping, grants Genie access — all transactional, rolls back on failure. There's a bulk path for thousands of tenants — paste a CSV, get a job."

---

### 3:30 — 5:00 · Isolation

**On screen:** Switch to Isolation proof tab. Pick Acme. Type a question or use a sample chip. Click Ask Genie.**

> "Isolation proof tab. Six steps run on every ask. The inspector shows what's actually on the wire."

**Click step 1 "Authenticate".**

> "Step 1, proxy looks up the tenant in Lakebase. Actual SQL, actual host."

**Click step 4 "Apply row filter" (amber).**

> "Step 4 is the one that matters. UC's row filter runs in the warehouse for this SP. Proxy doesn't get to decide what the tenant sees. UC does."

**Scroll up, click Verify isolation.**

> "And the proof — Verify isolation runs as every active tenant, queries the bookings table, asserts each only sees its own rows. This is the test that has to be green for the architecture to mean anything."

**Wait for results.**

> "All passing."

---

### 5:00 — 6:00 · Architecture

**On screen:** Switch to Architecture tab. Scroll to system architecture diagram.

> "Whole architecture in one picture. Three call paths from the tenant — Genie, direct SQL for the widgets, custom agent. All three converge on the same OAuth minter, all three run as the tenant SP, UC's row filter is the single enforcement point.
>
> Lakebase holds the operational metadata — tenant registry, encrypted credentials, audit. UC holds the governed data and the mapping table the row filter joins."

**Scroll to "Row filter — live SQL".**

> "This is the function deployed in UC. It joins `sp_tenant_mapping` on `session_user()` — which resolves to the SP's app ID. No `WHERE tenant_id =` in the proxy code, no prompt instruction. One SP per tenant, one row filter, deployed once. That's the whole pattern."

---

### 6:00 — 6:45 · Take it + wrap

**On screen:** Portal tab clean, or terminal showing the repo.

> "Repo's `github.com/rohit-db/multi-tenant-genie`, branch `generalize-and-scale`. `scripts/deploy.sh` does the whole deploy in one command — Lakebase, secret scope, app SP, UC grants. 90 seconds against a fresh workspace.
>
> Three takeaways. One — UC row filters are the right enforcement layer. Not the model, not the prompt, not the app code. Two — the SP-per-tenant pattern works for any agent you build, not just Genie. Three — this is opinionated. Pattern A only, Lakebase for OLTP, no Pattern B yet. Future directions are in the doc.
>
> Fork it, adapt the domain, tell me what you build."

**End on Portal.**

---

### Director's notes

- **Total runtime:** ~6:45 if clicks land cleanly. Pad pauses on the tenant-switch moment — that's the most-rewatched second.
- **The agent moment is the differentiator.** Most viewers have seen Genie demos. "Same pattern, custom agent" is why they re-share.
- **Don't apologize for opinions.** Pattern A only, Lakebase for OLTP — state them, move on.

---

## Section 2 — Blog Draft

**Working title:** *A reference architecture for multi-tenant Databricks Genie*

**Suggested length:** 1200–1500 words. The draft below is around 1300 words; trim or extend per house style.

---

### A reference architecture for multi-tenant Databricks Genie

Most customers asking me about embedding Genie aren't asking for Genie. They're asking for the answer to a harder question: *how do I deliver Genie to thousands of tenants — embedded in my own SaaS, behind my own auth, branded as my product — and guarantee that tenant A never sees tenant B's data?*

That last clause is the whole problem. The dashboard is straightforward. The chat is straightforward. Tenant isolation, on a shared workspace with a shared warehouse and a shared Genie space, is where most attempts get stuck.

I built a reference solution that solves it, deployed it as a Databricks App on a serverless FEVM workspace, and packaged it as a one-command deploy anyone on the field can fork and adapt. This post walks through the pattern, what's in the repo, and what I deliberately left out.

#### The pattern: row filters, not prompts

There are three places you can try to enforce tenant isolation in a Genie deployment:

1. **At the prompt layer** — tell the model "only return rows for tenant X." This is what most early implementations do. It's non-deterministic, not auditable, and breaks the moment the model decides to be creative.
2. **At the application layer** — filter rows in the proxy before returning to the user. This works but it means the proxy has to inspect every result, which kills performance and turns the proxy into a security-critical component.
3. **At the warehouse** — Unity Catalog row filters, joined against a mapping table on `session_user()`. The filter runs in-warehouse, deterministically, on every query. The proxy doesn't decide what the tenant can see. UC does.

This reference picks option 3. The whole pattern is one Service Principal per tenant, one mapping table, one row filter function deployed once.

```sql
CREATE OR REPLACE FUNCTION tenant_row_filter(tenant_id STRING)
RETURN
  is_account_group_member('admins')
  OR EXISTS (
    SELECT 1 FROM sp_tenant_mapping m
    WHERE m.sp_app_id = session_user()
      AND m.active = true
      AND m.tenant_id = tenant_row_filter.tenant_id
  );
```

Apply that function to every tenant-scoped table with `ALTER TABLE … SET ROW FILTER`. Mint OAuth tokens per tenant SP. Done. The tenant SP is the only thing the proxy hands to Genie or any custom agent. UC handles the rest.

#### What's in the repo

The repo is a FastAPI proxy plus a React UI. Three layers:

- **Lakebase** holds the operational metadata: `client_registry` (tenants), `sp_credentials` (encrypted at rest with AES-GCM), `audit_log`, `token_cache`. Reads on every request, writes on every onboard and every query. Postgres is the right tool for that workload.
- **UC Delta** holds the governed data and the `sp_tenant_mapping` table. The row filter has to live here because UC is where the SQL runs.
- **The proxy** is a thin FastAPI app: tenant onboarding via SCIM, OAuth token minting, request inspector, and three call paths from the UI — Genie ask, direct SQL for dashboard widgets, and a custom agent endpoint.

The UI has four tabs:

- **Portal** is the customer-facing data app — KPIs, charts, a chat panel and a custom-agent panel that slide in from the right. This is what someone watching a demo recognizes as the thing they're trying to build.
- **Isolation proof** has the request-flow inspector. Six steps on every Genie ask — authenticate, resolve tenant, mint token, apply row filter, ask Genie, audit. Each step shows the actual SQL or HTTP call on the wire. The amber-highlighted step is the row filter, because that's the one that matters.
- **Admin** is the operator surface — tenant table, lifecycle actions (rotate / deactivate / reactivate / delete), bulk onboarding, audit log, and a "verify isolation" button that runs through every active tenant and asserts isolation holds.
- **Architecture** has the system diagram, the deployed row filter SQL, and the live `sp_tenant_mapping` table.

#### Custom agents: same pattern, different framework

The most interesting part for me, after Genie was working, was watching the same pattern survive being wrapped in a custom agent. The reference includes one — a "travel insights" agent that does plan / execute / synthesize:

1. Foundation Model API picks two or three SQL queries that would help answer a focus area.
2. Each query runs through the proxy as the tenant's SP. Same OAuth token Genie would use. Same row filter.
3. Foundation Model API takes the results and writes a recommendation.

The agent could be doing anything — LangGraph multi-turn loops, the OpenAI Agents SDK, your own framework. The isolation guarantee comes from the SP token, not the agent's reasoning loop. The agent never sees more rows than the row filter lets through.

The repo currently runs the agent inline in the proxy for simplicity. The recommended deploy, now that Databricks Apps is the preferred place to host agents, is splitting the agent into its own app and POSTing from the proxy. The split is a one-file lift; the architecture diagram in the repo's Architecture tab shows both shapes.

#### Operating it at scale

The repo includes a few things you don't always see in a reference:

- **`scripts/deploy.sh`** does the whole deploy in one command — Lakebase instance, secret scope, app SP, UC grants, resource bindings, the lot. Idempotent. I deployed against a fresh FEVM workspace in 90 seconds for verification.
- **Bulk onboarding** as an in-process job — accepts a CSV or JSON list, runs through `SPManager.onboard_tenant` on a thread pool with 429 retry, returns per-tenant outcomes. Documented swap-path to a real Databricks Job for production scale.
- **Verify isolation** is the credibility test. It runs as each active tenant, queries the bookings table, asserts each only sees its own rows. The whole thing has to be green for the architecture to mean anything. It runs as a runtime UI feature and also as a release-gate script.

#### What I left out

This is opinionated. Some things are deliberately not in the reference:

- **Pattern B (shared SP + custom claims)** is documented as a future direction. It needs Genie surface validation before I'd ship it as a recommended path. There's an active escalation tracking the gap.
- **Per-tenant rate limits** — `client_registry.rate_limit_per_min` is in the schema; no enforcement layer yet. The interesting design question (what to do on overshoot) is harder than the limiter itself.
- **Multi-Genie-space UI** — the data model accommodates per-tenant overrides via `client_registry.genie_space_id`. The UI doesn't surface it yet. Each Genie space caps at 10,000 conversations; for deployments above that, splitting tenants across spaces by tier or vertical is the path. Three lines of code; deferred until someone actually needs it.
- **Cost / token tracking per tenant** — Genie's API doesn't currently expose token cost in its response shape. When it does, the audit log already has space for it.

The full list is in `docs/future-directions.md`.

#### How to take it

Repo: [github.com/rohit-db/multi-tenant-genie](https://github.com/rohit-db/multi-tenant-genie), branch `generalize-and-scale`. The design spec, all four implementation plans, and the deploy guide are in `docs/`. The README is the front door.

Pre-reqs: a serverless workspace with Apps enabled, a SQL warehouse, a Genie space, and the Databricks CLI authenticated. That's all. Run `scripts/deploy.sh`, open the resulting URL, click Onboard a couple of times. Working multi-tenant Genie demo, less than two minutes from clone to clicking around.

If you fork it, adapt the demo domain, deploy it for an account, or use it to unblock a customer conversation — please tell me what you built. The whole point is to take the pattern further than I will alone.

---

### Director's note for the blog

- The intro is the most-read part. The first paragraph names the problem in customer language; the second paragraph commits to the answer. Don't bury the lede with infrastructure details up front.
- The row filter SQL block is the most quoted moment. Make sure it renders cleanly in your blog platform's code styling.
- The "What I left out" section is the most divisive. Keep it. Reference solutions that try to ship everything are how every reference solution turns into a maintenance burden.
- For the social-share image, the Architecture tab's system diagram with all three call paths converging on the row filter is the strongest visual.
