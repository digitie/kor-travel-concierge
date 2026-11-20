// AppShell 내비 활성 판정의 단일 출처(T-192). 컴포넌트에서 분리해 단위 테스트한다.
// `/jobs`와 `/jobs/:id`는 모두 "작업" 항목을, `/status`는 자기 자신만 활성화한다.

export function isNavItemActive(pathname: string, href: string): boolean {
  if (href === "/") {
    return pathname === "/";
  }
  return pathname === href || pathname.startsWith(`${href}/`);
}

/** 활성 후보 중 가장 구체적인(긴) href를 고른다. */
export function pickActiveNavHref(
  pathname: string,
  hrefs: readonly string[],
): string | undefined {
  return [...hrefs]
    .filter((href) => isNavItemActive(pathname, href))
    .sort((a, b) => b.length - a.length)[0];
}

export type AdminRouteLayout = {
  /** 셸 상단 바의 페이지 이름. 서버 렌더 첫 화면부터 "영역 - 페이지"가 맞도록 경로에서 정한다. */
  title: string;
  /** lg 이상에서 셸을 화면 높이에 고정하고 본문을 남은 높이로 채우는 작업 화면(지도·검수 큐). */
  viewportLocked: boolean;
};

// 레이아웃 셸(app/(admin)/layout.tsx)이 경로마다 쓰는 제목·본문 배치의 단일 출처.
// 설명·동작처럼 페이지 데이터에 매인 값은 각 페이지가 AdminPageTitle로 덮어쓴다.
const ADMIN_ROUTES: readonly { path: string; nested?: boolean; title: string; viewportLocked?: boolean }[] = [
  { path: "/", title: "결과", viewportLocked: true },
  { path: "/collect", title: "수집", viewportLocked: true },
  { path: "/jobs", title: "작업" },
  { path: "/jobs", nested: true, title: "작업 상세" },
  { path: "/review", title: "검수 큐", viewportLocked: true },
  { path: "/review", nested: true, title: "검수 후보 상세" },
  { path: "/place", nested: true, title: "장소 상세" },
  { path: "/settings", title: "설정" },
  { path: "/status", title: "상태" },
  { path: "/dagster", title: "Dagster 운영" },
  { path: "/api-test", title: "API 테스트" },
];

export function adminRouteLayout(pathname: string): AdminRouteLayout {
  const route = ADMIN_ROUTES.find((entry) =>
    entry.nested ? pathname.startsWith(`${entry.path}/`) : pathname === entry.path,
  );
  return { title: route?.title ?? "", viewportLocked: route?.viewportLocked ?? false };
}
