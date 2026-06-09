import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Shield, Network, ArrowUpRight, LogOut, ServerCog, Activity } from "lucide-react";
import { BRAND } from "@/brand";
import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/utils";

const NAV = [
  { to: "/console", label: "Operations", icon: ServerCog, end: true },
  { to: "/console/diagnostics", label: "Diagnostics", icon: Activity, end: false },
  { to: "/console/architecture", label: "Architecture", icon: Network, end: false },
];

export function ConsoleShell() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <header className="sticky top-0 z-40 border-b border-slate-800 bg-slate-900/90 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-7xl items-center gap-6 px-5">
          <div className="flex items-center gap-2.5">
            <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-slate-800">
              <Shield className="h-4 w-4 text-sky-400" />
            </span>
            <span className="text-[15px] font-semibold tracking-tight">
              {BRAND.name} <span className="text-slate-500">Console</span>
            </span>
          </div>

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
                      ? "bg-slate-800 text-white"
                      : "text-slate-400 hover:bg-slate-800/60 hover:text-slate-100",
                  )
                }
              >
                <n.icon className="h-4 w-4" />
                {n.label}
              </NavLink>
            ))}
          </nav>

          <div className="ml-auto flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              className="gap-1.5 border-slate-700 bg-transparent text-slate-200 hover:bg-slate-800 hover:text-white"
              onClick={() => navigate("/")}
            >
              Open product
              <ArrowUpRight className="h-3.5 w-3.5" />
            </Button>
            <span className="hidden text-xs text-slate-400 sm:inline">
              {user?.email}
            </span>
            <Button
              variant="ghost"
              size="sm"
              className="gap-1.5 text-slate-400 hover:bg-slate-800 hover:text-white"
              onClick={() => logout()}
            >
              <LogOut className="h-4 w-4" />
            </Button>
          </div>
        </div>
      </header>

      {/* The reused operator pages are light-themed cards; render them on a
          light canvas inset so they stay legible inside the dark console. */}
      <main className="mx-auto max-w-7xl px-5 py-8">
        <div className="rounded-2xl bg-slate-50 p-5 text-slate-900 shadow-xl sm:p-7">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
