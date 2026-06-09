// Shared fetch wrapper for the JSON API. Centralizes credentials, error
// shaping, and the 401 -> "bounce to login" signal so every domain module
// (auth, tenants, genie, ...) behaves identically.

export const BASE = "/api";

export async function http<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    ...init,
  });
  if (!res.ok) {
    // Session expired / not logged in: let the app bounce to the login screen.
    if (res.status === 401 && path !== "/auth/me" && path !== "/auth/login") {
      window.dispatchEvent(new Event("mtg:unauthorized"));
    }
    const text = await res.text().catch(() => "");
    throw new Error(`${res.status} ${res.statusText}${text ? `: ${text}` : ""}`);
  }
  // 204 / empty bodies
  const ct = res.headers.get("content-type") ?? "";
  if (!ct.includes("application/json")) return undefined as T;
  return res.json();
}
