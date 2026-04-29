# Multi-Tenant Genie

A reference solution for delivering Databricks Genie to thousands of isolated tenants — one Service Principal per tenant, UC row filters for hard data isolation, no Databricks accounts for end users.

> **Status:** Refactoring to a generalized reference solution (branch `generalize-and-scale`). The full README + quickstart land in Phase 4 of the migration. See `docs/superpowers/specs/2026-04-28-generalize-and-scale-design.md` for the plan.

## Problem Statement

Deliver a natural-language analytics experience (via Databricks Genie Conversation API) to thousands of external tenants where:

- Each tenant queries their **own data only** (strict row-level isolation)
- Tenants authenticate via API keys — **no Databricks accounts required**
- The platform operator manages onboarding/offboarding without per-tenant Databricks provisioning
- Audit trails trace every query back to the originating tenant

## Architecture Patterns

Two viable patterns are documented. **Pattern B is recommended** for scale.

| | Pattern A: SP-per-Client | Pattern B: Shared SP + Custom Claims |
|---|---|---|
| Service Principals | 1 per client (thousands) | 1 total |
| RLS mechanism | Dynamic views with `session_user()` | Dynamic views with `current_oauth_custom_identity_claims()` |
| Scaling | O(N) SP lifecycle management | O(1) — add clients to a registry, not Databricks |
| Works today | Yes, fully GA | Yes — verify Genie surface support |
| Operational cost | High | Low |
| Precedent | Ibotta (1,300+ SPs) | Identity Claims User Guide |

## Documentation

| Document | Description |
|----------|-------------|
| [Architecture Overview](docs/architecture.md) | Full system design, component interactions, data flow |
| [Code Snippets](docs/code-snippets.md) | Lift-and-use examples: token mint, SP onboarding, row filters, Genie ask, audit |
| [Pattern A: SP-per-Client](docs/pattern-a-sp-per-client.md) | SP-per-client with `session_user()` RLS |
| [Security & RBAC](docs/security-rbac.md) | Authentication, encryption, multi-tenant isolation, audit |
| [Implementation Guide](docs/implementation-guide.md) | Step-by-step setup: proxy app, Lakebase, UC, Genie |
| [Rate Limits & Scaling](docs/scaling.md) | Genie throughput, token caching, multi-workspace strategies |
| [Internal References](docs/references.md) | Links to internal docs, escalations, and prior art |

## Project Structure

```
multi-tenant-genie/
├── docs/                     # Architecture & design documents
├── src/
│   ├── proxy/                # API gateway / proxy app code
│   ├── scripts/              # SP provisioning, client onboarding automation
│   └── sql/                  # UC dynamic views, row filters, Lakebase schema
├── diagrams/                 # Architecture diagrams (Mermaid, PNG)
└── README.md
```

## Key References

- [Firefly Analytics](https://www.firefly-analytics.com/) — Databricks reference implementation for SSO-SPN multi-tenant apps
- [Genie Conversation API](https://docs.databricks.com/aws/en/genie/conversation-api) — Official API docs
- [Designing Multi-Tenant Applications on Databricks](https://docs.google.com/document/d/13xs2ysXplWIgS5auf03zjuA2DTP3dlNSVn97UZ180TE) — Internal isolation patterns guide
- [Identity Claim User Guide](https://docs.google.com/document/d/1elK2fy3s1OSH_TetVvgs4z-bIGKMNii0J2deH9cb4tg) — `current_oauth_custom_identity_claims()` setup
- [RLS via Custom Claims Escalation](https://docs.google.com/document/d/1scAq6GdTRzdmv3ydUwv6JusgTRv6Lo3IkwILOrzXSxk) — Product escalation tracking Genie + custom claims gap

## Status

**Phase: Design & Documentation** — validating custom claims support through Genie surfaces before committing to Pattern B implementation.
