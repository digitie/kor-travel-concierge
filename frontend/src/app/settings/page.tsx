import { AppShell } from "@/components/AppShell";
import { SettingsPanel } from "@/components/SettingsPanel";

export default function SettingsPage() {
  return (
    <AppShell
      title="설정"
      description="AI 엔진, 사전 프롬프트, 외부 API 키, 공개 API 키와 로그인 기록을 관리합니다."
      section="운영"
    >
      <SettingsPanel />
    </AppShell>
  );
}
