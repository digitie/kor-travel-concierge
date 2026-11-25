"use client";

import type { ComponentProps } from "react";
import { DialogContent as CommonDialogContent } from "@kor-travel/ui/dialog";

import { useDialogFocusReturn } from "@/lib/dialog-focus-return";

// star export는 React Doctor only-export-components에 걸려 이름을 명시한다(공통 0.2.6 목록과 같다).
export {
  Dialog,
  DialogClose,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogOverlay,
  DialogPortal,
  DialogTitle,
  DialogTrigger,
} from "@kor-travel/ui/dialog";

// trigger 없는 제어형 대화상자도 닫힌 뒤 연 요소로 focus를 돌려준다(lib/dialog-focus-return).
export function DialogContent({
  onOpenAutoFocus,
  onCloseAutoFocus,
  ...props
}: ComponentProps<typeof CommonDialogContent>) {
  const focusReturn = useDialogFocusReturn(onOpenAutoFocus, onCloseAutoFocus);
  return <CommonDialogContent {...props} {...focusReturn} />;
}
