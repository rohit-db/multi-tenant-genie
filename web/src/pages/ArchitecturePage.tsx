import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Layers,
  Key,
  ShieldCheck,
  Database,
  Sparkles,
  GitBranch,
  PlayCircle,
  UserPlus,
  MessageCircle,
  RotateCw,
  Trash2,
} from "lucide-react";
import { api } from "@/lib/api";
import { Mermaid } from "@/components/Mermaid";

const ONBOARD_FLOW = `sequenceDiagram
    autonumber
    participant Admin as Admin UI
    participant API as FastAPI
    participant SCIM as Workspace SCIM
    participant SPS as SP Secrets API
    participant Scope as Secret Scope
    participant UC as Unity Catalog
    participant Perm as Genie Permissions

    Admin->>API: POST /tenants/onboard<br/>{tenant_id, tenant_name}
    API->>SCIM: service_principals.create(display_name)
    SCIM-->>API: SP { application_id, id }
    API->>SPS: secrets.create(service_principal_id)
    SPS-->>API: { client_secret }  (returned once)
    API->>Scope: put_secret(key=app_id, value=secret)
    API->>UC: INSERT tenants (status='active')
    API->>UC: INSERT sp_tenant_mapping (active=true)
    API->>UC: GRANT USE + SELECT TO app_id
    API->>Perm: PATCH /permissions/genie/{space} CAN_RUN
    API->>UC: INSERT audit_log (action='onboard')
    API-->>Admin: { tenant, client_id, client_secret }
`;

const CALL_FLOW = `sequenceDiagram
    autonumber
    participant UI as Client UI
    participant API as FastAPI
    participant Cache as Token Cache
    participant OIDC as /oidc/v1/token
    participant Scope as Secret Scope
    participant Genie as Genie API
    participant UC as Unity Catalog

    UI->>API: POST /genie/ask<br/>{tenant_id, question}
    API->>Cache: get_token(sp_app_id)
    alt cache hit, TTL > 5 min
        Cache-->>API: cached JWT
    else miss / near expiry
        API->>Scope: read secret by sp_app_id
        API->>OIDC: client_credentials grant<br/>(basic auth with client_id + secret)
        OIDC-->>API: access_token (JWT, ~55 min TTL)
        API->>Cache: store (token, expiry)
    end
    API->>Genie: POST /spaces/{id}/start-conversation<br/>Authorization: Bearer <token>
    Genie-->>API: { conversation_id, message_id }
    loop poll until COMPLETED
        API->>Genie: GET /messages/{message_id}
        Genie-->>API: status=IN_PROGRESS | COMPLETED
    end
    Note over Genie,UC: Genie issues tenant-scoped SQL via the warehouse
    Genie->>UC: SELECT ... FROM bookings
    UC->>UC: tenant_row_filter(tenant_id)<br/>joins sp_tenant_mapping<br/>on session_user()
    UC-->>Genie: only this tenant's rows
    Genie-->>API: { sql, rows, answer_text }
    API->>UC: INSERT audit_log (action='query')
    API-->>UI: AskResponse
`;

const ROTATE_FLOW = `sequenceDiagram
    autonumber
    participant Admin as Admin UI
    participant API as FastAPI
    participant SPS as SP Secrets API
    participant Scope as Secret Scope
    participant UC as Unity Catalog

    Admin->>API: POST /tenants/{id}/rotate
    API->>SPS: list secrets for SP
    SPS-->>API: [ secret_1 ]
    API->>SPS: create NEW secret
    SPS-->>API: { new_client_secret }
    Note over API,Scope: New secret stored BEFORE old deleted<br/>→ overlap window for in-flight tokens<br/>(up to 5 concurrent secrets per SP)
    API->>Scope: put_secret(key=app_id, value=new)
    API->>SPS: delete secret_1
    API->>UC: UPDATE tenants SET updated_at
    API->>UC: INSERT audit_log (action='rotate')
    API-->>Admin: { tenant_id, new_client_secret }
`;

