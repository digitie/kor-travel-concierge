import { AppShell } from "@/components/AppShell";
import { StatusDashboard } from "@/components/StatusDashboard";

export default function StatusPage() {
  return (
    <AppShell title="상태">
      <StatusDashboard />
    </AppShell>
  );
}
