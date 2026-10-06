"use client";
/* Hallmark · genre: editorial-utilitarian · macrostructure: Rail-Workbench · design-system: design.md · designed-as-app */

import { AppMenu, type AppMenuLinkProps } from "@kor-travel/ui/app-menu";
import { useQueryClient } from "@tanstack/react-query";
import type { ReactNode } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  ActivityIcon,
  ClipboardCheckIcon,
  DownloadCloudIcon,
  ListChecksIcon,
  LogOutIcon,
  MapIcon,
  PanelLeftCloseIcon,
  PanelLeftOpenIcon,
  PlugIcon,
  SettingsIcon,
  type LucideIcon,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { JobStatusLink } from "@/components/JobStatusLink";
import { Button, buttonVariants } from "@/components/ui/button";
import { pickActiveNavHref } from "@/lib/nav";
import { cn } from "@/lib/utils";

type NavItem = {
  href: string;
  label: string;
  icon: LucideIcon;
};

type NavGroup = {
  label: string;
  items: readonly NavItem[];
};

// 최신 kor-travel-map admin의 그룹형 IA를 현재 Concierge의 실제 route에 맞춰 적용한다.
// 존재하지 않는 map route는 추가하지 않고, 기존 기능은 모두 같은 목적지로 유지한다.
const navGroups: readonly NavGroup[] = [
  {
    label: "개요",
    items: [{ href: "/", label: "결과", icon: MapIcon }],
  },
  {
    label: "수집 파이프라인",
    items: [
      { href: "/collect", label: "수집", icon: DownloadCloudIcon },
      { href: "/jobs", label: "작업", icon: ListChecksIcon },
    ],
  },
  {
    label: "검수",
    items: [{ href: "/review", label: "검수", icon: ClipboardCheckIcon }],
  },
  {
    label: "시스템",
    items: [
      { href: "/settings", label: "설정", icon: SettingsIcon },
      { href: "/status", label: "상태", icon: ActivityIcon },
      { href: "/dagster", label: "Dagster", icon: ActivityIcon },
      { href: "/api-test", label: "API 테스트", icon: PlugIcon },
    ],
  },
] as const;

const navItems = navGroups.flatMap((group) => group.items);
const SIDEBAR_COLLAPSED_KEY = "kor-travel-concierge:sidebar-collapsed";
const MAIN_CONTENT_ID = "main-content";

const railRowClass =
  "relative flex h-control-sm shrink-0 items-center gap-2.5 rounded-control px-3 text-xs font-medium whitespace-nowrap text-[var(--shell-rail-muted)] no-underline transition-[color,background-color] duration-fast ease-out hover:bg-white/10 hover:text-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white active:bg-white/15";
const railRowActiveClass =
  "bg-white text-[var(--shell-rail)] hover:bg-white before:absolute before:inset-y-1.5 before:left-0 before:w-0.5 before:rounded-full before:bg-brand";

function MenuLink(props: AppMenuLinkProps) {
  const active = props["aria-current"] === "page";
  return <Link {...props} className={cn(railRowClass, active && railRowActiveClass)} />;
}

