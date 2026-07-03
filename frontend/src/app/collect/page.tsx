import { AppShell } from "@/components/AppShell";
import { CollectWorkspace } from "@/components/CollectWorkspace";

export default function CollectPage() {
  return (
    <AppShell
      title="수집"
      contentClassName="flex min-h-0 flex-1 p-0"
      viewportLocked
    >
      <CollectWorkspace />
    </AppShell>
  );
}
