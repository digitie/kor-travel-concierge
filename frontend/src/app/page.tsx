import { AppShell } from "@/components/AppShell";
import { DestinationWorkspace } from "@/components/DestinationWorkspace";
import { HomeActionBanner } from "@/components/HomeActionBanner";

export default function HomePage() {
  return (
    <AppShell
      title="결과"
      contentClassName="flex min-h-0 flex-1 flex-col p-0"
      viewportLocked
    >
      <HomeActionBanner />
      <div className="flex min-h-0 flex-1 flex-col">
        <DestinationWorkspace />
      </div>
    </AppShell>
  );
}
