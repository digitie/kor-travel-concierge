"use client";

import { AdminShell, type AdminShellSlotState } from "@kor-travel/ui/admin-shell";
import { AppMenu, type AppMenuLinkProps } from "@kor-travel/ui/app-menu";
import { useQueryClient } from "@tanstack/react-query";
import {
  ActivityIcon, ClipboardCheckIcon, DownloadCloudIcon, ListChecksIcon,
  LogOutIcon, MapIcon, PlugIcon, SettingsIcon, type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import type { ReactNode } from "react";

import { JobStatusLink } from "@/components/JobStatusLink";
import { Button } from "@/components/ui/button";
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
  return (
    <Link
      {...props}
      className={cn(props.className, railRowClass, props["aria-current"] === "page" && railRowActiveClass)}
    />
  );
}

function ShellBrand({ collapsed }: AdminShellSlotState) {
  return (
    <Link
      aria-label="Travel Concierge Admin UI"
      className="min-w-0 truncate rounded-control text-sm font-semibold tracking-tight text-[var(--shell-rail-text)] no-underline hover:no-underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white"
      href="/"
    >
      {collapsed ? "tca" : "Travel Concierge"}
    </Link>
  );
}

function ShellFooter({ collapsed, inDrawer, logout }: AdminShellSlotState & { logout: () => Promise<void> }) {
  return (
    <div className={cn("flex flex-col gap-2 p-2", collapsed && "items-center")}>
      {/* 작업 큐 observer는 rail에 하나만 둔다. drawer는 기존 메뉴로 작업 화면에 접근한다. */}
      {!collapsed && !inDrawer ? (
        <JobStatusLink
          className="border-white/15 bg-transparent text-[var(--shell-rail-muted)] hover:border-white/25 hover:bg-white/10 hover:text-white"
          variant="menu"
        />
      ) : null}
      <Button
        aria-label="로그아웃"
        className={cn(
          "h-control-sm w-full justify-start border-0 px-3 text-xs font-medium text-[var(--shell-rail-muted)] hover:bg-white/10 hover:text-white",
          collapsed && "size-control justify-center px-0",
        )}
        type="button"
        title={collapsed ? "로그아웃" : undefined}
        variant="ghost"
        onClick={logout}
      >
        <LogOutIcon aria-hidden="true" />
        {!collapsed ? <span>로그아웃</span> : null}
      </Button>
    </div>
  );
}

export function AppShell({ title, description, actions, children, contentClassName, viewportLocked }: {
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
  const activeHref = pickActiveNavHref(pathname, navItems.map((item) => item.href));
  const activeGroup = navGroups.find((group) => group.items.some((item) => item.href === activeHref));

  async function logout() {
    await fetch("/api/auth/logout", { method: "POST" }).catch(() => undefined);
    queryClient.clear();
    router.replace("/login");
    router.refresh();
  }

  return (
    <AdminShell
      area={activeGroup?.label ?? "운영"}
      title={title}
      description={description}
      actions={actions}
      brand={(slot) => <ShellBrand {...slot} />}
      railFooter={(slot) => <ShellFooter {...slot} logout={logout} />}
      navigationKey={pathname}
      collapsedStorageKey={SIDEBAR_COLLAPSED_KEY}
      fillViewport={viewportLocked}
      mainId={MAIN_CONTENT_ID}
      labels={{ collapseRail: "좌측 메뉴 접기", expandRail: "좌측 메뉴 펼치기", menu: "주요 메뉴" }}
      className="concierge-admin-shell"
      railClassName="concierge-common-rail"
      drawerClassName="concierge-common-drawer"
      mainClassName={cn("px-4 py-5 lg:px-6 lg:py-6", viewportLocked && "lg:overflow-hidden", contentClassName)}
      menu={
        <div className="concierge-common-menu">
          <AppMenu
            label="주요 메뉴"
            pathname={pathname}
            activeItemId={activeHref}
            linkComponent={MenuLink}
            testId="concierge-common-menu"
            groups={navGroups.map((group) => ({
              id: group.label,
              label: group.label,
              items: group.items.map((item) => ({
                id: item.href, href: item.href, label: item.label, exact: item.href === "/",
                icon: <item.icon className="size-4" />,
              })),
            }))}
          />
        </div>
      }
    >
      {children}
    </AdminShell>
  );
}
