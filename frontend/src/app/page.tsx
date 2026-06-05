import { HarvestConsole } from "@/components/HarvestConsole";
import { VWorldMap } from "@/components/VWorldMap";

export default function HomePage() {
  return (
    <main className="flex min-h-screen flex-col bg-background md:flex-row">
      <section
        id="destination-list"
        className="min-h-[42rem] border-b md:h-screen md:w-[24rem] md:border-b-0 md:border-r"
      >
        <HarvestConsole />
      </section>
      <section className="min-h-[32rem] flex-1 md:h-screen">
        <VWorldMap />
      </section>
    </main>
  );
}
