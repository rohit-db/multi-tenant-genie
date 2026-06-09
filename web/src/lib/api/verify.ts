// Isolation verifier — proves each tenant SP sees only its own rows.
import { http } from "./http";
import type { VerifyResultRow } from "./types";

export const verifyApi = {
  verify: () => http<VerifyResultRow[]>("/verify", { method: "POST" }),
};
