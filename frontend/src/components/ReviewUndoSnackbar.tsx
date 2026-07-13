"use client";

import { Loader2Icon, XIcon } from "lucide-react";

import { Button } from "@/components/ui/button";

export function ReviewUndoSnackbar({
  candidateName,
  actionLabel,
  pending,
  disabled,
  error,
  onUndo,
  onDismiss,
}: {
  candidateName: string;
  actionLabel: string;
  pending: boolean;
  disabled: boolean;
  error: string | null;
  onUndo: () => void;
  onDismiss: () => void;
}) {
  return (
    <div
      role="status"
      aria-live="polite"
      className="fixed right-4 bottom-4 z-50 flex w-[min(28rem,calc(100vw-2rem))] flex-col gap-2 rounded-xl border bg-background p-3 shadow-lg"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm font-medium">
            {candidateName} 후보를 {actionLabel}했습니다.
          </p>
          <p className="text-xs text-muted-foreground">
            마지막으로 처리한 이 후보만 되돌릴 수 있습니다.
          </p>
        </div>
        <Button
          type="button"
          size="icon-xs"
          variant="ghost"
          aria-label="되돌리기 알림 닫기"
          disabled={pending}
          onClick={onDismiss}
        >
          <XIcon className="size-4" />
        </Button>
      </div>
      {error ? (
        <p role="alert" className="text-xs text-destructive">
          {error}
        </p>
      ) : null}
      <div className="flex justify-end">
        <Button
          type="button"
          size="sm"
          disabled={pending || disabled}
          onClick={onUndo}
        >
          {pending ? (
            <Loader2Icon data-icon="inline-start" className="animate-spin" />
          ) : null}
          되돌리기
        </Button>
      </div>
    </div>
  );
}
