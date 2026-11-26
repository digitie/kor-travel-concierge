"use client";

import { useSyncExternalStore, type ReactNode } from "react";

// 서버 렌더와 hydration 동안에는 fallback만 그리고, hydration이 끝난 뒤에 children을 그린다.
//
// 관리자 화면은 T-212부터 요청 시점 렌더링이다(실행 시 지도 키). 정적 prerender 시절에는 useSearchParams를 읽는
// 본문이 가까운 Suspense까지 client 렌더로 넘어갔는데, 요청 시점 렌더링에서는 서버에서도 그려진다. 그 본문이
// hydrate되기 전에 헤더(JobStatusLink)가 같은 react-query 캐시를 채우면 첫 client 렌더가 서버 HTML과 달라
// React #418이 난다. 이 경계가 정적 prerender 시절의 client 렌더 경계를 그대로 되살린다.
const subscribe = () => () => undefined;
const getClientSnapshot = () => true;
const getServerSnapshot = () => false;

export function HydratedOnly({ children, fallback }: { children: ReactNode; fallback: ReactNode }) {
  const hydrated = useSyncExternalStore(subscribe, getClientSnapshot, getServerSnapshot);
  return hydrated ? children : fallback;
}
