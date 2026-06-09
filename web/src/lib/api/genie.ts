// Genie surface: embed config, ask (REST/MCP), isolation sweep, direct SQL.
import { http } from "./http";
import type { AskResponse, AskTransport, EmbedConfig } from "./types";

export const genieApi = {
  // Embedded AI/BI dashboard: scoped token minted as the tenant's SP.
  embedConfig: (tenant_id: string) =>
    http<EmbedConfig>(`/genie/embed?tenant_id=${encodeURIComponent(tenant_id)}`),

  ask: (
    tenant_id: string,
    question: string,
    options?: {
      conversation_id?: string | null;
      inspect?: boolean;
      transport?: AskTransport;
    },
  ) => {
    const params = new URLSearchParams();
    if (options?.inspect) params.set("inspect", "true");
    if (options?.transport) params.set("transport", options.transport);
    const qs = params.toString();
    const url = qs ? `/genie/ask?${qs}` : "/genie/ask";
    return http<AskResponse>(url, {
      method: "POST",
      body: JSON.stringify({
        tenant_id,
        question,
        conversation_id: options?.conversation_id ?? null,
      }),
    });
  },
  sweep: (question: string) =>
    http<AskResponse[]>("/genie/sweep", {
      method: "POST",
      body: JSON.stringify({ question }),
    }),

  // Direct SQL — runs as the tenant SP via the warehouse, row filter still applies.
  // Used for deterministic dashboard widgets (no Genie roundtrip).
  runSql: (tenant_id: string, sql: string) =>
    http<{
      columns: string[];
      rows: (string | number | null)[][];
      latency_ms: number;
    }>("/genie/sql", {
      method: "POST",
      body: JSON.stringify({ tenant_id, sql }),
    }),
};
