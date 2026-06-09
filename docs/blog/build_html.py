#!/usr/bin/env python3
"""Assemble a self-contained, copy-paste-ready HTML version of the blog for Medium.

Images from diagrams/exports/web are base64-embedded at build time so the single
.html file renders with no external assets. Run:

    python3 docs/blog/build_html.py
"""
import base64
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
WEB = ROOT / "diagrams" / "exports" / "web"
OUT = ROOT / "docs" / "blog" / "databricks-is-all-you-need.html"

IMAGES = {
    "HERO": "hero-layer-cake.png",
    "FLOW": "end-to-end-flow.png",
    "HOME": "shot-home.jpg",
    "ASK": "shot-ask.jpg",
    "DASH": "shot-dashboard.jpg",
    "LOGIN": "shot-login.jpg",
    "CONSOLE": "shot-console.jpg",
    "FRONTDOOR": "shot-frontdoor.jpg",
}

MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}


def data_uri(filename: str) -> str:
    path = WEB / filename
    raw = path.read_bytes()
    b64 = base64.b64encode(raw).decode("ascii")
    mime = MIME[path.suffix.lower()]
    return f"data:{mime};base64,{b64}"


def fig(token: str, alt: str, caption: str) -> str:
    return (
        f'<figure>\n'
        f'  <img alt="{alt}" src="{{{{{token}}}}}" />\n'
        f'  <figcaption>{caption}</figcaption>\n'
        f'</figure>'
    )


