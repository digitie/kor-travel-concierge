"use client";

import { useState } from "react";
import { PanelLeftCloseIcon, PanelLeftOpenIcon } from "lucide-react";

import { DestinationWorkspace } from "@/components/DestinationWorkspace";
import { HarvestConsole } from "@/components/HarvestConsole";
import { cn } from "@/lib/utils";

export default function HomePage() {
  const [collapsed, setCollapsed] = useState(false);

  return (
    <main className="flex min-h-screen flex-col bg-background md:flex-row">
      <section
        id="destination-list"
        className={cn(
          "relative shrink-0 border-b transition-[width] duration-200 md:h-screen md:border-b-0 md:border-r",
          collapsed ? "md:w-12" : "min-h-[42rem] md:w-[24rem]",
        )}
      >
        {collapsed ? (
          <button
            type="button"
            onClick={() => setCollapsed(false)}
            aria-label="수집 사이드바 펼치기"
            className="flex h-11 w-full items-center justify-center gap-2 text-muted-foreground hover:bg-muted hover:text-foreground md:h-screen md:w-12 md:flex-col md:gap-3 md:py-4"
          >
            <PanelLeftOpenIcon className="size-5" />
            <span className="text-[11px] font-medium tracking-wide md:[writing-mode:vertical-rl]">
              수집 작업
            </span>
          </button>
        ) : (
          <div className="relative h-full">
            <button
              type="button"
              onClick={() => setCollapsed(true)}
              aria-label="수집 사이드바 접기"
              className="absolute top-5 right-3 z-10 rounded-md p-1 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            >
              <PanelLeftCloseIcon className="size-4" />
            </button>
            <HarvestConsole />
          </div>
        )}
      </section>
      <section className="min-h-[32rem] flex-1 md:h-screen">
        <DestinationWorkspace />
      </section>
    </main>
  );
}
