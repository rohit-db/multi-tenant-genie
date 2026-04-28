# BCD Travel / Advito — Project Context

## Meeting Notes (Architecture Discussion)

### Stakeholders
- **Rohit Bhagwat** — Databricks SA (us)
- **Ryan** — Databricks (user provisioning / SCIM expertise)
- **Amit Vaze** — BCD (presented architecture)
- **VJ** — BCD/Advito (built current Genie function-based approach)
- **Stefan (Stessier)** — BCD (concerned about operational overhead of provisioning)
- **John** — Advito (AWS Cognito / Azure AD migration)

### Scale
- **~10,000 users** across **1,000+ customers** (~3,000-4,000 clients)
- Data isolation required at **company and GCN (Global Customer Number) levels**
- April pilot milestone

### Current Architecture
- **Authentication:** Azure AD B2C for external users; BCD Active Directory (SSO) for internal users
- **API layer:** Amazon Elastic Beanstalk
- **AI Agent:** Genie-based "AI Analyst" feature
- **Identity Providers:**
  - BCD: Azure AD B2C (some customers integrate their own SSO)
  - Advito: Currently AWS Cognito, exploring Azure AD migration
- **Databricks:** BCD and Advito share the same Databricks **account** but use different **workspaces**
- **User overlap:** Some users (travel managers) exist in both BCD and Advito with different access controls

### Current Genie Security Approach (VJ's Implementation)
VJ built a function-based approach for data isolation in Genie:
- Functions used as **data sources** (not filters)
- Customer ID mapping via functions
- Prompt-based instructions to enforce access
- Additional verification checks
- **Test results:** 80/81 unauthorized access attempts blocked

**Problem identified by Rohit:** This approach relies on three non-deterministic elements:
1. The function not being used as a filter (can be bypassed)
2. Effectiveness of the prompt (non-deterministic)
3. Additional verification checks

