import { AppShell } from "@/components/AppShell";
import { DestinationWorkspace } from "@/components/DestinationWorkspace";

export default function HomePage() {
  return (
    <AppShell
      title="결과"
      contentClassName="flex min-h-0 flex-1 p-0"
      viewportLocked
    >
      <DestinationWorkspace />
    </AppShell>
  );
}
