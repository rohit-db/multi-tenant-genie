# Building a Customer-Facing OEM Analytics App on Databricks

### By Rohit Bhagwat

**9 min read · June 5, 2026**

---

_Databricks is all you need — you just bring the skin. The reasoning, the dashboards, the app database, the hosting, and the per-customer security were already in the platform._

In my last post I called Genie from an API and got real answers back over HTTP. That was the "huh, this actually works" moment. This week I took the next step and shipped the whole thing as a product: a branded, multi-tenant OEM analytics app — the kind a SaaS embeds for its own customers — where each one logs in, asks questions in plain English, and opens live dashboards on their own data. It runs as a Databricks App. I wrote the front end and almost nothing else.

I want to make a simple case in this post. Building an end-to-end app is no longer the hard part, and doing it on Databricks makes a lot of sense, because the pieces you normally bolt together are already sitting in one place and already governed.

> The views in this post are my own and do not represent the official stance of Databricks.

*[High-level architecture diagram — space reserved. One picture of the whole flow: customer → external front door (an edge Service Principal clears the Apps OAuth proxy) → branded login → app (React + FastAPI on Databricks Apps) → Genie over Managed MCP and embedded AI/BI, each running as the per-tenant Service Principal → Unity Catalog row filter on the warehouse → Lakebase for app state. Show the two SP tiers explicitly: one edge/doorman SP out front, N per-tenant data SPs behind it. Use this as the featured image too.]*

## Pick your coding agent. Deploy on Databricks.

There are a lot of coding agents now, and people have strong opinions about which one to use. I'm not going to add to that pile. Use the one you like. The interesting part isn't the agent you code with, it's where the thing lands when you're done.

For me that's Databricks, and the reason is boring in a good way: the data is already there, the permissions are already there, and the hosting is right next to both. I didn't stand up a warehouse, a separate auth service, a BI embed vendor, a vector store, an app database, and a cloud account to host it. I used what was already in the workspace.

Here's the same product the usual way versus this way:

| What you need | The usual stack | On Databricks |
|---|---|---|
| Storage + governance | Warehouse + a permissions service | Unity Catalog + row filters |
| Per-customer isolation | `WHERE tenant_id = ?` in app code | A Service Principal per tenant + OAuth |
| Embedded charts | Looker / Power BI embed | AI/BI dashboards |
| Natural-language Q&A | Build-your-own RAG | Genie, now over Managed MCP |
| App database + users | A separate Postgres | Lakebase |
| Hosting | Your cloud | Databricks Apps |
| The skin and the login | Your front end | Your front end (the only thing you bring) |

That last row is the whole point. The only column I owned was the front end.

And the front end isn't boxed in. Databricks Apps run the Python UI frameworks a lot of us reach for first, Streamlit, Dash, Gradio, and those are genuinely great for standing up an internal tool in an afternoon. But a customer-facing product usually wants more control over the experience than a script-driven layout gives you, and Apps will just as happily serve a full single-page application. This one is a React app built with Vite and TypeScript, styled with Tailwind and shadcn/ui, talking to a FastAPI backend, with client-side routing, a branded login, charting, and the embedded dashboard SDK. That's a much richer user experience: real navigation, animated transitions, optimistic loading, a design system you control end to end. You're not choosing Databricks at the cost of the front end you'd build anywhere else. You get that front end and the governed data sits right behind it.

*[Screenshot — the product home: branded hero, the "ask anything" bar, KPI tiles, and the spend-over-time chart, all scoped to one tenant.]*

## From Genie-as-API to Genie over MCP

The prior post used Genie's Conversation API directly. It works well. The new piece is that the same Genie space is also reachable over Databricks Managed MCP.

I want to be precise here, because this is easy to overclaim. My app does not run a model or an agent to use MCP. There's no LLM hosted in the app, no tool-calling loop I maintain. The app calls the Genie MCP server's tools directly: as the tenant Service Principal, it lists what the space exposes, calls `query_space` with the question, and polls `poll_response` until the answer is ready. The natural-language-to-SQL reasoning happens inside Genie. My app is a thin, governed client over the MCP protocol, and that's the whole appeal: nothing to manage on my side, no model weights, no prompt to babysit, no agent that can wander off.

So why use MCP instead of the REST endpoint at all? It's the standard, governed protocol Databricks exposes for this, the request still routes through the same Genie space with the same instructions and data context, and it still honors Unity Catalog permissions on the way through. It's also the seam where a tool-calling agent could plug in later and use Genie alongside other governed tools, without changing any of the isolation below it. I'm just not running that agent today.

