// Wire types for the API. Mirrors the Pydantic models in server/.

export interface Tenant {
  tenant_id: string;
  tenant_name: string;
  sp_app_id: string;
  sp_display_name: string;
  status: "active" | "rotating" | "deactivated" | string;
  created_at: string;
  updated_at: string;
}

export interface UserInfo {
  email: string;
  name: string;
  role: "user" | "operator" | string;
  tenant_id: string | null;
}

export interface DemoAccount {
  email: string;
  name: string;
  role: "user" | "operator" | string;
  tenant_id: string | null;
}

export interface WorkspaceInfo {
  host: string;
  catalog: string;
  schema_name: string;
  genie_space_id: string;
  warehouse_name: string;
  admin_group: string;
  dashboard_id: string;
  embed_configured: boolean;
}

export interface EmbedConfig {
  instance_url: string;
  workspace_id: string;
  dashboard_id: string;
  embed_token: string;
  tenant_id: string;
}

export interface InspectorStep {
  n: number;
  name: string;
  summary: string | null;
  code_snippet: string | null;
  payload_in: Record<string, unknown> | null;
  payload_out: Record<string, unknown> | null;
  duration_ms: number;
  error: string | null;
}

export interface InspectorPayload {
  request_id: string;
  steps: InspectorStep[];
}

// Transport used for a Genie ask. "rest" hits the Genie Conversation API;
// "mcp" routes through Databricks managed MCP. Additive — defaults to "rest".
export type AskTransport = "rest" | "mcp";

export interface AskResponse {
  tenant_id: string;
  tenant_name: string;
  sp_app_id: string;
  question: string;
  answer_text: string | null;
  sql: string | null;
  columns: string[];
  rows: (string | number | null)[][];
  latency_ms: number;
  conversation_id: string | null;
  message_id: string | null;
  status: string;
  inspector: InspectorPayload | null;
  // Optional deep link back into the Databricks Genie conversation.
  deep_link?: string | null;
}

export interface AuditRow {
  id: number;
  tenant_id: string | null;
  actor: string | null;
  action: string;
  sp_app_id: string | null;
  question: string | null;
  status: string;
  latency_ms: number | null;
  detail: string | null;
  created_at: string;
}

export interface MappingRow {
  sp_app_id: string;
  tenant_id: string;
  active: boolean;
}

export interface OnboardResponse {
  tenant: Tenant;
  client_id: string;
  client_secret: string;
}

export interface RotateResponse {
  tenant_id: string;
  new_client_secret: string;
}

export interface BulkOnboardInput {
  tenant_id: string;
  tenant_name: string;
}

export interface BulkOnboardResponse {
  job_id: string;
}

export interface BulkOnboardJobError {
  tenant_id: string;
  error: string;
}

export interface BulkOnboardJobResult {
  tenant_id: string;
  tenant_name: string;
  sp_app_id: string;
  client_secret: string;
}

export interface JobStatus {
  job_id: string;
  state: "running" | "completed" | string;
  total: number;
  processed: number;
  errors: BulkOnboardJobError[];
  results: BulkOnboardJobResult[];
}

export interface VerifyResultRow {
  tenant_id: string;
  tenant_name: string;
  passed: boolean;
  distinct_tenant_ids: string[];
  visible_row_count: number | null;
  error: string | null;
}
