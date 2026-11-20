import { DestinationWorkspace } from "@/components/DestinationWorkspace";
import { HomeActionBanner } from "@/components/HomeActionBanner";

export default function HomePage() {
  return (
    <>
      <HomeActionBanner />
      <div className="flex min-h-0 flex-1 flex-col">
        <DestinationWorkspace />
      </div>
    </>
  );
}
