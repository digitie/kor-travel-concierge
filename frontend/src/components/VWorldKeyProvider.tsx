"use client";

import { createContext, useContext, type ReactNode } from "react";

// 서버가 실행 시 env에서 읽은 브라우저용 VWorld 키(빈 값 = 키 없음). (admin)/layout.tsx가 요청마다 채운다.
const VWorldKeyContext = createContext("");

export function VWorldKeyProvider({ value, children }: { value: string; children: ReactNode }) {
  return <VWorldKeyContext value={value}>{children}</VWorldKeyContext>;
}

export function useVWorldBrowserKey(): string {
  return useContext(VWorldKeyContext);
}
