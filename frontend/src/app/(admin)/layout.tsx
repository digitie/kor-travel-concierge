import { connection } from "next/server";
import type { ReactNode } from "react";

import { AppShell } from "@/components/AppShell";
import { VWorldKeyProvider } from "@/components/VWorldKeyProvider";
import { readVWorldBrowserKey } from "@/lib/vworld-browser-key";

// 관리자 화면은 셸을 레이아웃에서 한 번만 그려 이동 사이에 유지한다(drawer 이동 뒤 본문 포커스).
// 로그인·API route는 이 route group 밖이라 셸이 없다.
//
// 지도 키는 실행 시 env에서 읽어 내려준다(T-212). `connection()`으로 요청 시점 렌더링을 강제한다 — 정적
// prerender면 build 때의 env가 HTML에 박혀 이전(build arg) 방식의 문제가 그대로 돌아온다. 이 route group은
// proxy 인증 뒤에만 열리므로 키는 로그인한 관리자에게만 간다.
export default async function AdminLayout({ children }: { children: ReactNode }) {
  await connection();
  const { key } = readVWorldBrowserKey();
  return (
    <VWorldKeyProvider value={key}>
      <AppShell>{children}</AppShell>
    </VWorldKeyProvider>
  );
}