The practical part: I kept both transports. A feature flag, `MT_GENIE_TRANSPORT`, switches the app between REST and Managed MCP without touching the front end. Same question, same isolation guarantees, different path under the hood. Being able to A/B them in a running app made it easy to trust the MCP path before committing to it.

*[Screenshot — an Ask turn: the natural-language answer, the auto-generated chart, and the expanded request-flow inspector showing the row-filter step. Worth a second shot showing the same question for two tenants returning different numbers.]*

## Embedding the dashboards, not rebuilding them

For the dashboard side I didn't want to hand-roll charts that drift from what the customer would see in Databricks. So I embedded the real AI/BI dashboard with the `@databricks/aibi-client` SDK.

The part that matters for a customer-facing app is how the embed authenticates. I publish the dashboard with `embed_credentials=false`, and the app mints a short-lived token server-side as the tenant's Service Principal. The embedded dashboard's queries then run as that SP, the warehouse applies the row filter, and the customer sees only their rows. It's the same isolation as the chat path, enforced one layer down in the warehouse.

*[Screenshot — the embedded native AI/BI dashboard inside the app shell, under the brand skin, with the Databricks logo hidden.]*

**One thing worth noting:** that `embed_credentials=false` is load-bearing, and it's the step that bit me. If you publish the dashboard with embedded credentials, it runs as you, the publisher, and every tenant sees the full dataset. The row filter never gets a chance to engage. Publish without embedded credentials, grant each tenant SP `CAN RUN`, and let the warehouse do the scoping.

## Lakebase is the app's database

A real app needs a transactional database. Logins, the customer-to-tenant mapping, the Service Principal records, an audit trail. That's OLTP, not analytics, and I didn't want to run a separate Postgres somewhere off to the side.

Lakebase is Postgres, managed, sitting in the same platform as the data and the app. I used it for exactly the app metadata you'd expect: the customer registry, the per-tenant SP credentials (encrypted at rest), the app users, and an audit log of every lifecycle action. The app binds to it as a resource and connects with a token minted at request time, so there's no long-lived database password living in the app config.

This is the quiet workhorse of the whole thing. Analytics queries go to the warehouse through Genie and the dashboards; the app's own state lives in Lakebase. One platform, two storage shapes, no glue.

## The login layer, and why Service Principals do the heavy lifting

*[Screenshot — the branded login: the SkyDesk skin with the seeded per-client demo logins, so the login already maps each user to a tenant.]*

Databricks Apps run with an identity and support on-behalf-of access, so the app can act with the right scope instead of one god-account doing everything. On top of that I added a thin login layer in the app itself: app users with hashed passwords and a signed session cookie, completely separate from workspace identity. That models how a real SaaS gates its own end users, and it's where you'd later wire in your real identity provider.

But the login isn't the security boundary. The Service Principals are. Every customer gets their own SP, and every query, whether it comes from the chat or the embedded dashboard, runs as that customer's SP. A Unity Catalog row filter keyed on `session_user()` does the scoping in the warehouse. If my app code had a bug and asked for the wrong tenant, the filter would still hold, because the data layer, not the app layer, decides what each SP can see. I find that a much calmer place to put the boundary than a `WHERE` clause I have to get right on every query.

The lifecycle of those SPs, creating them, rotating secrets, deactivating, auditing, turned out to be the real engineering, and it's tucked behind an operator console. The row-filter SQL is one line. Running it safely for every customer over time is the actual product.

*[Screenshot — the operator console: the tenant list with status, plus the isolation-verification / backfill-grants actions.]*

## The front door, and a second Service Principal

There's one more wrinkle in "customer-facing." A Databricks App sits behind the platform's OAuth proxy. That's exactly right for internal users who already have Databricks SSO, but my customers don't have Databricks accounts and should never see a Databricks login screen. So I put a thin front door in front of the app: a small reverse proxy I host myself that owns the public origin, runs my own login, and brokers requests into the App.

That front door needs a way past the OAuth proxy, and this is where a *second* Service Principal earns its keep. The result is a two-tier SP design, and the split is deliberate:

- A single **edge SP** is the doorman. Its only privilege is `CAN_USE` on the app. The front door presents its token to clear the proxy, and that is *all* it can do — it can't read a table, touch Unity Catalog, or open a system table. If the internet-facing edge were ever compromised, the attacker gets a key to the lobby, not to the data.
- The **per-tenant SPs** keep doing the real work behind it. Every query still runs as the customer's own SP, the row filter still scopes it in the warehouse, and the system tables still attribute it per tenant. The front door changes how a customer *reaches* the app; it changes nothing about how their data is isolated once they're in.

