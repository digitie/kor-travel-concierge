import { AppNav } from "@/components/AppNav";
import { CollectWorkspace } from "@/components/CollectWorkspace";

export default function CollectPage() {
  return (
    <main className="flex min-h-screen flex-col bg-background">
      <AppNav />
      <CollectWorkspace />
    </main>
  );
}
