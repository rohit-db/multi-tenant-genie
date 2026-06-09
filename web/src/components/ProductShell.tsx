import { NavLink, Outlet, useNavigate } from "react-router-dom";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Home, Sparkles, LayoutGrid, ChevronDown, LogOut, Shield, Lock } from "lucide-react";
import { BRAND, BrandMark } from "@/brand";
import { useAuth } from "@/lib/auth";
import { useTenant } from "@/lib/tenant";
import { cn } from "@/lib/utils";

const NAV = [
  { to: "/", label: "Home", icon: Home, end: true },
  { to: "/ask", label: "Ask", icon: Sparkles, end: false },
  { to: "/dashboards", label: "Dashboards", icon: LayoutGrid, end: false },
];

export function ProductShell() {
  const { user, logout } = useAuth();
  const { active, selectedId, setSelected, selected, locked } = useTenant();
  const navigate = useNavigate();

  const initials = (user?.name ?? user?.email ?? "?")
    .split(/[\s@.]+/)
    .slice(0, 2)
    .map((s) => s[0]?.toUpperCase())
    .join("");

  return (
    <div className="min-h-screen bg-slate-50/60">
      <div
        aria-hidden
        className="h-0.5 w-full"
        style={{
          background:
            "linear-gradient(90deg, var(--brand-strong), var(--brand) 50%, #38bdf8)",
        }}
      />
      <header className="sticky top-0 z-40 border-b border-slate-200/70 bg-white/90 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-7xl items-center gap-6 px-5">
          <button
            type="button"
            onClick={() => navigate("/")}
            className="flex items-center gap-2.5"
          >
            <BrandMark className="h-7 w-7" />
            <span className="text-[15px] font-semibold tracking-tight text-slate-900">
              {BRAND.name}
            </span>
          </button>

          <nav className="hidden items-center gap-1 md:flex">
            {NAV.map((n) => (
              <NavLink
                key={n.to}
                to={n.to}
                end={n.end}
                className={({ isActive }) =>
                  cn(
                    "flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
                    isActive
                      ? "bg-[var(--brand-soft)] text-[var(--brand-strong)]"
                      : "text-slate-600 hover:bg-slate-100 hover:text-slate-900",
                  )
                }
              >
                <n.icon className="h-4 w-4" />
                {n.label}
              </NavLink>
            ))}
          </nav>

          <div className="ml-auto flex items-center gap-2.5">
            {locked ? (
              <div
                className="flex h-9 items-center gap-1.5 rounded-md border border-slate-200 bg-slate-50 px-3 text-sm"
                title="Your account is signed in to a single client"
              >
                <Lock className="h-3.5 w-3.5 text-slate-400" />
                <span className="text-[11px] uppercase tracking-wide text-slate-400">
                  Client
                </span>
                <span className="font-medium text-slate-700">
                  {selected?.tenant_name ?? user?.tenant_id}
                </span>
              </div>
            ) : (
              active.length > 0 && (
                <Select value={selectedId} onValueChange={setSelected}>
                  <SelectTrigger className="h-9 w-[176px] text-sm">
                    <span className="mr-1 text-[11px] uppercase tracking-wide text-slate-400">
                      Workspace
                    </span>
                    <SelectValue placeholder="Tenant" />
                  </SelectTrigger>
                  <SelectContent>
                    {active.map((t) => (
                      <SelectItem key={t.tenant_id} value={t.tenant_id}>
                        {t.tenant_name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )
            )}

            <DropdownMenu>
              <DropdownMenuTrigger className="flex items-center gap-1.5 rounded-full border border-slate-200 py-1 pl-1 pr-2 text-sm hover:bg-slate-50">
                <span className="flex h-7 w-7 items-center justify-center rounded-full bg-[var(--brand)] text-xs font-semibold text-white">
                  {initials}
                </span>
                <ChevronDown className="h-3.5 w-3.5 text-slate-400" />
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-56">
                <DropdownMenuLabel className="flex flex-col">
                  <span className="text-sm font-medium">{user?.name}</span>
                  <span className="text-xs font-normal text-slate-500">
                    {user?.email}
                  </span>
                </DropdownMenuLabel>
                <DropdownMenuSeparator />
                {user?.role === "operator" && (
                  <DropdownMenuItem onClick={() => navigate("/console")}>
                    <Shield className="mr-2 h-4 w-4" />
                    Operator console
                  </DropdownMenuItem>
                )}
                <DropdownMenuItem onClick={() => logout()}>
                  <LogOut className="mr-2 h-4 w-4" />
                  Sign out
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-5 py-8">
        <Outlet />
      </main>

      <footer className="border-t border-slate-200/60">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-5 py-5 text-[11px] text-slate-400">
          <span>{BRAND.poweredBy}</span>
          <span>SP per tenant · UC row filters · Genie MCP</span>
        </div>
      </footer>
    </div>
  );
}
