"use client";

import { useEffect, useRef } from "react";

/**
 * 검수 처리 단축키(T-187, 로드맵 PR-16).
 *
 * 전역 keydown 하나로 처리하되, 확장 포커스 가드로 오작동을 막는다. 아래 중 하나라도
 * 참이면 단축키를 무시한다:
 *  - 이미 다른 핸들러가 처리(`defaultPrevented`)
 *  - 반복 keydown(`repeat`) — 키 누름 유지로 인한 폭주 방지
 *  - modifier 조합(`ctrl`/`meta`/`alt`) — 브라우저/OS 단축키와 충돌 방지(shift는 허용)
 *  - IME 조합 중(`isComposing` 또는 legacy keyCode 229)
 *  - 포커스가 편집/상호작용 요소(input·textarea·select·contenteditable) 또는
 *    button·link, 그리고 dialog/menu 컨테이너 내부에 있을 때
 *
 * 가드/디스패치 판정은 DOM 없이 단위 테스트할 수 있도록 순수 함수로 분리한다.
 */
export type ReviewKeyboardHandlers = {
  /** 단축키 활성 여부(예: 목록 URL 상태가 확정된 검수 화면). */
  enabled: boolean;
  onNextCandidate: () => void;
  onPrevCandidate: () => void;
  /** 검색 hit ordinal(1부터) 선택 — `allHits[n-1]`. */
  onSelectHit: (ordinal: number) => void;
  onSave: () => void;
  onExclude: () => void;
  onUndo: () => void;
  onFocusSearch: () => void;
  onToggleHelp?: () => void;
};

export const REVIEW_SHORTCUTS: readonly { keys: string; label: string }[] = [
  { keys: "J / K", label: "다음 / 이전 후보" },
  { keys: "1–9", label: "검색 결과 n번째 선택" },
  { keys: "Enter", label: "확정 저장(폼 유효 시)" },
  { keys: "X", label: "후보 제외" },
  { keys: "U", label: "마지막 처리 되돌리기" },
  { keys: "/", label: "검색 입력 포커스" },
  { keys: "?", label: "단축키 도움말" },
];

/** 포커스 가드에 필요한 이벤트/포커스 정보(순수 판정용). */
export type ReviewShortcutGuardContext = {
  defaultPrevented: boolean;
  repeat: boolean;
  ctrlKey: boolean;
  metaKey: boolean;
  altKey: boolean;
  isComposing: boolean;
  keyCode?: number;
  /** keydown target이 상호작용 요소인가. */
  targetInteractive: boolean;
  /** 현재 활성 요소(document.activeElement)가 상호작용 요소인가. */
  activeInteractive: boolean;
};

/** 전역 단축키를 무시해야 하는지 판정하는 순수 함수(단위 테스트 대상). */
export function shouldIgnoreReviewShortcut(
  ctx: ReviewShortcutGuardContext,
): boolean {
  if (ctx.defaultPrevented) return true;
  if (ctx.repeat) return true;
  if (ctx.ctrlKey || ctx.metaKey || ctx.altKey) return true;
  // IME 조합 중(한글 등): isComposing 미지원 브라우저 대비 keyCode 229도 함께 본다.
  if (ctx.isComposing || ctx.keyCode === 229) return true;
  if (ctx.targetInteractive || ctx.activeInteractive) return true;
  return false;
}

export type ReviewShortcutAction =
  | { type: "next" }
  | { type: "prev" }
  | { type: "selectHit"; ordinal: number }
  | { type: "save" }
  | { type: "exclude" }
  | { type: "undo" }
  | { type: "focusSearch" }
  | { type: "help" };

/** keydown key를 검수 액션으로 사상하는 순수 함수. 매칭 없으면 null. */
export function resolveReviewShortcut(key: string): ReviewShortcutAction | null {
  if (/^[1-9]$/.test(key)) {
    return { type: "selectHit", ordinal: Number(key) };
  }
  switch (key.toLowerCase()) {
    case "j":
      return { type: "next" };
    case "k":
      return { type: "prev" };
    case "x":
      return { type: "exclude" };
    case "u":
      return { type: "undo" };
    case "enter":
      return { type: "save" };
    case "/":
      return { type: "focusSearch" };
    case "?":
      return { type: "help" };
    default:
      return null;
  }
}

/** 액션을 핸들러로 실행한다(순수 디스패치, 단위 테스트 대상). */
export function runReviewShortcut(
  action: ReviewShortcutAction,
  handlers: ReviewKeyboardHandlers,
): void {
  switch (action.type) {
    case "next":
      handlers.onNextCandidate();
      return;
    case "prev":
      handlers.onPrevCandidate();
      return;
    case "selectHit":
      handlers.onSelectHit(action.ordinal);
      return;
    case "save":
      handlers.onSave();
      return;
    case "exclude":
      handlers.onExclude();
      return;
    case "undo":
      handlers.onUndo();
      return;
    case "focusSearch":
      handlers.onFocusSearch();
      return;
    case "help":
      handlers.onToggleHelp?.();
      return;
  }
}

const INTERACTIVE_ROLES = new Set([
  "textbox",
  "combobox",
  "searchbox",
  "listbox",
  "option",
  "menu",
  "menuitem",
  "dialog",
  "alertdialog",
]);

const INTERACTIVE_CONTAINER_SELECTOR =
  "[role='dialog'],[role='alertdialog'],[role='menu'],[role='listbox'],dialog";

/** 포커스 요소가 편집/상호작용/오버레이 컨테이너인지 판정한다(순수, 단위 테스트 대상). */
export function isInteractiveElement(element: Element | null): boolean {
  if (!element) return false;
  const tag = element.tagName?.toLowerCase();
  if (
    tag === "input" ||
    tag === "textarea" ||
    tag === "select" ||
    tag === "button" ||
    tag === "a"
  ) {
    return true;
  }
  if ((element as HTMLElement).isContentEditable) return true;
  const role = element.getAttribute?.("role");
  if (role && INTERACTIVE_ROLES.has(role)) return true;
  // dialog/alertdialog/menu/listbox 컨테이너 안쪽에 포커스가 있어도(닫기 버튼·
  // combobox 옵션 등) 단축키를 막는다.
  if (
    typeof element.closest === "function" &&
    element.closest(INTERACTIVE_CONTAINER_SELECTOR)
  ) {
    return true;
  }
  return false;
}

function guardContextFromEvent(event: KeyboardEvent): ReviewShortcutGuardContext {
  const target =
    event.target instanceof Element ? (event.target as Element) : null;
  const active =
    typeof document !== "undefined" ? document.activeElement : null;
  return {
    defaultPrevented: event.defaultPrevented,
    repeat: event.repeat,
    ctrlKey: event.ctrlKey,
    metaKey: event.metaKey,
    altKey: event.altKey,
    isComposing: event.isComposing,
    keyCode: event.keyCode,
    targetInteractive: isInteractiveElement(target),
    activeInteractive: isInteractiveElement(active),
  };
}

export function useReviewKeyboard(handlers: ReviewKeyboardHandlers): void {
  const handlersRef = useRef(handlers);
  // 매 렌더마다 최신 핸들러로 갱신하되 리스너는 한 번만 등록한다(stable listener).
  useEffect(() => {
    handlersRef.current = handlers;
  });

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      const handler = handlersRef.current;
      if (!handler.enabled) return;
      if (shouldIgnoreReviewShortcut(guardContextFromEvent(event))) return;
      const action = resolveReviewShortcut(event.key);
      if (!action) return;
      if (action.type === "help" && !handler.onToggleHelp) return;
      event.preventDefault();
      runReviewShortcut(action, handler);
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);
}
