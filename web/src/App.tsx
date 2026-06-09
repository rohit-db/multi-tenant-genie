import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider, RequireAuth, RequireOperator } from "@/lib/auth";
import { TenantProvider } from "@/lib/tenant";
import { ProductShell } from "@/components/ProductShell";
import { ConsoleShell } from "@/components/console/ConsoleShell";
import { LoginPage } from "@/pages/LoginPage";
import { HomePage } from "@/pages/HomePage";
import { DemoPage } from "@/pages/DemoPage";
import { DashboardsPage } from "@/pages/DashboardsPage";
import { AdminPage } from "@/pages/AdminPage";
import { DiagnosticsPage } from "@/pages/DiagnosticsPage";
import { ArchitecturePage } from "@/pages/ArchitecturePage";

function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<LoginPage />} />

          {/* Customer product — branded skin, any authenticated user */}
          <Route
            element={
              <RequireAuth>
                <TenantProvider>
                  <ProductShell />
                </TenantProvider>
              </RequireAuth>
            }
          >
            <Route index element={<HomePage />} />
            <Route path="ask" element={<DemoPage />} />
            <Route path="dashboards" element={<DashboardsPage />} />
          </Route>

          {/* Operator console — back-office, operators only */}
          <Route
            path="/console"
            element={
              <RequireOperator>
                <ConsoleShell />
              </RequireOperator>
            }
          >
            <Route index element={<AdminPage />} />
            <Route path="diagnostics" element={<DiagnosticsPage />} />
            <Route path="architecture" element={<ArchitecturePage />} />
          </Route>

          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}

export default App;
