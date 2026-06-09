import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type Tenant } from "@/lib/api";
import { useAuth } from "@/lib/auth";

interface TenantState {
  tenants: Tenant[];
  active: Tenant[];
  selectedId: string | undefined;
  selected: Tenant | undefined;
  setSelected: (id: string) => void;
  loading: boolean;
  /** True when the signed-in user is bound to a single client (customer
   * login). The workspace switcher is locked to that tenant. */
  locked: boolean;
}

const TenantContext = createContext<TenantState | null>(null);

const PREFERRED = ["nike", "acme", "orion", "cloudventure"];
const STORAGE_KEY = "mtg:selectedTenant";

export function TenantProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const boundTenantId = user?.tenant_id ?? null;
  const locked = boundTenantId != null;

  const tenantsQ = useQuery({ queryKey: ["tenants"], queryFn: api.tenants });
  const active = useMemo(
    () => (tenantsQ.data ?? []).filter((t) => t.status === "active"),
    [tenantsQ.data],
  );

  const [selectedId, setSelectedId] = useState<string | undefined>(() => {
    return boundTenantId ?? localStorage.getItem(STORAGE_KEY) ?? undefined;
  });

  useEffect(() => {
    // Customer login: hard-pin to the bound client, ignore any stored choice.
    if (boundTenantId) {
      setSelectedId((prev) => (prev === boundTenantId ? prev : boundTenantId));
      return;
    }
    // Operator: fall back to a preferred/first active tenant if invalid.
    if (active.length === 0) return;
    const valid = selectedId && active.some((t) => t.tenant_id === selectedId);
    if (!valid) {
      const preferred = PREFERRED.map((p) =>
        active.find((t) => t.tenant_id === p),
      ).find(Boolean);
      setSelectedId(preferred?.tenant_id ?? active[0].tenant_id);
    }
  }, [active, selectedId, boundTenantId]);

  const setSelected = (id: string) => {
    if (locked) return; // bound logins can't switch clients
    setSelectedId(id);
    localStorage.setItem(STORAGE_KEY, id);
  };

  const selected = active.find((t) => t.tenant_id === selectedId);

  return (
    <TenantContext.Provider
      value={{
        tenants: tenantsQ.data ?? [],
        active,
        selectedId,
        selected,
        setSelected,
        loading: tenantsQ.isLoading,
        locked,
      }}
    >
      {children}
    </TenantContext.Provider>
  );
}

export function useTenant(): TenantState {
  const ctx = useContext(TenantContext);
  if (!ctx) throw new Error("useTenant must be used within TenantProvider");
  return ctx;
}
