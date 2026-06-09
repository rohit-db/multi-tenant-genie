// Public API facade. Composes the per-domain modules into the single `api`
// object the app imports, and re-exports every wire type. Call sites keep
// importing `{ api, type Foo } from "@/lib/api"` exactly as before.
import { agentApi } from "./agent";
import { auditApi } from "./audit";
import { authApi } from "./auth";
import { genieApi } from "./genie";
import { tenantsApi } from "./tenants";
import { verifyApi } from "./verify";
import { workspaceApi } from "./workspace";

export * from "./types";

export const api = {
  ...authApi,
  ...workspaceApi,
  ...tenantsApi,
  ...genieApi,
  ...auditApi,
  ...verifyApi,
  ...agentApi,
};
