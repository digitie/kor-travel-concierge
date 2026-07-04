import { AppShell } from "@/components/AppShell";
import { ApiTestPanel } from "@/components/ApiTestPanel";

export default function ApiTestPage() {
  return (
    <AppShell title="API 테스트">
      <ApiTestPanel />
    </AppShell>
  );
}
