import { AppShell } from "@/components/AppShell";
import { SettingsPanel } from "@/components/SettingsPanel";

export default function SettingsPage() {
  return (
    <AppShell title="설정">
      <SettingsPanel />
    </AppShell>
  );
}
