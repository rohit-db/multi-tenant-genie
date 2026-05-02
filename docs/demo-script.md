# Demo Script + Blog Draft

Two artifacts for sharing the multi-tenant Genie reference with your team:

- **Section 1** — a tight 10-minute screen-recording script with stage directions and narration.
- **Section 2** — a long-form blog draft you can adapt for an internal post.

---

## Section 1 — 10-Minute Demo Script

**Format:** screen recording with voiceover. App URL: `https://multi-tenant-genie-7474655568396905.aws.databricksapps.com` (FEVM deploy). Default tenant: Acme Industrial.

**Before recording:**
- Open the app, land on Portal tab. Confirm Acme Industrial is selected.
- Have a tab/window with the repo open as a backup reference.
- Close any chat-app or notification windows.

---

### 0:00 — 0:30 · Hook

**On screen:** Portal tab, default landing page, dashboard fully loaded.

> "Most teams asking me about embedding Genie are building something that looks like this. A customer-facing data app — branded portal, charts driven by their data, a chat assistant that answers questions in plain English. The dashboard is the easy part. The hard part is making sure tenant A never sees tenant B's data, even when they share the same workspace, the same warehouse, and the same Genie space.
>
> This is a reference solution that solves that. It's a fork-and-adapt repo. Let me show you what it does, how it works, and how to take it."

---

### 0:30 — 1:30 · The pattern in action

**On screen:** Portal tab, Acme Industrial selected. Use the "Acting as" dropdown to switch to Nike. Pause. Switch to CloudVenture. Pause. Switch back to Acme.

> "I'm currently signed in as Acme Industrial. Two hundred bookings. Half a million in spend. Top route is Austin to Denver.
>
> I'll switch tenants. Same dashboard, same SQL queries running underneath — but Nike's numbers are completely different. CloudVenture's are different again.
>
> I haven't changed any code. I haven't changed any prompts. The proxy minted a different OAuth token for each tenant, and Unity Catalog's row filter scoped every query to that tenant's rows. The isolation isn't in the model or the prompt — it's in the warehouse."

---

### 1:30 — 3:00 · Why this matters + how it works

**On screen:** Briefly switch to the Architecture tab. Scroll to the system architecture diagram. Then scroll down to "Row filter — live SQL".

> "Here's why this matters. If you've tried multi-tenant Genie before, you've probably either (a) used dynamic views and hit performance issues, or (b) tried to filter at the prompt layer, which is non-deterministic and not auditable.
>
> What you actually want is a single, deterministic, SQL-level enforcement point that doesn't depend on the model behaving correctly. Unity Catalog row filters give you that. This is the function that's deployed in UC right now."

**Highlight the row filter SQL on screen.**

> "When any tenant SP queries a governed table, this function runs. It joins `sp_tenant_mapping` on `session_user()` — which resolves to the SP's application ID inside UC. The mapping says which tenant_id this SP is allowed to see, and that's the only filter that gets applied. No `WHERE tenant_id = something` in the proxy code. No prompt instruction. UC enforces it.
>
> One Service Principal per tenant. One row filter, deployed once. That's the whole pattern."

---

### 3:00 — 4:30 · Genie chat + the inspector

**On screen:** Back to Portal tab. Click the **Chat** button in the header. Panel slides in.

> "On the Portal, the chat panel is Genie. Tenant types a natural-language question. Genie generates SQL. UC row filter applies. Watch."

**Type:** "What was my busiest month?" Hit send. Wait for response.

> "Genie wrote the SQL. UC trimmed it to Acme's rows. Answer comes back grounded in real data."

**Close chat panel. Switch to the Isolation proof tab. Pick Acme. Type the same question or use a sample chip. Click Ask Genie.**

> "Same question on the Isolation proof tab. The difference here is the inspector — six steps run on every ask, and you can see what's actually on the wire."

**Click step 1 "Authenticate".**

> "Step 1 — proxy looks up the tenant in Lakebase. Here's the actual SQL it ran. Here's the Lakebase host."

**Click step 4 "Apply row filter" (amber).**

> "Step 4 is the load-bearing one. The row filter ran in the warehouse for *this* SP. This is the enforcement point. The proxy doesn't get to decide what the tenant can see. UC does."

**Close the inspector. Switch back to Portal.**

---

### 4:30 — 6:30 · Custom agent

**On screen:** Portal tab, Acme. Click the **Insights agent** button. Panel slides in.

> "Most of what people are actually building now isn't just a chatbot — it's a custom agent. Multiple tools, planning, synthesis. The good news is the same isolation pattern works."

**Point at the agent panel description.**

