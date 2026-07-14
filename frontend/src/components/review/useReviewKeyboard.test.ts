import { describe, expect, it, vi } from "vitest";

import {
  isInteractiveElement,
  resolveReviewShortcut,
  runReviewShortcut,
  shouldIgnoreReviewShortcut,
  type ReviewKeyboardHandlers,
  type ReviewShortcutGuardContext,
} from "./useReviewKeyboard";

function fakeElement({
  tag = "div",
  role = null,
  contentEditable = false,
  insideContainer = false,
}: {
  tag?: string;
  role?: string | null;
  contentEditable?: boolean;
  insideContainer?: boolean;
} = {}): Element {
  return {
    tagName: tag.toUpperCase(),
    isContentEditable: contentEditable,
    getAttribute: (name: string) => (name === "role" ? role : null),
    closest: () => (insideContainer ? ({} as Element) : null),
  } as unknown as Element;
}

function guard(
  overrides: Partial<ReviewShortcutGuardContext> = {},
): ReviewShortcutGuardContext {
  return {
    defaultPrevented: false,
    repeat: false,
    ctrlKey: false,
    metaKey: false,
    altKey: false,
    isComposing: false,
    keyCode: 74,
    targetInteractive: false,
    activeInteractive: false,
    ...overrides,
  };
}

describe("shouldIgnoreReviewShortcut", () => {
  it("확장 포커스 가드가 없으면 통과(무시하지 않음)한다", () => {
    expect(shouldIgnoreReviewShortcut(guard())).toBe(false);
  });

  it.each([
    ["defaultPrevented", { defaultPrevented: true }],
    ["repeat", { repeat: true }],
    ["ctrl 조합", { ctrlKey: true }],
    ["meta 조합", { metaKey: true }],
    ["alt 조합", { altKey: true }],
    ["IME isComposing", { isComposing: true }],
    ["IME keyCode 229", { keyCode: 229 }],
    ["target 상호작용 요소", { targetInteractive: true }],
    ["active 상호작용 요소", { activeInteractive: true }],
  ])("%s이면 단축키를 무시한다", (_label, overrides) => {
    expect(shouldIgnoreReviewShortcut(guard(overrides))).toBe(true);
  });

  it("shift 조합은 허용한다(? 등 shift 문자 입력)", () => {
    // shiftKey는 가드 컨텍스트에 없다 — 즉 shift는 무시 사유가 아니다.
    expect(shouldIgnoreReviewShortcut(guard())).toBe(false);
  });
});

describe("isInteractiveElement", () => {
  it("일반 비상호작용 요소는 false다", () => {
    expect(isInteractiveElement(null)).toBe(false);
    expect(isInteractiveElement(fakeElement({ tag: "div" }))).toBe(false);
    expect(isInteractiveElement(fakeElement({ tag: "span" }))).toBe(false);
  });

  it.each(["input", "textarea", "select", "button", "a"])(
    "%s 태그는 true다",
    (tag) => {
      expect(isInteractiveElement(fakeElement({ tag }))).toBe(true);
    },
  );

  it("contenteditable은 true다", () => {
    expect(
      isInteractiveElement(fakeElement({ contentEditable: true })),
    ).toBe(true);
  });

  it.each([
    "textbox",
    "combobox",
    "searchbox",
    "listbox",
    "option",
    "menu",
    "menuitem",
    "dialog",
    "alertdialog",
  ])("role=%s는 true다(combobox 옵션·? alertdialog 오발화 방지)", (role) => {
    expect(isInteractiveElement(fakeElement({ role }))).toBe(true);
  });

  it("dialog/menu/listbox 컨테이너 내부(closest 매칭) 포커스는 true다", () => {
    expect(
      isInteractiveElement(fakeElement({ tag: "div", insideContainer: true })),
    ).toBe(true);
  });
});

describe("resolveReviewShortcut", () => {
  it("1–9는 hit ordinal로 사상한다", () => {
    expect(resolveReviewShortcut("1")).toEqual({ type: "selectHit", ordinal: 1 });
    expect(resolveReviewShortcut("9")).toEqual({ type: "selectHit", ordinal: 9 });
  });

  it("0과 두 자리 숫자는 매칭하지 않는다", () => {
    expect(resolveReviewShortcut("0")).toBeNull();
    expect(resolveReviewShortcut("10")).toBeNull();
  });

  it.each([
    ["j", "next"],
    ["J", "next"],
    ["k", "prev"],
    ["x", "exclude"],
    ["u", "undo"],
    ["Enter", "save"],
    ["/", "focusSearch"],
    ["?", "help"],
  ])("%s → %s", (key, type) => {
    expect(resolveReviewShortcut(key)?.type).toBe(type);
  });

  it("매핑 없는 키는 null이다", () => {
    expect(resolveReviewShortcut("a")).toBeNull();
    expect(resolveReviewShortcut("Escape")).toBeNull();
  });
});

describe("runReviewShortcut", () => {
  function handlers(): ReviewKeyboardHandlers & {
    [K in keyof ReviewKeyboardHandlers]: ReviewKeyboardHandlers[K];
  } {
    return {
      enabled: true,
      onNextCandidate: vi.fn(),
      onPrevCandidate: vi.fn(),
      onSelectHit: vi.fn(),
      onSave: vi.fn(),
      onExclude: vi.fn(),
      onUndo: vi.fn(),
      onFocusSearch: vi.fn(),
      onToggleHelp: vi.fn(),
    };
  }

  it("selectHit는 ordinal을 그대로 전달한다", () => {
    const h = handlers();
    runReviewShortcut({ type: "selectHit", ordinal: 3 }, h);
    expect(h.onSelectHit).toHaveBeenCalledWith(3);
  });

  it("각 액션이 대응 핸들러 하나만 호출한다", () => {
    const cases: { action: Parameters<typeof runReviewShortcut>[0]; key: keyof ReviewKeyboardHandlers }[] = [
      { action: { type: "next" }, key: "onNextCandidate" },
      { action: { type: "prev" }, key: "onPrevCandidate" },
      { action: { type: "save" }, key: "onSave" },
      { action: { type: "exclude" }, key: "onExclude" },
      { action: { type: "undo" }, key: "onUndo" },
      { action: { type: "focusSearch" }, key: "onFocusSearch" },
      { action: { type: "help" }, key: "onToggleHelp" },
    ];
    for (const { action, key } of cases) {
      const h = handlers();
      runReviewShortcut(action, h);
      expect(h[key]).toHaveBeenCalledTimes(1);
    }
  });

  it("onToggleHelp 미제공이면 help 액션은 무해하다", () => {
    const h = handlers();
    h.onToggleHelp = undefined;
    expect(() => runReviewShortcut({ type: "help" }, h)).not.toThrow();
  });
});