### Recommended Approach (From Meeting)
1. **Replace function-based approach with Unity Catalog row filters** — deterministic, enforced at query time
2. **Automate user provisioning** via SCIM or just-in-time (JIT) provisioning from Azure AD B2C
3. **Use mapping tables** in Databricks for user → customer → data access resolution
4. **Avoid managing 5,000 service principals** (VJ's concern) — use user provisioning instead

### Three Possible Approaches Discussed

| Approach | Description | Status |
|----------|-------------|--------|
| **A. User Provisioning (SCIM/JIT)** | Provision each user in Databricks via Azure AD B2C sync; UC row filters use `current_user()` | Ryan verifying JIT via API feasibility |
| **B. SP-per-Customer** | 1 SP per customer (~1,000-4,000 SPs); proxy maps user → customer → SP | VJ concerned about managing 5,000 SPs |
| **C. Shared SP + Custom Claims** | 1 SP with `custom_claim=<customer_id>`; UC row filters use `current_oauth_custom_identity_claims()` | Best scaling but verify Genie support |

### Open Questions (From Meeting)
1. **Can users be JIT-provisioned via API** when accessing Databricks indirectly through the BCD app? (Ryan to verify)
2. **SCIM operational impact** — what's the admin burden for 10,000 users? (Ryan to provide details)
3. **How to handle BCD + Advito user overlap** in a shared account with different workspaces?
4. **AWS Cognito → Databricks integration** for Advito (John exploring)
5. **Custom claims through Genie** — does `current_oauth_custom_identity_claims()` work in Genie-initiated queries?

### Next Steps (From Meeting)
- [ ] **Ryan:** Verify JIT user provisioning via API for indirect Databricks access
- [ ] **Ryan:** Share SCIM provisioning operational details with Stefan
- [ ] **Rohit + Ryan:** Share docs on automating provisioning from Azure AD B2C (and Cognito)
- [ ] **Rohit + Ryan:** Schedule follow-up on user/group sync between BCD and Advito
- [ ] **Rohit:** Help VJ set up UC table-level row filters (replacing function-based approach)
- [ ] **Rohit + Ryan:** Explore secret rotation automation if SP approach is pursued

## Honest Assessment of Approaches

### The Two Products Have Different Profiles

| | BCD Travel App | Advito |
|---|---|---|
| **Users** | ~10,000 across 1,000+ customers | ~600 |
| **IdP** | Azure AD B2C (external) + BCD AD (internal) | AWS Cognito (exploring Azure AD) |
| **User type** | External customers who never see Databricks | Mix of internal analysts + some external |
| **Workspace** | Shared account, separate workspace | Shared account, separate workspace |
| **Isolation** | Per-company / per-GCN | Per-user / per-client |

**Advito is straightforward:** 600 users → SCIM provisioning, UC row filters with `current_user()`. Standard pattern, well-supported, low operational risk. Done.

**BCD is the hard problem.** 10,000 external users who never touch Databricks, mediated through an Elastic Beanstalk proxy. Three approaches, each with real tradeoffs.

### Approach A: User Provisioning (SCIM/JIT) — Rohit's Push

**What's strong:**
- Cleanest identity model — each user is a real Databricks identity
- `current_user()` works natively in UC row filters, no custom claims dependency
- Standard pattern, well-supported
- Audit trail maps directly to users

**What's genuinely uncertain:**
1. **Azure AD B2C → Databricks SCIM is not well-trodden.** B2C is for consumer/external identities. Most Databricks SCIM integrations are with enterprise Azure AD (B2B) or Okta. Ryan hasn't confirmed this works cleanly — and there's a reason it's uncommon.
2. **10,000 Databricks identities for users who never log into Databricks.** These users interact through BCD's app. They'll never see the Databricks UI. Creating Databricks accounts purely for identity-to-row-filter mapping is an architectural smell — you're provisioning identities in a system users don't directly use.
3. **Ryan hasn't confirmed JIT provisioning via API for indirect access.** If this doesn't work, you need full SCIM sync upfront — exactly what Stefan pushed back on.
4. **User lifecycle management.** When a customer's employee leaves, BCD deactivates them in Azure AD B2C. Does that propagate to Databricks via SCIM? If there's drift (and there will be), you have stale Databricks accounts with active row filter access. Security problem.
5. **BCD + Advito user overlap.** SCIM from two IdPs (Azure AD B2C + Cognito) into the same account with overlapping emails is messy.

### Approach B: SP-per-Customer — The Fallback We Downplayed

**What's easy to automate (the honest version):**
- SP creation, workspace assignment, group membership, initial secret generation — all API calls, scriptable

**What's genuinely hard (the part we downplayed):**
- **Secret rotation at scale.** 1,000+ SPs × secrets with 730-day expiry × max 5 secrets per SP. You need a rotation service that tracks expiry, creates new secrets, updates the credential store, migrates sessions, and deletes old secrets — without downtime. This isn't a script, it's a service.
- **Sync drift.** SP→tenant mapping must be perfectly in sync. Any drift = data leakage or access denial. Needs reconciliation jobs.
- **Monitoring.** 1,000+ SPs to watch for anomalous activity. Audit queries get expensive.
- **Account-level limits.** Ibotta has 1,300+ SPs. Unclear if there's a soft cap.
- **Rate limits.** ~50 SP operations/min on account API. Bulk provisioning 1,000 SPs takes 20+ minutes.

**The honest framing for BCD:** "SP lifecycle management is automatable, but it's building and maintaining a dedicated identity management service — not a one-time script. Budget engineering effort accordingly."

### Approach C: Shared SP + Custom Claims — Best on Paper, Blocked in Practice

**Why it's the best architecture:**
- O(1) SP management
- Proxy already exists (Elastic Beanstalk)
- Onboarding = insert row in registry
- Row filters handle isolation transparently

**Why we can't recommend it today:**
- `current_oauth_custom_identity_claims()` flowing through Genie-initiated queries is **the gap** that 17 use cases across 12 accounts are blocked on. BCD is named in that escalation.
- Q2/Q3 target with no firm commitment from product.
- If it doesn't work with Genie, it's irrelevant for BCD's use case.
- Single SP = single blast radius if credential leaks (row filter is only barrier).

### Recommended Strategy

| Priority | Action | Timeline |
|----------|--------|----------|
| **Now** | **Advito: SCIM provisioning** — 600 users, straightforward, do it | Immediate |
| **Now** | **Validate custom claims through Genie** in BCD workspace — quick test determines if Approach C is viable | This week |
| **Now** | **Help VJ replace function-based approach with UC row filters** — regardless of which identity approach wins, the row filters are needed | This week |
| **Pending** | **Get Ryan's JIT answer** — determines if Approach A is feasible for indirect access | Waiting on Ryan |
| **If custom claims works** | **BCD: Approach C** — add token exchange to Elastic Beanstalk proxy, one SP, row filters | Best outcome |
| **If custom claims doesn't work + JIT works** | **BCD: Approach A** — SCIM from Azure AD B2C, accept operational overhead | Second best |
| **If neither works** | **BCD: Approach B** — SP-per-customer with a dedicated rotation service, be honest about the engineering investment | Fallback |

### What to Say to BCD

> "We have three approaches ranked by operational simplicity. First, let's validate custom claims through Genie — if it works, management overhead is near-zero. Second, user provisioning via SCIM is the standard path, and Ryan is confirming JIT feasibility. Third, SP-per-customer works (Ibotta runs 1,300+), but it requires investing in a credential lifecycle service — it's automatable but it's a real engineering commitment. Let's validate the first two before defaulting to the third."
>
> "For Advito, with 600 users, SCIM provisioning is the clear path — no need to overthink it."

### What Needs Validation

- [ ] Does `current_oauth_custom_identity_claims()` flow through Genie queries? (test in BCD workspace)
- [ ] Can Ryan confirm JIT provisioning via API for indirect Databricks access?
- [ ] Azure AD B2C → Databricks SCIM: is this a supported integration path?
- [ ] Row filter performance with 10,000 users / 4,000 clients
- [ ] Account-level SP limits (if Approach B is needed)
