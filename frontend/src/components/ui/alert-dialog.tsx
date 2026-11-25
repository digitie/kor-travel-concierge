'use client';

import type { ComponentProps } from 'react';
import { AlertDialogContent as CommonAlertDialogContent } from '@kor-travel/ui/alert-dialog';

import { useDialogFocusReturn } from '@/lib/dialog-focus-return';

// 공통 Radix 프리미티브를 기존 경로로 제공한다. star export는 React Doctor only-export-components에
// 걸려 이름을 명시한다(공통 0.2.6 목록과 같다).
export {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogMedia,
  AlertDialogOverlay,
  AlertDialogPortal,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@kor-travel/ui/alert-dialog';

// trigger 없는 제어형 확인창도 닫힌 뒤 연 요소로 focus를 돌려준다(lib/dialog-focus-return).
export function AlertDialogContent({
  onOpenAutoFocus,
  onCloseAutoFocus,
  ...props
}: ComponentProps<typeof CommonAlertDialogContent>) {
  const focusReturn = useDialogFocusReturn(onOpenAutoFocus, onCloseAutoFocus);
  return <CommonAlertDialogContent {...props} {...focusReturn} />;
}