I tested this end to end by hosting the front door locally and signing in as a customer. The browser only ever talked to my origin — never a Databricks URL, never an SSO redirect — and the Ask still came back scoped to that one tenant's SP, with the same row-filter step in the inspector. Two tiers, two jobs: a minimal doorman out front, a per-customer identity for the data. It's the same instinct as the row filter — keep the powerful credential away from the layer that faces the internet.

*[Screenshot — the browser at the front door's own origin (e.g. localhost or your domain), the branded login, and the address bar showing no Databricks SSO. Worth a second shot of the request flow: front door → app → tenant SP.]*

## Usage analytics you didn't have to build

Here's a side effect I didn't appreciate until the app was live. Because it runs on the platform, the usage analytics were already there. I didn't add an events table, a telemetry pipeline, or a product-analytics vendor.

Every query the app runs goes through the warehouse, every login and admin action is an audited event, and every bit of compute is metered. That activity lands in Unity Catalog system tables: audit events in `system.access.audit`, warehouse activity in `system.query.history`, and DBU and cost in `system.billing.usage`. So "who used what, how often, and what did it cost" is one SQL query away, with nothing extra wired into the app.

The per-tenant design makes this better. Each customer queries as their own Service Principal, so the query-history and audit rows are already tagged by tenant identity. Grouping usage by SP gives me per-customer adoption and cost without instrumenting anything. I can even point a Genie space or an AI/BI dashboard at those system tables and watch the product's own usage the same way my customers watch theirs.

*[Screenshot — a usage dashboard built on system tables: queries and DBU per tenant SP over time. Or a quick `SELECT … FROM system.query.history` grouped by the tenant SPs.]*

## What this isn't

This is a reference app, not a finished SaaS. The thin login is demo-grade on purpose. There's no customer-facing billing or plan enforcement in the app itself, though the raw usage to build it on is already in the system tables above. It runs against a single Genie space and one domain of sample data. The front door I tested is local and single-origin; in production you'd run it on your own domain over TLS, wire your real identity provider into it, and isolate cookies the way the Firefly proxy docs call out (their reference proxy is explicitly dev/demo-only on a shared domain). If you took this further you'd also add per-customer rate limiting and think harder about secret rotation cadence. The pattern holds; the hardening is yours.

I'll also be honest about how it was built: I vibe-coded a large chunk of it, so you don't have to. The point of sharing it is that the platform did the load-bearing work, not that I wrote especially clever code.

## Where this fits

A lot of the structure here follows [Firefly Analytics](https://www.firefly-analytics.com/) (now in [databrickslabs](https://github.com/databrickslabs/firefly)), the built-on multi-tenant reference. Firefly's model is SSO-SPN: users sign in through your own OIDC provider, and every Databricks call runs as **one Service Principal per organization**, with the SP credentials encrypted at rest in the app's Postgres and tokens minted and refreshed server-side. That per-org SP is exactly my per-tenant SP, and the encrypted-creds-in-Lakebase, refresh-ahead-of-expiry handling is the same. Firefly also documents an **Apps Proxy** — an external proxy that injects a token so end users can reach an embedded Databricks App without ever seeing Databricks SSO — and that's the idea behind my front door. The edge-SP-versus-per-tenant-SP split above is my own adaptation of that proxy idea for a Databricks App; Firefly keeps user identity and Databricks access in two *layers* rather than two SP tiers. If you want a deeper, more complete reference after this post, that's the one to read.

This is the second post in a short series on the idea that, for an embedded analytics product, Databricks is most of the stack. The first post was Genie as an API. This one adds Managed MCP, embedding, Lakebase, and the app shell. Future posts go deeper on the isolation proof and the operator console.

## Try it

The whole thing is on GitHub: [github.com/rohit-db/multi-tenant-genie](https://github.com/rohit-db/multi-tenant-genie). There's a one-shot deploy script that builds the front end, provisions Lakebase, binds the resources, applies the grants, and ships the Databricks App:

```bash
PROFILE=<your-cli-profile> \
CATALOG=<your-catalog> \
GENIE_SPACE_ID=<your-genie-space> \
WAREHOUSE_ID=<your-warehouse> \
bash scripts/deploy.sh
```

If you've built a customer-facing app on top of Genie or AI/BI embedding, I'd like to hear how you handled per-customer isolation. Did you put the boundary in app code, or push it down to the warehouse the way I did here?

---

_Rohit Bhagwat is a Solutions Architect at Databricks. Opinions are my own._

_The ideas here are my own; I used AI to help polish the writing._
