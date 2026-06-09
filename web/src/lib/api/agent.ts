// Custom agent — plan→execute→synthesize. Every tool call goes through the
// tenant SP so the UC row filter applies, just like Genie.
import { http } from "./http";

export const agentApi = {
  agentInsights: (tenant_id: string, focus: string) =>
    http<{
      tenant_id: string;
      focus: string;
      model: string;
      reasoning: string | null;
      tool_calls: Array<{
        name: string;
        sql: string;
        columns?: string[];
        rows?: (string | number | null)[][];
        row_count?: number;
        latency_ms?: number;
        error?: string;
      }>;
      recommendation: string;
    }>("/agent/insights", {
      method: "POST",
      body: JSON.stringify({ tenant_id, focus }),
    }),
};
