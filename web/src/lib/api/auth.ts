// Auth — the thin app-level login layer.
import { http } from "./http";
import type { DemoAccount, UserInfo } from "./types";

export const authApi = {
  login: (email: string, password: string) =>
    http<UserInfo>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),
  logout: () => http<void>("/auth/logout", { method: "POST" }),
  me: () => http<UserInfo>("/auth/me"),
  demoAccounts: () => http<DemoAccount[]>("/auth/demo-accounts"),
};
