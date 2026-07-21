import { Outlet } from "react-router-dom";
import { AppShell } from "@/components/layout/AppShell";
import { AppErrorBoundary } from "@/components/feedback/AppErrorBoundary";

export function App() {
  return (
    <AppErrorBoundary>
      <AppShell>
        <Outlet />
      </AppShell>
    </AppErrorBoundary>
  );
}
