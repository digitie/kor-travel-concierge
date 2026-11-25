"use client";

import { useCallback, useRef } from "react";

type AutoFocusHandler = (event: Event) => void;

/**
 * 공통 Dialog/AlertDialog(Radix modal)는 닫힐 때 DialogTrigger로만 focus를 돌려준다.
 * trigger 없이 open state로 여는 제어형 대화상자는 닫힌 뒤 focus가 body로 빠진다
 * (Radix DialogContentModal이 onCloseAutoFocus를 항상 preventDefault하고 triggerRef만 본다).
 * 이 앱의 대화상자는 대부분 trigger 없는 제어형이라, 열릴 때 focus를 가졌던 요소(opener)를
 * 기억해 두고 닫힌 뒤 focus가 사라졌을 때만 그 요소로 돌려준다.
 *
 * - 다른 코드가 닫힘과 함께 focus를 의도적으로 옮겼으면(예: 일괄 처리 패널의 다시 열기 버튼)
 *   그대로 둔다 — focus가 body가 아닐 때는 손대지 않는다.
 * - opener가 이미 DOM에서 빠졌으면(삭제된 행 등) Radix 기본 동작에 맡긴다.
 * - 호출자가 넘긴 handler가 먼저 돌고, 그 handler가 preventDefault하면 아무것도 하지 않는다.
 */
export function useDialogFocusReturn(
  onOpenAutoFocus?: AutoFocusHandler,
  onCloseAutoFocus?: AutoFocusHandler,
) {
  const openerRef = useRef<HTMLElement | null>(null);

  const handleOpenAutoFocus = useCallback(
    (event: Event) => {
      // FocusScope는 focus를 대화상자 안으로 옮기기 전에 이 이벤트를 보낸다.
      const active = document.activeElement;
      openerRef.current =
        active instanceof HTMLElement && active !== document.body ? active : null;
      onOpenAutoFocus?.(event);
    },
    [onOpenAutoFocus],
  );

  const handleCloseAutoFocus = useCallback(
    (event: Event) => {
      onCloseAutoFocus?.(event);
      if (event.defaultPrevented) return;
      const opener = openerRef.current;
      if (!opener?.isConnected) return;
      const active = document.activeElement;
      if (active && active !== document.body) return;
      opener.focus();
      // disabled·숨김으로 focus가 실패하면 Radix 기본(trigger) 복귀를 막지 않는다.
      if (document.activeElement === opener) event.preventDefault();
    },
    [onCloseAutoFocus],
  );

  return { onOpenAutoFocus: handleOpenAutoFocus, onCloseAutoFocus: handleCloseAutoFocus };
}
