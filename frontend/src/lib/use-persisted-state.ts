"use client";

import { useEffect, useState } from "react";

// sessionStorage에 동기화되는 상태. 상세 페이지 이동·컴포넌트 리마운트에도 필터/선택
// 같은 화면 상태가 초기화되지 않고 유지된다(쇼핑몰 장바구니처럼).
//
// SSR 하이드레이션 안전을 위해 첫 렌더는 항상 `initial`을 쓰고(서버=클라 일치),
// 마운트 후 effect에서 저장값을 복원한다. 복원 effect가 저장값을 읽은 직후 persist
// effect가 같은 커밋에서 initial을 잠깐 덮어쓰지만, 다음 커밋에서 복원된 값으로 다시
// 저장돼 최종 결과는 항상 저장값이다.
export function usePersistedState<T>(
  key: string,
  initial: T,
): [T, React.Dispatch<React.SetStateAction<T>>] {
  const [value, setValue] = useState<T>(initial);

  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    try {
      const raw = window.sessionStorage.getItem(key);
      if (raw != null) {
        setValue(JSON.parse(raw) as T);
      }
    } catch {
      // 손상된 값이면 initial 유지.
    }
  }, [key]);
  /* eslint-enable react-hooks/set-state-in-effect */

  useEffect(() => {
    try {
      window.sessionStorage.setItem(key, JSON.stringify(value));
    } catch {
      // 저장 실패는 무시(quota/비활성 등).
    }
  }, [key, value]);

  return [value, setValue];
}
