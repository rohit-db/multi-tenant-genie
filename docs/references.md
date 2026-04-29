# Internal References & Prior Art

## Databricks Internal Documents

### Architecture & Design Patterns

| Document | Description | Key Takeaway |
|----------|-------------|--------------|
| [Designing Multi-Tenant Applications on Databricks](https://docs.google.com/document/d/13xs2ysXplWIgS5auf03zjuA2DTP3dlNSVn97UZ180TE) | INTERNAL — Comprehensive guide to tenant isolation patterns | Shared workspace + catalog/schema per tenant is preferred; dedicated compute per SP for chargeback |
| [Isolation in Multi-Tenant Applications](https://databricks.atlassian.net/wiki/spaces/BLT/pages/4753064523) | Confluence — Isolation patterns deep dive | Data isolation via UC, compute as attribution layer |
| [Single Tenant vs Multi Tenant Applications](https://docs.google.com/presentation/d/1AsTpo6BBsWRIRx6Bicjj8f4rtp5iP5ZoXE47hWeTfts) | Presentation on isolation tradeoffs | Decision framework for choosing isolation level |

### Genie & Custom Claims

| Document | Description | Key Takeaway |
|----------|-------------|--------------|
| [Identity Claim User Guide](https://docs.google.com/document/d/1elK2fy3s1OSH_TetVvgs4z-bIGKMNii0J2deH9cb4tg) | How `current_oauth_custom_identity_claims()` works | Token exchange with `custom_claim` param; supported on JDBC + SQL Execution API |
| [RLS via Custom Claims for Genie API](https://docs.google.com/document/d/1CAXj20i58KR4UsEFzCThRMX5Rxp1R7pjuHz4uXpuNAE) | Feature proposal for claims-based RLS in Genie | Vision for shared SP + JWT claims flowing through to UC |
| [ESCALATION: RLS via Custom Claims](https://docs.google.com/document/d/1scAq6GdTRzdmv3ydUwv6JusgTRv6Lo3IkwILOrzXSxk) | Executive escalation tracking 17 use cases across 12 accounts | $70K+ monthly DBU at stake; Q2/Q3 target for `current_oauth_custom_identity_claim()` in Genie |
| [Genie APIs: The Next Generation](https://docs.google.com/document/d/14AokZfxDOo3hVnQaxnsJ2PwQ7b6VEpGYmdl99hAXFo4) | Roadmap for Genie API expansion | Session-level filters, CI/CD for spaces, agent framework integration planned |
| [SP + Genie + Dynamic Views (Confluence)](https://databricks.atlassian.net/wiki/spaces/SSA/pages/4996268283) | Step-by-step: SP calling Genie with dynamic view RLS | TokenMinter pattern, GenieClient class, `session_user()` approach |
| [Genie Teams Integration with OBO and RLS](https://databricks.atlassian.net/wiki/spaces/SSA/pages/5899223141) | Teams bot using Azure AD OBO token exchange | Alternative: federate user identity through Azure AD instead of custom claims |
| [VTS - Custom Identity Claims](https://docs.google.com/document/d/1c0UqttMKXQxqYSFa5whWLG9ghKohl-TOhwd9yybO9QE) | VTS implementation of row filters with custom claims | Working example: `current_oauth_custom_identity_claim()` in row filter functions |

### Reference Implementations & Customer Examples

| Document | Description | Key Takeaway |
|----------|-------------|--------------|
| [Firefly Analytics](https://www.firefly-analytics.com/) | Official reference implementation — SSO-SPN multi-tenant platform | Next.js + Lakebase + UC; 1 SP per org; AES-256-GCM encryption; two-tier SP design |
| [Firefly Architecture](https://www.firefly-analytics.com/docs/architecture/overview) | Detailed architecture docs | Request flow, IAM, security, scalability, apps proxy |
| [Ibotta — Golden Path to Enterprise AI](https://docs.google.com/document/d/19ySKIvSTVQYfCFIuWgV6V_M2fY-6Vq8M6b-JKcIufYk) | Customer running 1,300+ SPs with per-client Genie isolation | Proves SP-per-client pattern works at scale (but operational overhead) |
| [Embedded Analytics Deep Dive](https://docs.google.com/presentation/d/19oKE5mxRfXNNxAqWGMqvufEeOCd4KqfEzHASb8ym2X4) | Technical deep dive on embedding Genie | SP permissions setup for Genie API calls |
| [Databricks Partner Well-Architected Framework](https://databrickslabs.github.io/partner-architecture/) | Official partner architecture guidance | Design patterns for built-on partners; Firefly is the reference impl |

## Public Documentation

| Document | URL |
|----------|-----|
| Genie Conversation API | https://docs.databricks.com/aws/en/genie/conversation-api |
| OAuth M2M (Service Principals) | https://docs.databricks.com/aws/en/dev-tools/auth/oauth-m2m.html |
| Dynamic Views (Row/Column Security) | https://docs.databricks.com/aws/en/data-governance/unity-catalog/row-and-column-filters.html |
| Service Principals | https://docs.databricks.com/aws/en/admin/users-groups/service-principals.html |
| Unity Catalog Privileges | https://docs.databricks.com/aws/en/data-governance/unity-catalog/manage-privileges/privileges.html |
| Python SDK — Service Principals | https://databricks-sdk-py.readthedocs.io/en/latest/account/iam/service_principals.html |
| Python SDK — Groups | https://databricks-sdk-py.readthedocs.io/en/latest/account/iam/groups.html |

## Slack Channels

- `#genie-field` — Genie questions and field issues
- `#partner-architecture` — WAF and built-on patterns
- `#unity-catalog` — UC permissions and governance

## Key Contacts / Escalation

- Custom claims escalation tracked in the [multi-account escalation doc](https://docs.google.com/document/d/1scAq6GdTRzdmv3ydUwv6JusgTRv6Lo3IkwILOrzXSxk)
- Firefly maintainers in `#partner-architecture`
