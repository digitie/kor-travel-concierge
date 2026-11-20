import type { ReactNode } from "react";

import { AppShell } from "@/components/AppShell";

// 관리자 화면은 셸을 레이아웃에서 한 번만 그려 이동 사이에 유지한다(drawer 이동 뒤 본문 포커스).
// 로그인·API route는 이 route group 밖이라 셸이 없다.
export default function AdminLayout({ children }: { children: ReactNode }) {
  return <AppShell>{children}</AppShell>;
}
