import { useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  AlertCircle,
  Loader2,
  ArrowRight,
  Shield,
  Building2,
  Sparkles,
  LayoutGrid,
  ShieldCheck,
} from "lucide-react";
import { BRAND, BrandMark } from "@/brand";
import { useAuth } from "@/lib/auth";
import { api } from "@/lib/api";

export function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const from = (location.state as { from?: { pathname?: string } })?.from?.pathname ?? "/";

  const [email, setEmail] = useState("operator@skydesk.app");
  const [password, setPassword] = useState("skydesk");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const accountsQ = useQuery({
    queryKey: ["demo-accounts"],
    queryFn: api.demoAccounts,
    staleTime: 60_000,
  });
  const accounts = accountsQ.data ?? [];
  const operators = accounts.filter((a) => a.role === "operator");
  const clients = accounts.filter((a) => a.role !== "operator");

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const user = await login(email.trim(), password);
      navigate(user.role === "operator" && from === "/" ? "/" : from, {
        replace: true,
      });
    } catch (err) {
      setError(
        (err as Error).message.includes("401")
          ? "Invalid email or password."
          : (err as Error).message,
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="grid min-h-screen lg:grid-cols-2">
      {/* Brand panel */}
      <div
        className="relative hidden flex-col justify-between overflow-hidden p-12 text-white lg:flex"
        style={{
          background:
            "linear-gradient(150deg, var(--brand-strong), var(--brand) 55%, #38bdf8)",
        }}
      >
        {/* Decorative depth: soft radial glows + faint dot grid */}
        <div
          aria-hidden
          className="pointer-events-none absolute -right-24 -top-24 h-80 w-80 rounded-full bg-white/15 blur-3xl"
        />
        <div
          aria-hidden
          className="pointer-events-none absolute -bottom-28 -left-16 h-72 w-72 rounded-full bg-white/10 blur-3xl"
        />
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0 opacity-[0.12]"
          style={{
            backgroundImage:
              "radial-gradient(circle, rgba(255,255,255,0.9) 1px, transparent 1px)",
            backgroundSize: "22px 22px",
          }}
        />

        <div className="relative flex items-center gap-3">
          <BrandMark className="h-9 w-9" />
          <span className="text-lg font-semibold tracking-tight">
            {BRAND.fullName}
          </span>
        </div>

        <div className="relative max-w-md space-y-6">
          <h1 className="text-3xl font-semibold leading-tight tracking-tight">
            {BRAND.tagline}
          </h1>
          <p className="leading-relaxed text-sky-50/90">{BRAND.pitch}</p>
          <ul className="space-y-3 text-sm">
            {[
              { icon: Sparkles, text: "Ask in plain English — your own Genie" },
              { icon: LayoutGrid, text: "Live dashboards on governed data" },
              {
                icon: ShieldCheck,
                text: "Every tenant isolated by Unity Catalog",
              },
            ].map((f) => (
              <li key={f.text} className="flex items-center gap-3">
                <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-white/15 backdrop-blur">
                  <f.icon className="h-3.5 w-3.5" />
                </span>
                <span className="text-sky-50/95">{f.text}</span>
              </li>
            ))}
          </ul>
        </div>

        <div className="relative space-y-3">
          <div className="flex flex-wrap gap-1.5">
            {["Genie", "Unity Catalog", "Lakebase", "Databricks Apps"].map(
              (c) => (
                <span
                  key={c}
                  className="rounded-full border border-white/20 bg-white/10 px-2.5 py-0.5 text-[11px] font-medium text-white/90 backdrop-blur"
                >
                  {c}
                </span>
              ),
            )}
          </div>
          <p className="text-xs text-sky-50/70">{BRAND.poweredBy}</p>
        </div>
      </div>

      {/* Form panel */}
      <div className="flex items-center justify-center bg-white px-6 py-12">
        <div className="w-full max-w-sm space-y-8">
          <div className="space-y-2 lg:hidden">
            <BrandMark className="h-9 w-9" />
            <h1 className="text-xl font-semibold">{BRAND.fullName}</h1>
          </div>

          <div className="space-y-1">
            <h2 className="text-2xl font-semibold tracking-tight text-slate-900">
              Sign in
            </h2>
            <p className="text-sm text-slate-500">
              Welcome back. Sign in to your analytics workspace.
            </p>
          </div>

          <form onSubmit={submit} className="space-y-4">
            <div className="space-y-1.5">
              <label className="text-sm font-medium text-slate-700">Email</label>
              <Input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                autoComplete="username"
                required
              />
            </div>
            <div className="space-y-1.5">
              <label className="text-sm font-medium text-slate-700">
                Password
              </label>
              <Input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
                required
              />
            </div>

            {error && (
              <div className="flex items-center gap-2 rounded-md bg-rose-50 px-3 py-2 text-sm text-rose-700">
                <AlertCircle className="h-4 w-4 shrink-0" />
                {error}
              </div>
            )}

            <Button
              type="submit"
              disabled={busy}
              className="w-full gap-1.5 text-white"
              style={{ background: "var(--brand)" }}
            >
              {busy ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <>
                  Sign in
                  <ArrowRight className="h-4 w-4" />
                </>
              )}
            </Button>
          </form>

          <div className="rounded-lg border border-slate-200 bg-slate-50 p-3.5 text-xs">
            <div className="mb-1 font-medium text-slate-600">Demo accounts</div>
            <p className="mb-2 text-[11px] leading-relaxed text-slate-400">
              Each client has its own login — signing in pins the product to that
              client. The operator can switch between all clients.
            </p>

            {operators.length > 0 && (
              <div className="space-y-1.5">
                {operators.map((a) => (
                  <AccountRow
                    key={a.email}
                    email={a.email}
                    label="Operator · all clients"
                    icon={<Shield className="h-3 w-3" />}
                    onPick={() => {
                      setEmail(a.email);
                      setPassword("skydesk");
                    }}
                  />
                ))}
              </div>
            )}

            {clients.length > 0 && (
              <div className="mt-2 space-y-1.5 border-t border-slate-200 pt-2">
                <div className="px-2 text-[10px] font-semibold uppercase tracking-wider text-slate-400">
                  Client logins
                </div>
                <div className="max-h-40 space-y-1 overflow-y-auto">
                  {clients.map((a) => (
                    <AccountRow
                      key={a.email}
                      email={a.email}
                      label={a.name.replace(/ Analyst$/, "")}
                      icon={<Building2 className="h-3 w-3" />}
                      onPick={() => {
                        setEmail(a.email);
                        setPassword("skydesk");
                      }}
                    />
                  ))}
                </div>
              </div>
            )}

            <div className="mt-2 text-slate-400">
              password: <span className="font-mono">skydesk</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function AccountRow({
  email,
  label,
  icon,
  onPick,
}: {
  email: string;
  label: string;
  icon: React.ReactNode;
  onPick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onPick}
      className="flex w-full items-center justify-between gap-2 rounded-md px-2 py-1 text-left text-slate-600 hover:bg-white"
    >
      <span className="truncate font-mono">{email}</span>
      <span className="flex shrink-0 items-center gap-1 text-slate-400">
        {icon}
        {label}
      </span>
    </button>
  );
}
