"use client";

import { useSyncExternalStore } from "react";

// 화면 폭 기준 모바일 여부(SSR-safe). 상세 보기를 모바일=새 페이지 / PC=모달로 분기할 때 사용.
const QUERY = "(max-width: 767px)";

export function useIsMobile(): boolean {
  return useSyncExternalStore(
    (callback) => {
      const mql = window.matchMedia(QUERY);
      mql.addEventListener("change", callback);
      return () => mql.removeEventListener("change", callback);
    },
    () => window.matchMedia(QUERY).matches,
    () => false,
  );
}
