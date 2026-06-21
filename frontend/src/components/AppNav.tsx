"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  ClipboardCheckIcon,
  DownloadCloudIcon,
  MapIcon,
} from "lucide-react";

import { OpsMetricsDialog } from "@/components/OpsMetricsDialog";
import { SettingsDialog } from "@/components/SettingsDialog";
import { cn } from "@/lib/utils";

const LINKS = [
  { href: "/", label: "결과", icon: MapIcon },
  { href: "/collect", label: "수집", icon: DownloadCloudIcon },
  { href: "/review", label: "검수", icon: ClipboardCheckIcon },
];

export function AppNav() {
  const pathname = usePathname();
  return (
    <header className="flex items-center justify-between gap-3 border-b bg-background px-4 py-2">
      <div className="flex items-center gap-3">
        <span className="text-sm font-semibold tracking-tight whitespace-nowrap">
          Kor Travel Concierge
        </span>
        <nav className="flex items-center gap-1">
          {LINKS.map((link) => {
            const active =
              link.href === "/"
                ? pathname === "/"
                : pathname.startsWith(link.href);
            const Icon = link.icon;
            return (
              <Link
                key={link.href}
                href={link.href}
                className={cn(
                  "inline-flex h-9 items-center gap-1.5 rounded-lg px-3 text-sm font-medium transition-colors",
                  active
                    ? "bg-primary/10 text-primary"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground",
                )}
              >
                <Icon className="size-4" />
                {link.label}
              </Link>
            );
          })}
        </nav>
      </div>
      <div className="flex items-center gap-1.5">
        <OpsMetricsDialog />
        <SettingsDialog />
      </div>
    </header>
  );
}
