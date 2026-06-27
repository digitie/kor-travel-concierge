import { AppShell } from "@/components/AppShell";
import { StatusDashboard } from "@/components/StatusDashboard";

export default function StatusPage() {
  return (
    <AppShell
      title="상태"
      description="작업, 데이터, 보안 상태를 주제별로 확인합니다."
      section="운영"
    >
      <StatusDashboard />
    </AppShell>
  );
}