ARTICLE = f"""<h1>Building a Customer-Facing OEM Analytics App on Databricks</h1>

<p><em>The views in this post are my own and do not represent the official stance of Databricks.</em></p>

{fig("HERO", "Layer-cake: you bring the skin, Databricks brings the rest",
     "Databricks is all you need\u2009\u2014\u2009you just bring the skin. The reasoning, dashboards, app database, hosting, and per-customer security were already in the platform.")}

<p><em>Databricks is all you need\u2009\u2014\u2009you just bring the skin. The reasoning, the dashboards, the app database, the hosting, and the per-customer security were already in the platform.</em></p>

<p>In my last post I called Genie from an API and got real answers back over HTTP. That was the &ldquo;huh, this actually works&rdquo; moment. This week I took the next step and shipped the whole thing as a product: a branded, multi-tenant OEM analytics app\u2009\u2014\u2009the kind a SaaS embeds for its own customers\u2009\u2014\u2009where each one logs in, asks questions in plain English, and opens live dashboards on their own data. It runs as a Databricks App. I wrote the front end and almost nothing else.</p>

<p>I want to make a simple case in this post. Building an end-to-end app is no longer the hard part, and doing it on Databricks makes a lot of sense, because the pieces you normally bolt together are already sitting in one place and already governed.</p>

{fig("FLOW", "End-to-end request flow diagram",
     "End-to-end request flow: customer \u2192 external front door (an edge Service Principal clears the Apps OAuth proxy) \u2192 branded login \u2192 React + FastAPI on Databricks Apps \u2192 Genie over Managed MCP and embedded AI/BI, each running as the per-tenant Service Principal \u2192 Unity Catalog row filter on the warehouse \u2192 Lakebase for app state.")}

<h2>Pick your coding agent. Deploy on Databricks.</h2>

<p>There are a lot of coding agents now, and people have strong opinions about which one to use. I&rsquo;m not going to add to that pile. Use the one you like. The interesting part isn&rsquo;t the agent you code with, it&rsquo;s where the thing lands when you&rsquo;re done.</p>

<p>For me that&rsquo;s Databricks, and the reason is boring in a good way: the data is already there, the permissions are already there, and the hosting is right next to both. I didn&rsquo;t stand up a warehouse, a separate auth service, a BI embed vendor, a vector store, an app database, and a cloud account to host it. I used what was already in the workspace.</p>

<p>Here&rsquo;s the same product the usual way versus this way:</p>

<table>
  <thead>
    <tr><th>What you need</th><th>The usual stack</th><th>On Databricks</th></tr>
  </thead>
  <tbody>
    <tr><td>Storage + governance</td><td>Warehouse + a permissions service</td><td>Unity Catalog + row filters</td></tr>
    <tr><td>Per-customer isolation</td><td><code>WHERE tenant_id = ?</code> in app code</td><td>A Service Principal per tenant + OAuth</td></tr>
    <tr><td>Embedded charts</td><td>Looker / Power BI embed</td><td>AI/BI dashboards</td></tr>
    <tr><td>Natural-language Q&amp;A</td><td>Build-your-own RAG</td><td>Genie, now over Managed MCP</td></tr>
    <tr><td>App database + users</td><td>A separate Postgres</td><td>Lakebase</td></tr>
    <tr><td>Hosting</td><td>Your cloud</td><td>Databricks Apps</td></tr>
    <tr><td>The skin and the login</td><td>Your front end</td><td>Your front end (the only thing you bring)</td></tr>
  </tbody>
</table>

<p>That last row is the whole point. The only column I owned was the front end.</p>

<p>And the front end isn&rsquo;t boxed in. Databricks Apps run the Python UI frameworks a lot of us reach for first, Streamlit, Dash, Gradio, and those are genuinely great for standing up an internal tool in an afternoon. But a customer-facing product usually wants more control over the experience than a script-driven layout gives you, and Apps will just as happily serve a full single-page application. This one is a React app built with Vite and TypeScript, styled with Tailwind and shadcn/ui, talking to a FastAPI backend, with client-side routing, a branded login, charting, and the embedded dashboard SDK. That&rsquo;s a much richer user experience: real navigation, animated transitions, optimistic loading, a design system you control end to end. You&rsquo;re not choosing Databricks at the cost of the front end you&rsquo;d build anywhere else. You get that front end and the governed data sits right behind it.</p>

{fig("HOME", "The product home, scoped to one tenant",
     "The product home\u2009\u2014\u2009branded hero, the &ldquo;ask anything&rdquo; bar, KPI tiles, and the spend-over-time chart, all scoped to one tenant.")}

<h2>From Genie-as-API to Genie over MCP</h2>

<p>The prior post used Genie&rsquo;s Conversation API directly. It works well. The new piece is that the same Genie space is also reachable over Databricks Managed MCP.</p>

<p>I want to be precise here, because this is easy to overclaim. My app does not run a model or an agent to use MCP. There&rsquo;s no LLM hosted in the app, no tool-calling loop I maintain. The app calls the Genie MCP server&rsquo;s tools directly: as the tenant Service Principal, it lists what the space exposes, calls <code>query_space</code> with the question, and polls <code>poll_response</code> until the answer is ready. The natural-language-to-SQL reasoning happens inside Genie. My app is a thin, governed client over the MCP protocol, and that&rsquo;s the whole appeal: nothing to manage on my side, no model weights, no prompt to babysit, no agent that can wander off.</p>

<p>So why use MCP instead of the REST endpoint at all? It&rsquo;s the standard, governed protocol Databricks exposes for this, the request still routes through the same Genie space with the same instructions and data context, and it still honors Unity Catalog permissions on the way through. It&rsquo;s also the seam where a tool-calling agent could plug in later and use Genie alongside other governed tools, without changing any of the isolation below it. I&rsquo;m just not running that agent today.</p>

<p>The practical part: I kept both transports. A feature flag, <code>MT_GENIE_TRANSPORT</code>, switches the app between REST and Managed MCP without touching the front end. Same question, same isolation guarantees, different path under the hood. Being able to A/B them in a running app made it easy to trust the MCP path before committing to it.</p>

{fig("ASK", "An Ask turn over Managed MCP",
     "An Ask turn over Genie Managed MCP\u2009\u2014\u2009the natural-language answer, the auto-generated chart, and the expanded request-flow inspector. Step 4 is the Unity Catalog row filter.")}

<h2>Embedding the dashboards, not rebuilding them</h2>

<p>For the dashboard side I didn&rsquo;t want to hand-roll charts that drift from what the customer would see in Databricks. So I embedded the real AI/BI dashboard with the <code>@databricks/aibi-client</code> SDK.</p>

<p>The part that matters for a customer-facing app is how the embed authenticates. I publish the dashboard with <code>embed_credentials=false</code>, and the app mints a short-lived token server-side as the tenant&rsquo;s Service Principal. The embedded dashboard&rsquo;s queries then run as that SP, the warehouse applies the row filter, and the customer sees only their rows. It&rsquo;s the same isolation as the chat path, enforced one layer down in the warehouse.</p>

{fig("DASH", "Embedded AI/BI dashboard under the brand skin",
     "Embedded AI/BI\u2009\u2014\u2009the native Databricks dashboard inside the app shell, under the brand skin, with the Databricks logo hidden.")}

<p><strong>One thing worth noting:</strong> that <code>embed_credentials=false</code> is load-bearing, and it&rsquo;s the step that bit me. If you publish the dashboard with embedded credentials, it runs as you, the publisher, and every tenant sees the full dataset. The row filter never gets a chance to engage. Publish without embedded credentials, grant each tenant SP <code>CAN RUN</code>, and let the warehouse do the scoping.</p>

<h2>Lakebase is the app&rsquo;s database</h2>

<p>A real app needs a transactional database. Logins, the customer-to-tenant mapping, the Service Principal records, an audit trail. That&rsquo;s OLTP, not analytics, and I didn&rsquo;t want to run a separate Postgres somewhere off to the side.</p>

<p>Lakebase is Postgres, managed, sitting in the same platform as the data and the app. I used it for exactly the app metadata you&rsquo;d expect: the customer registry, the per-tenant SP credentials (encrypted at rest), the app users, and an audit log of every lifecycle action. The app binds to it as a resource and connects with a token minted at request time, so there&rsquo;s no long-lived database password living in the app config.</p>

<p>This is the quiet workhorse of the whole thing. Analytics queries go to the warehouse through Genie and the dashboards; the app&rsquo;s own state lives in Lakebase. One platform, two storage shapes, no glue.</p>

<h2>The login layer, and why Service Principals do the heavy lifting</h2>

{fig("LOGIN", "The branded login",
     "The branded login\u2009\u2014\u2009the skin with seeded per-client demo logins, so the login already maps each user to a tenant.")}

<p>Databricks Apps run with an identity and support on-behalf-of access, so the app can act with the right scope instead of one god-account doing everything. On top of that I added a thin login layer in the app itself: app users with hashed passwords and a signed session cookie, completely separate from workspace identity. That models how a real SaaS gates its own end users, and it&rsquo;s where you&rsquo;d later wire in your real identity provider.</p>

<p>But the login isn&rsquo;t the security boundary. The Service Principals are. Every customer gets their own SP, and every query, whether it comes from the chat or the embedded dashboard, runs as that customer&rsquo;s SP. A Unity Catalog row filter keyed on <code>session_user()</code> does the scoping in the warehouse. If my app code had a bug and asked for the wrong tenant, the filter would still hold, because the data layer, not the app layer, decides what each SP can see. I find that a much calmer place to put the boundary than a <code>WHERE</code> clause I have to get right on every query.</p>

<p>The lifecycle of those SPs, creating them, rotating secrets, deactivating, auditing, turned out to be the real engineering, and it&rsquo;s tucked behind an operator console. The row-filter SQL is one line. Running it safely for every customer over time is the actual product.</p>

{fig("CONSOLE", "The operator console",
     "The operator console\u2009\u2014\u2009the tenant list with status, plus the isolation-verification and backfill-grants actions.")}

<h2>The front door, and a second Service Principal</h2>

<p>There&rsquo;s one more wrinkle in &ldquo;customer-facing.&rdquo; A Databricks App sits behind the platform&rsquo;s OAuth proxy. That&rsquo;s exactly right for internal users who already have Databricks SSO, but my customers don&rsquo;t have Databricks accounts and should never see a Databricks login screen. So I put a thin front door in front of the app: a small reverse proxy I host myself that owns the public origin, runs my own login, and brokers requests into the App.</p>

<p>That front door needs a way past the OAuth proxy, and this is where a <em>second</em> Service Principal earns its keep. The result is a two-tier SP design, and the split is deliberate:</p>

<ul>
  <li>A single <strong>edge SP</strong> is the doorman. Its only privilege is <code>CAN_USE</code> on the app. The front door presents its token to clear the proxy, and that is <em>all</em> it can do\u2009\u2014\u2009it can&rsquo;t read a table, touch Unity Catalog, or open a system table. If the internet-facing edge were ever compromised, the attacker gets a key to the lobby, not to the data.</li>
  <li>The <strong>per-tenant SPs</strong> keep doing the real work behind it. Every query still runs as the customer&rsquo;s own SP, the row filter still scopes it in the warehouse, and the system tables still attribute it per tenant. The front door changes how a customer <em>reaches</em> the app; it changes nothing about how their data is isolated once they&rsquo;re in.</li>
</ul>

<p>I tested this end to end by hosting the front door locally and signing in as a customer. The browser only ever talked to my origin\u2009\u2014\u2009never a Databricks URL, never an SSO redirect\u2009\u2014\u2009and the Ask still came back scoped to that one tenant&rsquo;s SP, with the same row-filter step in the inspector. Two tiers, two jobs: a minimal doorman out front, a per-customer identity for the data. It&rsquo;s the same instinct as the row filter\u2009\u2014\u2009keep the powerful credential away from the layer that faces the internet.</p>

{fig("FRONTDOOR", "Localhost as the front door",
     "Localhost as the front door\u2009\u2014\u2009the branded login on my own origin, with no Databricks SSO in the address bar.")}

<h2>Usage analytics you didn&rsquo;t have to build</h2>

<p>Here&rsquo;s a side effect I didn&rsquo;t appreciate until the app was live. Because it runs on the platform, the usage analytics were already there. I didn&rsquo;t add an events table, a telemetry pipeline, or a product-analytics vendor.</p>

<p>Every query the app runs goes through the warehouse, every login and admin action is an audited event, and every bit of compute is metered. That activity lands in Unity Catalog system tables: audit events in <code>system.access.audit</code>, warehouse activity in <code>system.query.history</code>, and DBU and cost in <code>system.billing.usage</code>. So &ldquo;who used what, how often, and what did it cost&rdquo; is one SQL query away, with nothing extra wired into the app.</p>

<p>The per-tenant design makes this better. Each customer queries as their own Service Principal, so the query-history and audit rows are already tagged by tenant identity. Grouping usage by SP gives me per-customer adoption and cost without instrumenting anything. I can even point a Genie space or an AI/BI dashboard at those system tables and watch the product&rsquo;s own usage the same way my customers watch theirs.</p>

<h2>What this isn&rsquo;t</h2>

<p>This is a reference app, not a finished SaaS. The thin login is demo-grade on purpose. There&rsquo;s no customer-facing billing or plan enforcement in the app itself, though the raw usage to build it on is already in the system tables above. It runs against a single Genie space and one domain of sample data. The front door I tested is local and single-origin; in production you&rsquo;d run it on your own domain over TLS, wire your real identity provider into it, and isolate cookies the way the Firefly proxy docs call out (their reference proxy is explicitly dev/demo-only on a shared domain). If you took this further you&rsquo;d also add per-customer rate limiting and think harder about secret rotation cadence. The pattern holds; the hardening is yours.</p>

<p>I&rsquo;ll also be honest about how it was built: I vibe-coded a large chunk of it, so you don&rsquo;t have to. The point of sharing it is that the platform did the load-bearing work, not that I wrote especially clever code.</p>

<h2>Where this fits</h2>

<p>A lot of the structure here follows <a href="https://www.firefly-analytics.com/">Firefly Analytics</a> (now in <a href="https://github.com/databrickslabs/firefly">databrickslabs</a>), the built-on multi-tenant reference. Firefly&rsquo;s model is SSO-SPN: users sign in through your own OIDC provider, and every Databricks call runs as <strong>one Service Principal per organization</strong>, with the SP credentials encrypted at rest in the app&rsquo;s Postgres and tokens minted and refreshed server-side. That per-org SP is exactly my per-tenant SP, and the encrypted-creds-in-Lakebase, refresh-ahead-of-expiry handling is the same. Firefly also documents an <strong>Apps Proxy</strong>\u2009\u2014\u2009an external proxy that injects a token so end users can reach an embedded Databricks App without ever seeing Databricks SSO\u2009\u2014\u2009and that&rsquo;s the idea behind my front door. The edge-SP-versus-per-tenant-SP split above is my own adaptation of that proxy idea for a Databricks App; Firefly keeps user identity and Databricks access in two <em>layers</em> rather than two SP tiers. If you want a deeper, more complete reference after this post, that&rsquo;s the one to read.</p>

<p>This is the second post in a short series on the idea that, for an embedded analytics product, Databricks is most of the stack. The first post was Genie as an API. This one adds Managed MCP, embedding, Lakebase, and the app shell. Future posts go deeper on the isolation proof and the operator console.</p>

<h2>Try it</h2>

<p>The whole thing is on GitHub: <a href="https://github.com/rohit-db/multi-tenant-genie">github.com/rohit-db/multi-tenant-genie</a>. There&rsquo;s a one-shot deploy script that builds the front end, provisions Lakebase, binds the resources, applies the grants, and ships the Databricks App:</p>

<pre><code>PROFILE=&lt;your-cli-profile&gt; \\
CATALOG=&lt;your-catalog&gt; \\
GENIE_SPACE_ID=&lt;your-genie-space&gt; \\
WAREHOUSE_ID=&lt;your-warehouse&gt; \\
bash scripts/deploy.sh</code></pre>

<p>If you&rsquo;ve built a customer-facing app on top of Genie or AI/BI embedding, I&rsquo;d like to hear how you handled per-customer isolation. Did you put the boundary in app code, or push it down to the warehouse the way I did here?</p>

<hr />

<p><em>Rohit Bhagwat is a Solutions Architect at Databricks. Opinions are my own.</em></p>

<p><em>The ideas here are my own; I used AI to help polish the writing.</em></p>
"""

