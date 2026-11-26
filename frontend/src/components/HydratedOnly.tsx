"use client";

import { useSyncExternalStore, type ReactNode } from "react";

// 서버 렌더와 hydration 동안에는 fallback만 그리고, hydration이 끝난 뒤에 children을 그린다.
//
// 관리자 화면은 T-212부터 요청 시점 렌더링이다(실행 시 지도 키). 정적 prerender 시절에는 useSearchParams를 읽는
// 본문이 가까운 Suspense까지 client 렌더로 넘어갔는데, 요청 시점 렌더링에서는 서버에서도 그려진다. Suspense 경계는
// root commit 뒤 따로 hydrate되므로(selective hydration), 그 사이 헤더(JobStatusLink)가 같은 react-query 캐시를
// 채우면 첫 client 렌더가 서버 HTML과 달라 React #418이 난다. 이 경계가 정적 prerender 시절의 client 렌더 경계를
// 그대로 되살린다.
//
// 계약: 헤더와 같은 react-query key(예: RUN_QUEUE_QUERY_KEY)를 render에서 읽는 본문을 Suspense 안(따로 hydrate되는
// 경계)에 새로 두거나 본문에서 useSearchParams를 쓰면 이 경계로 감싼다. `/`(HomeActionBanner)·`/collect`도 같은
// key를 쓰지만 Suspense 밖이라 root와 함께 hydrate돼 감싸지 않았다.
const subscribe = () => () => undefined;
const getClientSnapshot = () => true;
const getServerSnapshot = () => false;

export function HydratedOnly({ children, fallback }: { children: ReactNode; fallback: ReactNode }) {
  const hydrated = useSyncExternalStore(subscribe, getClientSnapshot, getServerSnapshot);
  return hydrated ? children : fallback;
}