export function AppShell({
  title,
  description,
  actions,
  children,
  contentClassName,
  viewportLocked,
}: {
  title: string;
  description?: string;
  actions?: ReactNode;
  children: ReactNode;
  contentClassName?: string;
  viewportLocked?: boolean;
}) {
  const pathname = usePathname();
  const router = useRouter();
  const queryClient = useQueryClient();
  const activeHref = pickActiveNavHref(
    pathname,
    navItems.map((item) => item.href),
  );
  const activeGroup = navGroups.find((group) =>
    group.items.some((item) => item.href === activeHref),
  );
  const menuRef = useRef<HTMLDivElement | null>(null);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => {
    if (typeof window === "undefined") return false;
    return window.localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === "1";
  });

  useEffect(() => {
    window.localStorage.setItem(
      SIDEBAR_COLLAPSED_KEY,
      sidebarCollapsed ? "1" : "0",
    );
  }, [sidebarCollapsed]);

  useEffect(() => {
    if (typeof window === "undefined" || window.innerWidth >= 1024) return;
    const reduceMotion = window.matchMedia(
      "(prefers-reduced-motion: reduce)",
    ).matches;
    menuRef.current?.querySelector<HTMLElement>('[aria-current="page"]')?.scrollIntoView({
      behavior: reduceMotion ? "auto" : "smooth",
      block: "nearest",
      inline: "center",
    });
  }, [activeHref]);

  async function logout() {
    await fetch("/api/auth/logout", { method: "POST" }).catch(() => undefined);
    queryClient.clear();
    router.replace("/login");
    router.refresh();
  }

  return (
    <div className="min-h-dvh bg-surface-page text-text-primary">
      <a
        className="sr-only focus:not-sr-only focus:fixed focus:top-3 focus:left-3 focus:z-50 focus:rounded-control focus:border focus:border-border focus:bg-card focus:px-3 focus:py-2 focus:text-xs focus:font-medium focus:text-text-primary focus:shadow-elevated focus:outline-2 focus:outline-offset-2 focus:outline-focus"
        href={`#${MAIN_CONTENT_ID}`}
      >
        본문으로 건너뛰기
      </a>
      <div
        className={cn(
          "grid min-h-dvh min-w-0",
          sidebarCollapsed
            ? "lg:grid-cols-[4rem_minmax(0,1fr)]"
            : "lg:grid-cols-[16rem_minmax(0,1fr)]",
        )}
      >
        <aside
          className="min-w-0 border-b border-white/15 bg-[var(--shell-rail)] text-[var(--shell-rail-text)] lg:sticky lg:top-0 lg:h-dvh lg:self-start lg:border-r lg:border-b-0 lg:border-white/15"
          data-slot="admin-shell-rail"
        >
          <div className="flex h-full min-w-0 flex-col">
            <div
              className={cn(
                "flex h-14 shrink-0 items-center justify-between gap-2 border-b border-white/15 px-4",
                sidebarCollapsed &&
                  "lg:h-auto lg:flex-col lg:justify-center lg:gap-1 lg:px-0 lg:py-2",
              )}
            >
              <Link
                aria-label="Travel Concierge Admin UI"
                className={cn(
                  "flex min-w-0 items-baseline gap-1.5 rounded-control text-[var(--shell-rail-text)] no-underline hover:no-underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white",
                  sidebarCollapsed && "lg:justify-center",
                )}
                href="/"
              >
                <span
                  className={cn(
                    "truncate text-sm font-semibold tracking-tight",
                    sidebarCollapsed && "lg:hidden",
                  )}
                >
                  Travel Concierge
                </span>
                <span
                  className={cn(
                    "text-2xs font-medium tracking-tight text-[var(--shell-rail-muted)]",
                    sidebarCollapsed && "lg:hidden",
                  )}
                >
                  Admin UI
                </span>
                <span
                  aria-hidden="true"
                  className={cn(
                    "hidden text-xs font-semibold tracking-tight",
                    sidebarCollapsed && "lg:inline",
                  )}
                >
                  tca
                </span>
              </Link>
              <div className="flex shrink-0 items-center gap-1">
                <Button
                  aria-label="로그아웃"
                  className="border border-white/15 text-[var(--shell-rail-muted)] hover:bg-white/10 hover:text-white lg:hidden"
                  size="icon-sm"
                  title="로그아웃"
                  type="button"
                  variant="ghost"
                  onClick={logout}
                >
                  <LogOutIcon aria-hidden="true" />
                </Button>
                <button
                  aria-label={
                    sidebarCollapsed ? "좌측 메뉴 펼치기" : "좌측 메뉴 접기"
                  }
                  className={cn(
                    buttonVariants({ variant: "ghost", size: "icon-sm" }),
                    "hidden border border-white/15 text-[var(--shell-rail-muted)] hover:bg-white/10 hover:text-white lg:inline-flex",
                  )}
                  title={sidebarCollapsed ? "좌측 메뉴 펼치기" : "좌측 메뉴 접기"}
                  type="button"
                  onClick={() => setSidebarCollapsed((current) => !current)}
                >
                  {sidebarCollapsed ? (
                    <PanelLeftOpenIcon aria-hidden="true" />
                  ) : (
                    <PanelLeftCloseIcon aria-hidden="true" />
                  )}
                </button>
              </div>
            </div>
            <div ref={menuRef} data-kt-surface data-sidebar-collapsed={sidebarCollapsed}
              className="concierge-common-menu min-h-0 max-w-full overflow-x-auto px-3 py-2 lg:flex-1 lg:overflow-x-hidden lg:overflow-y-auto lg:py-3">
              <AppMenu label="주요 메뉴" pathname={pathname} activeItemId={activeHref}
                linkComponent={MenuLink} testId="concierge-common-menu"
                groups={navGroups.map(group => ({ id: group.label, label: group.label,
                  items: group.items.map(item => ({ id: item.href, href: item.href,
                    label: item.label, exact: item.href === "/", icon: <item.icon className="size-4" /> })) }))} />
            </div>
            <div
              className={cn(
                "hidden shrink-0 border-t border-white/15 p-2 lg:flex lg:flex-col lg:gap-2",
                sidebarCollapsed && "lg:items-center",
              )}
            >
              {!sidebarCollapsed ? (
                <JobStatusLink
                  className="border-white/15 bg-transparent text-[var(--shell-rail-muted)] hover:border-white/25 hover:bg-white/10 hover:text-white"
                  variant="menu"
                />
              ) : null}
              <Button
                aria-label="로그아웃"
                className={cn(
                  "h-control-sm w-full justify-start border-0 px-3 text-xs font-medium text-[var(--shell-rail-muted)] hover:bg-white/10 hover:text-white",
                  sidebarCollapsed && "lg:size-control lg:justify-center lg:px-0",
                )}
                type="button"
                title={sidebarCollapsed ? "로그아웃" : undefined}
                variant="ghost"
                onClick={logout}
              >
                <LogOutIcon aria-hidden="true" />
                <span className={cn(sidebarCollapsed && "lg:hidden")}>로그아웃</span>
              </Button>
            </div>
          </div>
        </aside>
        <div
          className={cn(
            "flex min-h-dvh min-w-0 flex-col",
            viewportLocked && "ktc-viewport-locked",
          )}
        >
          <header
            className="shrink-0 border-b border-border bg-card px-4 pt-5 pb-4 lg:px-6"
            data-slot="admin-shell-header"
          >
            <div className="flex min-w-0 flex-col gap-1">
              <p className="text-2xs font-medium text-text-secondary">
                {activeGroup?.label ?? "운영"}
              </p>
              <div className="flex min-w-0 flex-col gap-3 md:flex-row md:items-center md:justify-between md:gap-6">
                <h1 className="text-xl leading-tight font-bold tracking-tight text-text-primary">
                  {title}
                </h1>
                {actions ? (
                  <div className="flex shrink-0 flex-wrap items-center gap-2">
                    {actions}
                  </div>
                ) : null}
              </div>
              {description ? (
                <p className="max-w-3xl text-xs text-text-secondary">
                  {description}
                </p>
              ) : null}
            </div>
          </header>
          <main
            className={cn(
              "min-w-0 flex-1 px-4 py-5 focus-visible:outline-0 lg:px-6 lg:py-6",
              viewportLocked && "ktc-viewport-locked-content",
              contentClassName,
            )}
            data-slot="admin-shell-main"
            id={MAIN_CONTENT_ID}
            tabIndex={-1}
          >
            {children}
          </main>
        </div>
      </div>
    </div>
  );
}
