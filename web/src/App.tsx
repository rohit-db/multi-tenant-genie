import { useQuery } from "@tanstack/react-query";
import { Sparkles, Shield, Database, Plane } from "lucide-react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import { api } from "@/lib/api";
import { AdminPage } from "@/pages/AdminPage";
import { DemoPage } from "@/pages/DemoPage";
import { ArchitecturePage } from "@/pages/ArchitecturePage";

function App() {
  const { data: ws } = useQuery({ queryKey: ["ws"], queryFn: api.workspace });

  return (
    <div className="min-h-screen bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-indigo-50/70 via-slate-50 to-white">
      <header className="border-b bg-white/75 backdrop-blur supports-[backdrop-filter]:bg-white/60 sticky top-0 z-40">
        <div className="container mx-auto px-6 py-3 flex items-center justify-between gap-4">
          <div className="flex items-center gap-3 min-w-0">
            <div className="h-10 w-10 rounded-xl bg-gradient-to-br from-indigo-500 via-violet-500 to-fuchsia-500 flex items-center justify-center shadow-sm ring-1 ring-inset ring-white/20">
              <Shield className="h-5 w-5 text-white" />
            </div>
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <h1 className="text-[15px] font-semibold leading-none">
                  Multi-Tenant Genie
                </h1>
                <Badge
                  variant="secondary"
                  className="text-[10px] font-medium bg-indigo-50 text-indigo-700 border-indigo-100"
                >
                  Reference
                </Badge>
              </div>
              <p className="text-xs text-muted-foreground mt-1 truncate">
                <Plane className="h-3 w-3 inline mr-1 -mt-0.5" />
                A reference solution for delivering Genie to thousands of isolated tenants — one service principal per tenant
              </p>
            </div>
          </div>
          {ws && (
            <div className="hidden lg:flex items-center gap-2 text-[11px]">
              <Badge variant="outline" className="font-mono gap-1.5 py-1 bg-white">
                <Database className="h-3 w-3" />
                {ws.catalog}.{ws.schema_name}
              </Badge>
              <Badge variant="outline" className="font-mono gap-1.5 py-1 bg-white">
                <Sparkles className="h-3 w-3" />
                space {ws.genie_space_id.slice(0, 12)}…
              </Badge>
              <Badge
                variant="secondary"
                className="font-mono py-1 bg-slate-100"
              >
                {ws.host
                  .replace("https://", "")
                  .replace(".cloud.databricks.com", "")}
              </Badge>
            </div>
          )}
        </div>
      </header>

      <main className="container mx-auto px-6 py-8">
        <Tabs defaultValue="demo" className="w-full">
          <TabsList className="bg-white shadow-sm border">
            <TabsTrigger value="demo">Demo</TabsTrigger>
            <TabsTrigger value="admin">Admin</TabsTrigger>
            <TabsTrigger value="architecture">Architecture</TabsTrigger>
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

      <footer className="container mx-auto px-6 py-6 text-[11px] text-muted-foreground flex items-center justify-between">
        <div>
          Pattern A — SP per tenant · UC row filters · Databricks OAuth M2M
        </div>
        <div className="font-mono opacity-70">
          {ws?.host.replace("https://", "")}
        </div>
      </footer>
    </div>
  );
}

export default App;
