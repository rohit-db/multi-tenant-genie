# Multi-Tenant Genie — Video Script

**Target length:** ~3:00 · **Audience:** Ajay Singh (BCD), Advito + Persistent engineering teams
**App URL:** http://localhost:5173

Stage directions in `[brackets]`, spoken text in plain English. Aim for a relaxed pace.

---

## 0:00 — Intro (15s)

`[Full screen — app loaded on Client View tab]`

> "Hey Ajay — quick walkthrough of the multi-tenant Genie prototype. The idea is: one service principal per client organization, and Unity Catalog row filters do the isolation — not prompts, not the application. Let me show you what that looks like end-to-end."

---

## 0:15 — Isolation, as a client (40s)

`[Client View tab — already open]`

> "This is what a client-side call looks like. I pick a tenant from the dropdown — let's start with **Nike**."

`[Select "Nike" from the "I am…" dropdown. Keep default question.]`

> "I'm now authenticating as Nike's service principal. I'll ask: *How many bookings do I have and what's my total spend?*"

`[Click "Ask Genie". Wait ~8s for the answer to load.]`

> "200 bookings, about $509K. Good. Now watch what happens when I ask the same question as a different client."

`[Change dropdown to "CloudVenture". Click "Ask Genie" again.]`

> "200 bookings again — but different numbers. $505K this time. Same table, same question, Genie generated the same SQL — but the row filter gave each client only their data."

---

## 0:55 — The money shot: isolation sweep (35s)

`[Click "Isolation sweep (all tenants)".]`

> "Let me make this obvious. I'll run the same question as every active client in parallel."

`[Wait ~10s for cards to render.]`

> "There it is. Four tenants, four different answers. Nike, Acme, CloudVenture — each shows their own 200 bookings with their own spend totals. And the fourth tenant here — 'Databricks' — I onboarded earlier and never seeded any data, so it correctly returns zero bookings. The filter denies by default. That's what deterministic isolation looks like."

---

## 1:30 — Admin: SP lifecycle (40s)

`[Click the "Admin" tab.]`

> "This is the admin side. Here are the client organizations, the service principals behind them, and a live audit log of every operation."

`[Point at the stat cards, then the table.]`

> "I can rotate any client's OAuth secret with zero downtime — the new secret is stored before the old one is deleted, so in-flight tokens keep working until they naturally expire. And I can deactivate a client in one click, which disables their service principal and flips the mapping off — any stale token gets zero rows immediately."

`[Click "Onboard tenant" to open the dialog.]`

> "Onboarding a new client is one click. The platform creates the service principal, mints its secret, stores it, grants access on Unity Catalog and the Genie Space, and inserts the mapping row."

`[Close the dialog without submitting — or submit if you want to show it live.]`

---

## 2:10 — Architecture: how it works (40s)

`[Click the "Architecture" tab. Scroll to "Sequence flows".]`

> "Last thing — here's what's actually happening under the hood. Four flows."

`[Point at the tabs: Admin onboarding / Client → Genie / Rotate / Deactivate.]`

> "Every arrow in these diagrams is a real HTTP call. Let me show you the client call flow."

`[Click "Client → Genie" tab.]`

> "The app exchanges the tenant's credentials at the OIDC endpoint, gets an access token, calls Genie with it. Inside Unity Catalog, `session_user()` resolves to the service principal's ID — and that's what the row filter joins against. Genie never sees the filter. It generates one SQL query, UC returns only the allowed rows."

`[Scroll down to the Live Mapping Table and the Row Filter SQL block.]`

> "And here's the mapping table and the row filter SQL deployed in the workspace right now. This is the only thing between a client and someone else's data. It's deterministic — no LLM is in the enforcement path."

---

## 2:50 — Close (15s)

`[Stay on Architecture tab or go back to Client View for a clean end frame.]`

> "Everything I just showed works today with GA Databricks primitives. Pattern scales to thousands of client organizations — both Advito's embedded use case and the broader BCD Decision Source and CSS workloads. Happy to dig in deeper with you, Sai, Deepak, and the Persistent team whenever works. Thanks!"

---

## Pacing tips

- Record a dry run once to feel the rhythm — aim for **3:00–3:15**.
- If you fumble, just pause and restart the sentence; Loom trims cleanly.
- The **isolation sweep** is your wow moment — wait a beat after the four cards land before you start talking. Let it sink in.
- The **"Databricks tenant shows 0 bookings"** line is the strongest proof — deliver it slow.

## Pre-recording checklist

- [ ] Browser window at ~1280px wide (stat cards and sweep grid fit nicely)
- [ ] FastAPI running on :8000, Vite on :5173
- [ ] Start on Client View tab with default question in the textbox
- [ ] Genie Space warmed up (ask one throwaway question beforehand)
- [ ] Mic check — no background apps pinging notifications
- [ ] Close any tabs with sensitive info showing in the tab title bar
