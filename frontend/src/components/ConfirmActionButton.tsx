"use client";

import { useState, type ReactElement, type ReactNode } from "react";

import {
  AlertDialog,
  AlertDialogClose,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";

// window.confirm 대체 — 파괴적 액션 공통 확인 다이얼로그.
// trigger로 받은 버튼을 그대로 렌더하고, 확인을 누르면 onConfirm을 실행한다.
export function ConfirmActionButton({
  trigger,
  title,
  description,
  confirmLabel = "삭제",
  confirmVariant = "destructive",
  onConfirm,
}: {
  /** 트리거로 쓸 버튼 요소(스타일·아이콘은 호출부가 정한다) */
  trigger: ReactElement;
  title: string;
  description?: ReactNode;
  confirmLabel?: string;
  confirmVariant?: "default" | "destructive" | "outline";
  onConfirm: () => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <AlertDialog open={open} onOpenChange={setOpen}>
      <AlertDialogTrigger render={trigger} />
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{title}</AlertDialogTitle>
          {description ? (
            <AlertDialogDescription>{description}</AlertDialogDescription>
          ) : null}
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogClose
            render={
              <Button type="button" variant="outline" size="sm">
                취소
              </Button>
            }
          />
          <Button
            type="button"
            size="sm"
            variant={confirmVariant}
            onClick={() => {
              setOpen(false);
              onConfirm();
            }}
          >
            {confirmLabel}
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
