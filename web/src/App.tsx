import { useQuery } from "@tanstack/react-query";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { api } from "@/lib/api";
import { AdminPage } from "@/pages/AdminPage";
import { DemoPage } from "@/pages/DemoPage";
import { ArchitecturePage } from "@/pages/ArchitecturePage";

function App() {
  const { data: ws } = useQuery({ queryKey: ["ws"], queryFn: api.workspace });

  return (
    <div className="min-h-screen bg-slate-50/40">
      <header className="border-b border-slate-200/70 bg-white sticky top-0 z-40">
        <div className="container mx-auto px-6 h-14 flex items-center justify-between gap-6">
          <div className="flex items-center gap-3 min-w-0">
            <Logomark />
            <h1 className="text-[15px] font-semibold tracking-tight">
              Multi-Tenant Genie
            </h1>
            <span className="text-[10px] uppercase tracking-[0.12em] text-slate-500 font-medium border border-slate-200 rounded px-1.5 py-0.5">
              reference
            </span>
          </div>
          {ws && (
            <div className="hidden md:flex items-center gap-3 text-[11px] font-mono text-slate-500 min-w-0">
              <span className="truncate">
                {ws.host.replace("https://", "").replace(".cloud.databricks.com", "")}
              </span>
              <span className="text-slate-300">·</span>
              <span className="truncate">
                {ws.catalog}.{ws.schema_name}
              </span>
            </div>
          )}
        </div>
      </header>

      <main className="container mx-auto px-6 py-10">
        <div className="mb-6">
          <p className="text-sm text-slate-600 max-w-2xl">
            A reference for delivering Genie to thousands of isolated tenants — one Service Principal per tenant, UC row filters for hard data isolation, no Databricks accounts for end users.
          </p>
        </div>

        <Tabs defaultValue="demo" className="w-full">
          <TabsList className="bg-transparent border-b border-slate-200 rounded-none w-full justify-start h-auto p-0 mb-6 gap-6">
            <TabsTrigger
              value="demo"
              className="data-[state=active]:bg-transparent data-[state=active]:shadow-none data-[state=active]:text-slate-900 data-[state=active]:border-slate-900 text-slate-500 border-b-2 border-transparent rounded-none px-0 pb-3 pt-1 font-medium"
            >
              Demo
            </TabsTrigger>
            <TabsTrigger
              value="admin"
              className="data-[state=active]:bg-transparent data-[state=active]:shadow-none data-[state=active]:text-slate-900 data-[state=active]:border-slate-900 text-slate-500 border-b-2 border-transparent rounded-none px-0 pb-3 pt-1 font-medium"
            >
              Admin
            </TabsTrigger>
            <TabsTrigger
              value="architecture"
              className="data-[state=active]:bg-transparent data-[state=active]:shadow-none data-[state=active]:text-slate-900 data-[state=active]:border-slate-900 text-slate-500 border-b-2 border-transparent rounded-none px-0 pb-3 pt-1 font-medium"
            >
              Architecture
            </TabsTrigger>
          </TabsList>

          <TabsContent value="demo">
            <DemoPage />
          </TabsContent>
          <TabsContent value="admin">
            <AdminPage />
          </TabsContent>
          <TabsContent value="architecture">
            <ArchitecturePage />
          </TabsContent>
        </Tabs>
      </main>

      <footer className="border-t border-slate-200/60 mt-16">
        <div className="container mx-auto px-6 py-5 text-[11px] text-slate-500 flex items-center justify-between">
          <span>Pattern A · SP per tenant · UC row filters · OAuth M2M</span>
          {ws && (
            <span className="font-mono">
              genie {ws.genie_space_id.slice(0, 8)}
            </span>
          )}
        </div>
      </footer>
    </div>
  );
}

function Logomark() {
  // Restrained mark: filled square with a subtle inset, no gradient.
  return (
    <div className="h-7 w-7 rounded-md bg-slate-900 flex items-center justify-center">
      <div className="h-2 w-2 rounded-sm bg-white" />
    </div>
  );
}

export default App;