STYLE = """
  :root { color-scheme: light; }
  body {
    font-family: Georgia, 'Times New Roman', serif;
    color: #242424;
    line-height: 1.58;
    font-size: 20px;
    max-width: 720px;
    margin: 0 auto;
    padding: 48px 24px 96px;
    background: #fff;
  }
  h1 { font-family: -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif;
       font-size: 40px; line-height: 1.15; letter-spacing: -0.02em; margin: 0 0 0.4em; }
  h2 { font-family: -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif;
       font-size: 28px; line-height: 1.2; letter-spacing: -0.02em; margin: 1.8em 0 0.4em; }
  p { margin: 0 0 1.2em; }
  a { color: #1a73e8; }
  figure { margin: 2em 0; text-align: center; }
  figure img { max-width: 100%; height: auto; border-radius: 6px;
               box-shadow: 0 1px 4px rgba(0,0,0,0.12); }
  figcaption { font-family: -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif;
               font-size: 14px; color: #6b6b6b; margin-top: 0.6em; line-height: 1.4; }
  table { border-collapse: collapse; width: 100%; font-family: -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif;
          font-size: 15px; margin: 1.5em 0; }
  th, td { border: 1px solid #e0e0e0; padding: 8px 12px; text-align: left; vertical-align: top; }
  th { background: #fafafa; }
  code { font-family: 'SF Mono', Menlo, Consolas, monospace; font-size: 0.85em;
         background: #f2f2f2; padding: 0.12em 0.35em; border-radius: 4px; }
  pre { background: #f6f8fa; border: 1px solid #e0e0e0; border-radius: 8px;
        padding: 16px 18px; overflow-x: auto; }
  pre code { background: none; padding: 0; font-size: 14px; line-height: 1.5; }
  ul { margin: 0 0 1.2em; padding-left: 1.4em; }
  li { margin: 0 0 0.6em; }
  hr { border: none; border-top: 1px solid #e0e0e0; margin: 2.5em 0; }
"""


def main() -> None:
    html_body = ARTICLE
    for token, filename in IMAGES.items():
        html_body = html_body.replace(f"{{{{{token}}}}}", data_uri(filename))

    doc = (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n"
        "<meta charset=\"utf-8\" />\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />\n"
        "<title>Building a Customer-Facing OEM Analytics App on Databricks</title>\n"
        f"<style>{STYLE}</style>\n"
        "</head>\n<body>\n"
        f"{html_body}\n"
        "</body>\n</html>\n"
    )
    OUT.write_text(doc, encoding="utf-8")
    size_kb = OUT.stat().st_size // 1024
    print(f"Wrote {OUT}  ({size_kb} KB)")


if __name__ == "__main__":
    main()