> "This is a small custom agent — three steps. Plan, execute, synthesize.
>
> Step one — Foundation Model API picks two or three SQL queries that would help answer the focus area.
> Step two — each query runs through the proxy as Acme's Service Principal. Same OAuth token Genie would use. Same row filter applies.
> Step three — Foundation Models takes the results and writes a recommendation.
>
> Watch."

**Pick or type a focus area like "Where am I spending the most and what's growing fastest?" Click Run insights. Wait ~10-15 seconds.**

> "There's the agent's plan — one sentence on what it's looking for.
>
> Three tool calls. I'll expand the first one."

**Click to expand a tool call.**

> "Here's the actual SQL the agent wrote. Here's the result table — Acme's rows only. If I switched to Nike and reran, I'd get Nike's rows.
>
> And here's the synthesized recommendation, grounded in those numbers.
>
> The agent could be doing anything — anomaly detection, recommendation, multi-turn tool use through LangGraph or the OpenAI Agents SDK. The isolation guarantee comes from the SP token, not the agent framework. Same pattern Genie uses, applied to anything you build."

**Close panel.**

---

### 6:30 — 7:30 · Operating it

**On screen:** Switch to Admin tab.

> "On the Admin tab — operating the platform. The numbers strip is computed live from the audit log. Active tenants. Queries last hour. Latency. Errors.
>
> Tenant table — every onboard is a single click. The proxy creates the SP, mints an OAuth secret, encrypts it in Lakebase with AES-GCM, inserts the UC mapping row, grants UC access, grants Genie access. All transactional — if any step fails, it rolls back."

**Click Verify isolation.**

> "And the proof point — Verify isolation runs through every active tenant, executes a query as that tenant against the bookings table, and asserts each one only sees its own rows. This is the test that has to be green for the whole thing to mean anything."

**Wait for verify results.**

> "All passing. There's a bulk onboard path for thousands of tenants too — paste a CSV, get a job ID back, poll for progress."

---

### 7:30 — 8:30 · Architecture

**On screen:** Switch to Architecture tab. Scroll to the system architecture diagram.

> "Here's the whole architecture in one picture.
>
> Three call paths from the tenant — Genie, direct SQL for the dashboard widgets, and the custom agent. All three converge on the same OAuth M2M minter. All three end up running SQL as the tenant SP through the warehouse. UC's row filter is the single enforcement point.
>
> Lakebase holds the operational metadata — tenant registry, encrypted credentials, audit log. UC holds the governed data and the mapping table the row filter joins.
>
> If you remember one thing from this video, remember this: the row filter is the line between tenant A and tenant B. Everything else is plumbing."

---

### 8:30 — 9:30 · Take it

**On screen:** Switch to a terminal or repo view if you have one. Otherwise stay on the app and reference the URL verbally.

> "Repo's at github dot com slash rohit-db slash multi-tenant-genie. Branch is `generalize-and-scale`.
>
> There's a `scripts/deploy.sh` that does the whole thing in one command. Lakebase instance, secret scope, app SP, UC grants — all of it. I deployed this against a fresh FEVM workspace in 90 seconds."

**Show the README briefly if convenient.**

> "Pre-reqs: a serverless workspace, a SQL warehouse, a Genie space, the databricks CLI authed. That's it. Run the script, open the URL, click Onboard. Working multi-tenant Genie demo, less than two minutes."

---

### 9:30 — 10:00 · Wrap

**On screen:** Back to Portal tab — clean view.

> "Three things to take away.
>
> One — UC row filters are the right enforcement layer for multi-tenant Genie. Not the model. Not the prompt. Not the application code.
>
> Two — the same SP-per-tenant pattern works for any AI agent you build. Genie, custom agents, third-party agents — they all converge on the same token, the same row filter, the same guarantee.
>
> Three — this is opinionated. Pattern A only. Lakebase for the operational store. UC for the data. Pattern B is documented as a future direction. Rate limits, multi-space UI, cost tracking — all listed in the future-directions doc.
>
> Fork it. Adapt the domain. Deploy it. Tell me what you build."

**End on the Portal page.**

---

### Director's notes

- **Total runtime:** about 10 minutes if you don't pause too long for clicks. If you cut the operating section (6:30-7:30) you can hit 8 minutes for a tighter version.
- **The two switch-tenants moments matter most** — the 0:30-1:30 section where the dashboard numbers visibly change. Don't rush it. Let the audience see same-question-different-answer.
- **The agent demo is the new hook** — most people watching have seen Genie demos. The "same pattern, custom agent" moment is what makes this re-shareable.
- **Don't apologize for opinions.** Pattern A only, Lakebase for OLTP, no Pattern B yet — those are deliberate. State them clearly.

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