const DEACTIVATE_FLOW = `sequenceDiagram
    autonumber
    participant Admin as Admin UI
    participant API as FastAPI
    participant SCIM as Workspace SCIM
    participant SPS as SP Secrets API
    participant Scope as Secret Scope
    participant UC as Unity Catalog

    Admin->>API: POST /tenants/{id}/deactivate
    API->>SCIM: service_principals.update(active=false)
    Note over SCIM: blocks new token exchanges<br/>(existing tokens still valid until expiry)
    API->>SPS: list + delete ALL secrets
    API->>Scope: delete_secret(key=app_id)
    API->>UC: UPDATE sp_tenant_mapping SET active=false
    Note over UC: row filter now rejects this SP<br/>even if a stale token reaches UC
    API->>UC: UPDATE tenants SET status='deactivated'
    API->>UC: INSERT audit_log (action='deactivate')
    API-->>Admin: { ok: true }
`;

export function ArchitecturePage() {
  const mapping = useQuery({ queryKey: ["mapping"], queryFn: api.mapping });
  const ws = useQuery({ queryKey: ["ws"], queryFn: api.workspace });
  const [flow, setFlow] = useState("onboard");

  const rowFilterSql = ws.data
    ? `CREATE OR REPLACE FUNCTION ${ws.data.catalog}.${ws.data.schema_name}.tenant_row_filter(tenant_param STRING)
RETURN
  is_account_group_member('${ws.data.admin_group}')
  OR EXISTS (
    SELECT 1 FROM ${ws.data.catalog}.${ws.data.schema_name}.sp_tenant_mapping m
    WHERE m.sp_app_id = session_user()
      AND m.active = true
      AND m.tenant_id = tenant_param
  );

ALTER TABLE ${ws.data.catalog}.${ws.data.schema_name}.bookings
  SET ROW FILTER ${ws.data.catalog}.${ws.data.schema_name}.tenant_row_filter ON (tenant_id);`
    : "";

  return (
    <div className="space-y-6">
      {/* Demo script callout */}
      <Card className="bg-gradient-to-br from-slate-900 to-slate-800 text-slate-100 border-0 shadow-lg">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-white">
            <PlayCircle className="h-5 w-5 text-indigo-300" />
            90-second demo script
          </CardTitle>
          <CardDescription className="text-slate-300">
            Narration outline for a screen recording. Each step is ~10–15s.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3 text-sm leading-relaxed">
          <ScriptStep
            n={1}
            label="Frame the problem"
            text='"Both BCD and Advito need to deliver Genie to thousands of client organizations — Advito via embedded analytics in BCD Pay (~130 clients), BCD via Decision Source / CSS at a much larger scale. We can’t put 10K+ end users into Databricks, and we can’t trust prompt-based filters. Same pattern solves both."'
          />
          <ScriptStep
            n={2}
            label="Show isolation (Client tab)"
            text='"I’m querying as Nike." Ask → result. "Same question as CloudVenture." Different answer. Then hit "Isolation sweep" — all tenants run in parallel, Genie generates one SQL, each tenant gets different rows.'
          />
          <ScriptStep
            n={3}
            label="Show lifecycle (Admin tab)"
            text='Open the Admin tab. Point at the stat cards + tenants table. Click "Onboard tenant" — creates a real SP, mints secret, grants UC + Genie, inserts mapping row. Audit log updates live.'
          />
          <ScriptStep
            n={4}
            label="Show enforcement (Architecture tab)"
            text='Scroll down. "Here is the actual mapping table Unity Catalog joins against — and the row filter SQL deployed right now. This is the only thing between a client and someone else’s data."'
          />
          <ScriptStep
            n={5}
            label="Close"
            text='"Pattern works today with GA primitives. One SP per client. Zero prompt-based enforcement. Scales to ~3,000 SPs with documented headroom. Next iteration adds Lakebase for app-layer state + a managed Terraform module."'
          />
        </CardContent>
      </Card>

      {/* Flow cards summary */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <FlowCard
          icon={Key}
          step={1}
          title="Onboarding"
          body="Creates a workspace Service Principal, mints its first OAuth client_credentials secret, stores it in the mt-genie-demo secret scope, inserts a row in sp_tenant_mapping, and grants USE/SELECT on the demo catalog plus CAN_RUN on the Genie Space."
        />
        <FlowCard
          icon={Sparkles}
          step={2}
          title="Client call"
          body="The app exchanges the tenant's SP client_id/secret at /oidc/v1/token. The JWT's session_user() resolves to the SP's application_id inside Unity Catalog — no end-user identity needed."
        />
        <FlowCard
          icon={ShieldCheck}
          step={3}
          title="Row filter"
          body="UC runs tenant_row_filter(tenant_id) for every row Genie touches. The function joins sp_tenant_mapping on session_user() and keeps only rows the SP is allowed to see. Deterministic, not prompt-dependent."
        />
        <FlowCard
          icon={GitBranch}
          step={4}
          title="Rotation & offboarding"
          body="Rotation creates a new secret before deleting old ones (overlap window for in-flight tokens). Deactivation flips active=false in the mapping, disables the SP, and revokes all its OAuth secrets."
        />
      </div>

      {/* Sequence diagrams */}
      <Card className="shadow-sm">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Layers className="h-5 w-5" />
            Sequence flows
          </CardTitle>
          <CardDescription>
            Every arrow below is a real HTTP/SDK call. Grey arrows = request;
            dashed = response. Amber notes call out constraints or guarantees.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Tabs value={flow} onValueChange={setFlow} className="w-full">
            <TabsList className="bg-slate-100 mb-4">
              <TabsTrigger value="onboard" className="gap-1.5">
                <UserPlus className="h-3.5 w-3.5" />
                Admin onboarding
              </TabsTrigger>
              <TabsTrigger value="call" className="gap-1.5">
                <MessageCircle className="h-3.5 w-3.5" />
                Client → Genie
              </TabsTrigger>
              <TabsTrigger value="rotate" className="gap-1.5">
                <RotateCw className="h-3.5 w-3.5" />
                Rotate secret
              </TabsTrigger>
              <TabsTrigger value="deactivate" className="gap-1.5">
                <Trash2 className="h-3.5 w-3.5" />
                Deactivate
              </TabsTrigger>
            </TabsList>

            <TabsContent value="onboard" className="mt-0">
              <DiagramCaption
                title="Admin onboards a client organization"
                points={[
                  "One-click end-to-end: creates SP, mints secret, stores it, inserts mapping, grants UC + Genie.",
                  "Client secret is surfaced exactly once. Lost → rotate.",
                  "Everything except secret creation is idempotent — re-onboard is safe.",
                ]}
              />
              <div className="rounded-md border bg-white p-4">
                <Mermaid chart={ONBOARD_FLOW} />
              </div>
            </TabsContent>

            <TabsContent value="call" className="mt-0">
              <DiagramCaption
                title="Client UI asks Genie as the tenant's SP"
                points={[
                  "Token cached per-SP in-process (5 min buffer before expiry). Miss ≈ one /oidc call.",
                  "session_user() inside Unity Catalog resolves to the SP's application_id from the JWT.",
                  "Row filter fires inside UC — Genie is unaware. Same Genie-generated SQL, different rows per tenant.",
                ]}
              />
              <div className="rounded-md border bg-white p-4">
                <Mermaid chart={CALL_FLOW} />
              </div>
            </TabsContent>

            <TabsContent value="rotate" className="mt-0">
              <DiagramCaption
                title="Zero-downtime secret rotation"
                points={[
                  "New secret is created and stored BEFORE the old one is deleted.",
                  "Databricks allows 5 concurrent OAuth secrets per SP — safe overlap window.",
                  "In-flight tokens minted from the old secret keep working until their TTL (~55 min).",
                ]}
              />
              <div className="rounded-md border bg-white p-4">
                <Mermaid chart={ROTATE_FLOW} />
              </div>
            </TabsContent>

            <TabsContent value="deactivate" className="mt-0">
              <DiagramCaption
                title="Offboarding a client organization"
                points={[
                  "SP.update(active=false) immediately blocks new token exchanges.",
                  "All secrets are deleted so even cached secrets can't mint new tokens.",
                  "Mapping flipped to active=false — any stale token that reaches UC gets zero rows.",
                ]}
              />
              <div className="rounded-md border bg-white p-4">
                <Mermaid chart={DEACTIVATE_FLOW} />
              </div>
            </TabsContent>
          </Tabs>
        </CardContent>
      </Card>

      {/* Live mapping */}
      <Card className="shadow-sm">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Database className="h-5 w-5" />
            Live mapping table
          </CardTitle>
          <CardDescription>
            Same table UC joins during the row filter. Any SP not listed (or
            marked active=false) sees zero rows by default.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {mapping.data && mapping.data.length > 0 ? (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>sp_app_id</TableHead>
                  <TableHead>tenant_id</TableHead>
                  <TableHead>active</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {mapping.data.map((m) => (
                  <TableRow key={m.sp_app_id + m.tenant_id}>
                    <TableCell className="font-mono text-xs">
                      {m.sp_app_id}
                    </TableCell>
                    <TableCell className="font-mono text-xs">
                      {m.tenant_id}
                    </TableCell>
                    <TableCell>
                      {m.active ? (
                        <Badge className="bg-emerald-100 text-emerald-800 hover:bg-emerald-100 border-0">
                          active
                        </Badge>
                      ) : (
                        <Badge variant="secondary">inactive</Badge>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <p className="text-sm text-muted-foreground">
              No mapping rows yet.
            </p>
          )}
        </CardContent>
      </Card>

      {/* Row filter SQL */}
      <Card className="shadow-sm">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Layers className="h-5 w-5" />
            Row filter — live SQL
          </CardTitle>
          <CardDescription>
            Exactly what is deployed in Unity Catalog right now.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <pre className="rounded-md bg-slate-900 text-slate-100 p-4 text-xs overflow-auto font-mono leading-relaxed shadow-inner">
            {rowFilterSql}
          </pre>
        </CardContent>
      </Card>
    </div>
  );
}

function FlowCard({
  icon: Icon,
  step,
  title,
  body,
}: {
  icon: React.ComponentType<{ className?: string }>;
  step: number;
  title: string;
  body: string;
}) {
  return (
    <Card className="shadow-sm hover:shadow-md transition-shadow">
      <CardHeader>
        <div className="flex items-center gap-3">
          <div className="h-9 w-9 rounded-full bg-gradient-to-br from-indigo-100 to-violet-100 text-indigo-700 font-mono text-sm flex items-center justify-center border border-indigo-200">
            {step}
          </div>
          <CardTitle className="flex items-center gap-2 text-base">
            <Icon className="h-4 w-4" />
            {title}
          </CardTitle>
        </div>
      </CardHeader>
      <CardContent>
        <p className="text-sm text-muted-foreground leading-relaxed">{body}</p>
      </CardContent>
    </Card>
  );
}

function ScriptStep({
  n,
  label,
  text,
}: {
  n: number;
  label: string;
  text: string;
}) {
  return (
    <div className="flex gap-3">
      <div className="h-6 w-6 shrink-0 rounded-full bg-indigo-500/20 text-indigo-300 text-[11px] font-semibold flex items-center justify-center border border-indigo-400/30">
        {n}
      </div>
      <div className="flex-1">
        <div className="text-[11px] uppercase tracking-wider text-indigo-300/80 font-semibold mb-1">
          {label}
        </div>
        <p className="text-slate-100">{text}</p>
      </div>
    </div>
  );
}

function DiagramCaption({
  title,
  points,
}: {
  title: string;
  points: string[];
}) {
  return (
    <div className="mb-3 space-y-1.5">
      <div className="text-sm font-semibold">{title}</div>
      <ul className="text-xs text-muted-foreground leading-relaxed list-disc list-inside space-y-0.5">
        {points.map((p, i) => (
          <li key={i}>{p}</li>
        ))}
      </ul>
    </div>
  );
}
