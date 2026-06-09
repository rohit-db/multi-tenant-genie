// Audit log + SP→tenant mapping (operator surface).
import { http } from "./http";
import type { AuditRow, MappingRow } from "./types";

export const auditApi = {
  audit: (limit = 50) => http<AuditRow[]>(`/audit?limit=${limit}`),
  mapping: () => http<MappingRow[]>("/audit/mapping"),
};
