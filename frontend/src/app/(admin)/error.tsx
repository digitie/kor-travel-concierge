"use client";

import { AppErrorPanel } from "@/components/layout/AppErrorPanel";

// 관리자 화면의 렌더 오류는 셸(메뉴·상단 바) 안에서만 본문을 대체한다.
// 루트 app/error.tsx는 (admin) 레이아웃 바깥이라 셸까지 지워 이동 수단이 사라진다.
export default function AdminError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return <AppErrorPanel error={error} reset={reset} inShell />;
}
