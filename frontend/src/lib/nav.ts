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
