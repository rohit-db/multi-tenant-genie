// Workspace metadata (host, catalog, Genie space, dashboard, ...).
import { http } from "./http";
import type { WorkspaceInfo } from "./types";

export const workspaceApi = {
  workspace: () => http<WorkspaceInfo>("/workspace/info"),
};
