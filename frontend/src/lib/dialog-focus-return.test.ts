// @vitest-environment jsdom

import { act, createElement, useState, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";

let root: Root;
let host: HTMLDivElement;

// Radix FocusScope는 unmount 뒤 setTimeout(0)에서 onCloseAutoFocus를 보낸다.
async function flush() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

async function press(key: string) {
  await act(async () => {
    (document.activeElement ?? document.body).dispatchEvent(
      new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true }),
    );
  });
  await flush();
}

async function openWith(button: HTMLElement) {
  await act(async () => {
    button.focus();
    button.click();
  });
  await flush();
}

function byText(text: string) {
  const found = [...document.querySelectorAll<HTMLElement>("button")].find(
    (element) => element.textContent === text,
  );
  expect(found, text).toBeDefined();
  return found!;
}

// trigger 없이 open state로만 여는 제어형 대화상자(장소 상세·검수 단축키 도움말과 같은 모양).
function ControlledDialog({ onClosed }: { onClosed?: () => void }) {
  const [open, setOpen] = useState(false);
  return createElement(
    "div",
    null,
    createElement("button", { type: "button", onClick: () => setOpen(true) }, "상세 열기"),
    createElement("button", { type: "button" }, "다른 버튼"),
    createElement(
      Dialog,
      {
        open,
        onOpenChange: (next: boolean) => {
          setOpen(next);
          if (!next) onClosed?.();
        },
      },
      createElement(
        DialogContent,
        null,
        createElement(DialogTitle, null, "장소 상세"),
        createElement(DialogDescription, null, "검증용 대화상자"),
        createElement("button", { type: "button" }, "안쪽 동작"),
      ),
    ),
  );
}

function ControlledAlert({ removeOpenerOnClose = false }: { removeOpenerOnClose?: boolean }) {
  const [open, setOpen] = useState(false);
  const [openerVisible, setOpenerVisible] = useState(true);
  const opener: ReactNode = openerVisible
    ? createElement("button", { type: "button", onClick: () => setOpen(true) }, "삭제")
    : null;
  return createElement(
    "div",
    null,
    opener,
    createElement(
      AlertDialog,
      {
        open,
        onOpenChange: (next: boolean) => {
          setOpen(next);
          if (!next && removeOpenerOnClose) setOpenerVisible(false);
        },
      },
      createElement(
        AlertDialogContent,
        null,
        createElement(AlertDialogTitle, null, "삭제 확인"),
        createElement(AlertDialogDescription, null, "검증용 확인창"),
        createElement(AlertDialogCancel, null, "취소"),
      ),
    ),
  );
}

beforeEach(() => {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

describe("trigger 없는 제어형 대화상자의 focus 복귀", () => {
  it("Dialog를 Escape로 닫으면 연 버튼으로 focus를 돌려준다", async () => {
    await act(async () => root.render(createElement(ControlledDialog)));
    const opener = byText("상세 열기");
    await openWith(opener);
    expect(document.querySelector("[role=dialog]")).not.toBeNull();
    expect(document.activeElement).not.toBe(opener);

    await press("Escape");

    expect(document.querySelector("[role=dialog]")).toBeNull();
    expect(document.activeElement).toBe(opener);
  });

  it("닫힘과 함께 다른 요소로 옮긴 focus는 빼앗지 않는다", async () => {
    const moveFocus = () => setTimeout(() => byText("다른 버튼").focus(), 0);
    await act(async () => root.render(createElement(ControlledDialog, { onClosed: moveFocus })));
    await openWith(byText("상세 열기"));

    await press("Escape");

    expect(document.activeElement).toBe(byText("다른 버튼"));
  });

  it("AlertDialog 취소도 연 버튼으로 focus를 돌려준다", async () => {
    await act(async () => root.render(createElement(ControlledAlert)));
    const opener = byText("삭제");
    await openWith(opener);
    expect(document.querySelector("[role=alertdialog]")).not.toBeNull();

    await act(async () => byText("취소").click());
    await flush();

    expect(document.querySelector("[role=alertdialog]")).toBeNull();
    expect(document.activeElement).toBe(opener);
  });

  it("연 요소가 사라졌으면 focus를 옮기지 않고 오류 없이 닫는다", async () => {
    await act(async () => root.render(createElement(ControlledAlert, { removeOpenerOnClose: true })));
    await openWith(byText("삭제"));

    await press("Escape");

    expect(document.querySelector("[role=alertdialog]")).toBeNull();
    expect(document.querySelectorAll("button")).toHaveLength(0);
    expect(document.activeElement).toBe(document.body);
  });
});
