"use client";

import type { ReactNode } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  ClipboardCheckIcon,
  DownloadCloudIcon,
  LogOutIcon,
  MapIcon,
  SettingsIcon,
  ActivityIcon,
} from "lucide-react";

import { JobStatusLink } from "@/components/JobStatusLink";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const navItems = [
  { href: "/", label: "결과", icon: MapIcon },
  { href: "/collect", label: "수집", icon: DownloadCloudIcon },
  { href: "/review", label: "검수", icon: ClipboardCheckIcon },
  { href: "/status", label: "상태", icon: ActivityIcon },
  { href: "/settings", label: "설정", icon: SettingsIcon },
] as const;

function isActive(pathname: string, href: string) {
  if (href === "/") {
    return pathname === "/";
  }
  if (href === "/status") {
    return pathname === href || pathname.startsWith("/jobs/");
  }
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function AppShell({
  title,
  description,
  section,
  actions,
  children,
  contentClassName,
}: {
  title: string;
  description?: string;
  section?: string;
  actions?: ReactNode;
  children: ReactNode;
  contentClassName?: string;
}) {
  const pathname = usePathname();
  const router = useRouter();
  const activeHref = [...navItems]
    .filter((item) => isActive(pathname, item.href))
    .sort((a, b) => b.href.length - a.href.length)[0]?.href;

  async function logout() {
    await fetch("/api/auth/logout", { method: "POST" }).catch(() => undefined);
    router.replace("/login");
    router.refresh();
  }

  return (
    <main className="min-h-screen bg-surface-page text-text-primary">
      <div className="grid min-h-screen min-w-0 lg:grid-cols-[17rem_1fr]">
        <aside className="min-w-0 border-b border-surface-muted bg-card shadow-[var(--shadow-card)] lg:border-r lg:border-b-0">
          <div className="flex h-full min-w-0 flex-col gap-5 p-4 lg:p-5">
            <Link className="flex items-center gap-2 text-text-primary" href="/">
              <span className="flex size-10 items-center justify-center rounded-xl bg-brand-tint text-brand">
                <MapIcon className="size-4" />
              </span>
              <span className="text-[14px] font-bold">Korea Travel Concierge</span>
            </Link>
            <nav className="flex max-w-full gap-1 overflow-x-auto lg:max-h-[calc(100vh-6rem)] lg:flex-col lg:overflow-y-auto lg:pr-1">
              {navItems.map((item) => {
                const Icon = item.icon;
                const active = item.href === activeHref;
                return (
                  <Link
                    className={cn(
                      buttonVariants({
                        variant: active ? "secondary" : "ghost",
                        size: "sm",
                      }),
                      "justify-start whitespace-nowrap",
                    )}
                    href={item.href}
                    key={item.href}
                  >
                    <Icon data-icon="inline-start" />
                    {item.label}
                  </Link>
                );
              })}
            </nav>
          </div>
        </aside>
        <div className="flex min-h-screen min-w-0 flex-col">
          <header className="px-4 pt-4 lg:px-6 lg:pt-6">
            <div className="flex flex-col gap-4 rounded-2xl bg-card p-4 shadow-[var(--shadow-card)] ring-1 ring-border/70 lg:p-6 xl:flex-row xl:items-start xl:justify-between">
              <div className="flex min-w-0 flex-1 flex-col gap-3">
                <div className="flex min-w-0 flex-col gap-1">
                  <div className="flex flex-wrap items-center gap-2">
                    {section ? <Badge variant="secondary">{section}</Badge> : null}
                    <span className="break-all font-mono text-[12px] text-text-secondary">
                      {pathname}
                    </span>
                  </div>
                  <h1 className="text-[24px] leading-snug font-bold">{title}</h1>
                  {description ? (
                    <p className="max-w-4xl text-[13px] leading-normal text-text-secondary">
                      {description}
                    </p>
                  ) : null}
                </div>
                <JobStatusLink className="max-w-4xl" />
              </div>
              <div className="flex shrink-0 flex-wrap gap-2">
                {actions}
                <Button type="button" variant="outline" size="sm" onClick={logout}>
                  <LogOutIcon data-icon="inline-start" />
                  로그아웃
                </Button>
              </div>
            </div>
          </header>
          <div
            className={cn(
              "min-w-0 flex-1 px-4 py-4 lg:px-6 lg:py-6",
              contentClassName,
            )}
          >
            {children}
          </div>
        </div>
      </div>
    </main>
  );
}
