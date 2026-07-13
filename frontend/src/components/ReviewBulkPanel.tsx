"use client";

import {
  useEffect,
  useRef,
  useState,
  type MouseEvent,
} from "react";
import { Loader2Icon, RotateCcwIcon, Trash2Icon } from "lucide-react";

import {
  AlertDialog,
  AlertDialogClose,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export type ReviewBulkAction = "ignore" | "delete" | "reopen";
export type ReviewBulkScope = "selection" | "foreign_filter";

export type ReviewBulkIntent =
  | { action: "ignore"; scope: ReviewBulkScope }
  | { action: "delete"; scope: "selection" }
  | { action: "reopen"; scope: "selection" };

export interface ReviewBulkProgressSummary {
  total: number;
  processed: number;
  succeeded: number;
  conflicts: number;
  failed: number;
  remaining: number;
}

interface ReviewBulkDialogBase {
  intent: ReviewBulkIntent;
}

export type ReviewBulkDialogState =
  | (ReviewBulkDialogBase & {
      phase: "previewing";
    })
  | (ReviewBulkDialogBase & {
      phase: "ready";
      /** 서버 미리보기가 반환한 정확한 처리 대상 건수 */
      exactCount: number;
      /** 상위 컴포넌트가 사용자 시간대로 변환한 확인 토큰 만료 시각 */
      expiresAtLabel?: string | null;
    })
  | (ReviewBulkDialogBase & {
      phase: "running";
      processed: number;
      total: number;
    })
  | (ReviewBulkDialogBase & {
      phase: "succeeded";
      processed: number;
      total: number;
    })
  | (ReviewBulkDialogBase & {
      phase: "partial";
      processed: number;
      total: number;
      conflictCount: number;
      failedCount: number;
      canRetryFailed: boolean;
      message?: string;
    })
  | (ReviewBulkDialogBase & {
      phase: "expired";
      message?: string;
      progress?: ReviewBulkProgressSummary;
    })
  | (ReviewBulkDialogBase & {
      phase: "failed";
      message: string;
      retryable?: boolean;
      retryMode?: "preview" | "execute";
      abandonable?: boolean;
      failureKind?: "retryable" | "fatal" | "contract" | "stale_conflict";
      progress?: ReviewBulkProgressSummary;
      currentChunkOutcomeUnknown?: boolean;
    });

export interface ReviewBulkPanelProps {
  mode: "review" | "removed";
  /** 현재 사용자가 직접 선택한 후보 수이며 필터 전체 건수로 사용하지 않는다. */
  selectedCount: number;
  /** 직접 선택 scope가 허용하는 최대 후보 수. */
  selectionLimit: number;
  /** 다른 검수 mutation 또는 닫힌 백그라운드 일괄 작업이 진행 중일 때 true */
  actionsDisabled?: boolean;
  /** 해외 미리보기 진입만 별도로 막아야 할 때 true */
  foreignActionDisabled?: boolean;
  dialogState: ReviewBulkDialogState | null;
  /** 실행 중 dialog를 닫아도 dialogState는 유지해 진행 상황을 다시 열 수 있게 한다. */
  dialogOpen: boolean;
  className?: string;
  onClearSelection: () => void;
  onRequestPreview: (intent: ReviewBulkIntent) => void;
  onConfirm: () => void;
  onRetry: () => void;
  onAbandon: () => void;
  onDialogOpenChange: (open: boolean) => void;
}

const COUNT_FORMATTER = new Intl.NumberFormat("ko-KR");

function formatCount(count: number): string {
  return COUNT_FORMATTER.format(Math.max(0, count));
}

function actionLabel(action: ReviewBulkAction): string {
  if (action === "ignore") return "제외";
  if (action === "delete") return "삭제";
  return "복구";
}

function intentSubject(intent: ReviewBulkIntent): string {
  return intent.scope === "foreign_filter"
    ? "현재 필터의 해외 판정 후보"
    : "선택한 후보";
}

function dialogTitle(state: ReviewBulkDialogState): string {
  const verb = actionLabel(state.intent.action);
  const subject = intentSubject(state.intent);
  switch (state.phase) {
    case "previewing":
      return `${subject} 대상을 확인하는 중입니다`;
    case "ready":
      return `${subject} ${formatCount(state.exactCount)}건을 ${verb}할까요?`;
    case "running":
      return `${subject} ${verb} 처리 중`;
    case "succeeded":
      return `${subject} ${verb} 완료`;
    case "partial":
      return `${subject} ${verb}가 일부 완료되었습니다`;
    case "expired":
      return "확인 시간이 만료되었습니다";
    case "failed":
      if (state.failureKind === "stale_conflict") {
        return "일괄 처리 진행 상태가 변경되었습니다";
      }
      if (state.failureKind === "contract") {
        return "일괄 처리 결과를 신뢰할 수 없습니다";
      }
      return `${subject} ${verb}에 실패했습니다`;
  }
}

function dialogDescription(state: ReviewBulkDialogState): string {
  const verb = actionLabel(state.intent.action);
  switch (state.phase) {
    case "previewing":
      return "현재 필터 조건을 기준으로 서버에서 정확한 처리 대상 건수를 확인하고 있습니다.";
    case "ready":
      return `서버 미리보기에서 현재 처리 대상이 정확히 ${formatCount(state.exactCount)}건임을 확인했습니다. 확인 후에만 ${verb}를 시작합니다.`;
    case "running":
      return "서버에서 분할 처리하고 있습니다. 이 창을 닫아도 작업은 계속되며, 창 닫기는 작업 취소가 아닙니다.";
    case "succeeded":
      return `확인한 대상의 ${verb} 처리가 끝났습니다.`;
    case "partial":
      return "완료된 항목은 유지됩니다. 처리 실패 항목만 새 미리보기로 다시 확인할 수 있고, 상태 충돌 항목은 자동 재실행하지 않습니다.";
    case "expired":
      if (state.progress) {
        return `${state.message ?? "일괄 처리 확인 시간이 만료되었습니다."} 이미 확인된 처리 결과는 유지되며, 오래된 범위를 자동 재실행하지 않습니다. 목록을 새로고침해 실제 상태를 확인해 주세요.`;
      }
      return (
        state.message ??
        "확인 토큰이 만료되어 작업을 시작하지 않았습니다. 최신 대상 건수를 다시 확인해 주세요."
      );
    case "failed":
      return state.message;
  }
}

function compactStatus(state: ReviewBulkDialogState | null): string | null {
  if (!state) return null;
  const verb = actionLabel(state.intent.action);
  switch (state.phase) {
    case "previewing":
      return "일괄 처리 대상 건수를 확인하는 중입니다.";
    case "ready":
      return `서버 미리보기에서 정확히 ${formatCount(state.exactCount)}건을 확인했습니다.`;
    case "running":
      return `${formatCount(state.processed)} / ${formatCount(state.total)}건 ${verb} 처리 중`;
    case "succeeded":
      return `${formatCount(state.processed)} / ${formatCount(state.total)}건 ${verb} 완료`;
    case "partial":
      return `${formatCount(state.processed)} / ${formatCount(state.total)}건 확인, 충돌 ${formatCount(state.conflictCount)}건 · 실패 ${formatCount(state.failedCount)}건`;
    case "expired":
      return "일괄 처리 확인 시간이 만료되었습니다.";
    case "failed":
      if (state.failureKind === "stale_conflict") {
        return "일괄 처리 진행 상태가 변경되어 목록 확인이 필요합니다.";
      }
      return `일괄 ${verb} 처리에 실패했습니다.`;
  }
}

function retryButtonLabel(state: ReviewBulkDialogState): string | null {
  switch (state.phase) {
    case "expired":
      return state.progress ? null : "최신 대상 다시 확인";
    case "partial":
      return state.failedCount > 0 && state.canRetryFailed
        ? `처리 실패 ${formatCount(state.failedCount)}건 다시 확인`
        : null;
    case "failed":
      if (state.retryable === false) return null;
      return state.retryMode === "preview"
        ? "대상 다시 확인"
        : "같은 묶음 다시 시도";
    default:
      return null;
  }
}

function abandonButtonLabel(state: ReviewBulkDialogState): string | null {
  switch (state.phase) {
    case "expired":
      return state.progress ? "목록 새로고침" : null;
    case "partial":
      if (
        state.conflictCount > 0 &&
        state.failedCount > 0 &&
        !state.canRetryFailed
      ) {
        return "목록 새로고침 · 충돌·실패 후보 나누어 선택";
      }
      if (state.conflictCount > 0) {
        return `목록 새로고침 · 충돌 ${formatCount(state.conflictCount)}건 다시 선택`;
      }
      return state.failedCount > 0 && !state.canRetryFailed
        ? "목록 새로고침 · 실패 후보 나누어 선택"
        : null;
    case "failed":
      if (!state.abandonable) return null;
      return state.retryable
        ? "재시도 중단 · 목록 새로고침"
        : "목록 새로고침";
    default:
      return null;
  }
}

function BulkProgress({
  processed,
  total,
}: {
  processed: number;
  total: number;
}) {
  const safeTotal = Math.max(0, total);
  const safeProcessed = Math.min(Math.max(0, processed), safeTotal);
  const percent = safeTotal === 0 ? 0 : (safeProcessed / safeTotal) * 100;
  return (
    <div className="flex flex-col gap-1.5">
      <div
        role="progressbar"
        aria-label="일괄 검수 처리 진행률"
        aria-valuemin={0}
        aria-valuemax={Math.max(1, safeTotal)}
        aria-valuenow={safeProcessed}
        className="h-2 overflow-hidden rounded-full bg-muted"
      >
        <div
          className="h-full rounded-full bg-primary transition-[width]"
          style={{ width: `${percent}%` }}
        />
      </div>
      <p role="status" aria-live="polite" aria-atomic="true" className="text-xs font-medium">
        {formatCount(safeProcessed)} / {formatCount(safeTotal)}건 처리됨
      </p>
    </div>
  );
}

function BulkProgressSummary({
  progress,
}: {
  progress: ReviewBulkProgressSummary;
}) {
  return (
    <div className="rounded-lg border bg-muted/30 p-3 text-xs">
      <BulkProgress processed={progress.processed} total={progress.total} />
      <p className="mt-2 text-muted-foreground">
        서버 응답으로 확인됨: 성공 {formatCount(progress.succeeded)}건 · 충돌{" "}
        {formatCount(progress.conflicts)}건 · 실패 {formatCount(progress.failed)}건 · 남음{" "}
        {formatCount(progress.remaining)}건
      </p>
    </div>
  );
}

function RecoveryNotice({ intent }: { intent: ReviewBulkIntent }) {
  if (intent.scope === "foreign_filter") {
    return (
      <div
        role="note"
        className="rounded-lg border border-warning/40 bg-warning/5 p-3 text-xs text-warning"
      >
        <p className="font-medium">해외 판정 기준을 확인하세요.</p>
        <p className="mt-1">
          <code>is_domestic=false</code>는 LLM 판정 결과이므로 실제 위치와 다를 수
          있습니다. 제외한 후보는 제외·삭제 목록에서 다시 복구할 수 있습니다.
        </p>
      </div>
    );
  }
  if (intent.action === "reopen") {
    return (
      <p className="rounded-lg bg-muted/60 p-3 text-xs text-muted-foreground">
        복구한 후보는 검수 대기 목록으로 돌아갑니다.
      </p>
    );
  }
  return (
    <p className="rounded-lg bg-muted/60 p-3 text-xs text-muted-foreground">
      {intent.action === "delete" ? "삭제" : "제외"}한 후보는 제외·삭제 목록에서
      다시 복구할 수 있습니다.
    </p>
  );
}

function ProgressPersistenceNotice() {
  return (
    <p role="note" className="rounded-lg border p-3 text-xs text-muted-foreground">
      실행 중에는 이 창만 닫아도 작업은 계속되지만, 페이지를 새로고침하거나 탭을 닫으면
      현재 진행 정보를 잃습니다. 이 경우 최신 대상을 다시 미리보기해 남은 항목을
      확인하세요.
    </p>
  );
}

export function ReviewBulkPanel({
  mode,
  selectedCount,
  selectionLimit,
  actionsDisabled = false,
  foreignActionDisabled = false,
  dialogState,
  dialogOpen,
  className,
  onClearSelection,
  onRequestPreview,
  onConfirm,
  onRetry,
  onAbandon,
  onDialogOpenChange,
}: ReviewBulkPanelProps) {
  const panelRef = useRef<HTMLElement | null>(null);
  const returnFocusRef = useRef<HTMLButtonElement | null>(null);
  const reopenButtonRef = useRef<HTMLButtonElement | null>(null);
  const dialogWasOpenRef = useRef(false);
  const actionGuardRef = useRef<{
    kind: "confirm" | "retry";
    state: ReviewBulkDialogState;
  } | null>(null);
  const [actionGuard, setActionGuard] = useState<{
    kind: "confirm" | "retry";
    state: ReviewBulkDialogState;
  } | null>(null);
  const isDialogVisible = dialogOpen && dialogState != null;

  useEffect(() => {
    if (isDialogVisible) {
      dialogWasOpenRef.current = true;
      return;
    }
    if (!dialogWasOpenRef.current) return;
    dialogWasOpenRef.current = false;
    const reopenButton = reopenButtonRef.current;
    const trigger = returnFocusRef.current;
    if (reopenButton?.isConnected && !reopenButton.disabled) {
      reopenButton.focus();
    } else if (trigger?.isConnected && !trigger.disabled) {
      trigger.focus();
    } else {
      panelRef.current?.focus();
    }
  }, [isDialogVisible]);

  const bulkBusy =
    dialogState?.phase === "previewing" || dialogState?.phase === "running";
  const panelActionsDisabled = actionsDisabled || bulkBusy;
  const selectedActionsDisabled = panelActionsDisabled || selectedCount <= 0;
  const confirmGuarded =
    actionGuard?.state === dialogState && actionGuard?.kind === "confirm";
  const retryGuarded =
    actionGuard?.state === dialogState && actionGuard?.kind === "retry";
  const retryLabel = dialogState ? retryButtonLabel(dialogState) : null;
  const abandonLabel = dialogState ? abandonButtonLabel(dialogState) : null;
  const selectedStatus =
    selectedCount > 0
      ? `현재 후보 ${formatCount(selectedCount)}건 선택됨${
          selectedCount >= selectionLimit ? " · 직접 선택 상한" : ""
        }`
      : null;
  const resultClosedWithNewSelection =
    !dialogOpen &&
    selectedStatus != null &&
    (dialogState?.phase === "succeeded" || dialogState?.phase === "partial");
  const status = resultClosedWithNewSelection
    ? selectedStatus
    : compactStatus(dialogState);

  function rememberTrigger(event: MouseEvent<HTMLButtonElement>) {
    returnFocusRef.current = event.currentTarget;
  }

  function requestPreview(
    event: MouseEvent<HTMLButtonElement>,
    intent: ReviewBulkIntent,
  ) {
    if (panelActionsDisabled) return;
    rememberTrigger(event);
    actionGuardRef.current = null;
    setActionGuard(null);
    onRequestPreview(intent);
  }

  function reopenDialog(event: MouseEvent<HTMLButtonElement>) {
    if (!dialogState) return;
    rememberTrigger(event);
    onDialogOpenChange(true);
  }

  function handleDialogOpenChange(open: boolean) {
    // 실행 중 Escape 같은 암시적 닫기는 막는다. 명시적 버튼만 작업이 계속됨을
    // 알린 뒤 dialog를 닫으며, 일괄 처리 취소 callback은 의도적으로 제공하지 않는다.
    if (!open && dialogState?.phase === "running") return;
    onDialogOpenChange(open);
  }

  function closeRunningDialog() {
    onDialogOpenChange(false);
  }

  function confirmReadyState() {
    if (
      !dialogState ||
      dialogState.phase !== "ready" ||
      dialogState.exactCount <= 0 ||
      (actionGuardRef.current?.kind === "confirm" &&
        actionGuardRef.current.state === dialogState)
    ) {
      return;
    }
    const guard = { kind: "confirm" as const, state: dialogState };
    actionGuardRef.current = guard;
    setActionGuard(guard);
    onConfirm();
  }

  function retryOperation() {
    if (
      !dialogState ||
      (actionGuardRef.current?.kind === "retry" &&
        actionGuardRef.current.state === dialogState)
    ) {
      return;
    }
    const guard = { kind: "retry" as const, state: dialogState };
    actionGuardRef.current = guard;
    setActionGuard(guard);
    onRetry();
  }

  return (
    <>
      <section
        ref={panelRef}
        tabIndex={-1}
        aria-label="일괄 검수 도구"
        aria-busy={bulkBusy}
        className={cn(
          "rounded-lg outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2",
          className,
        )}
      >
        <div className="sticky bottom-0 z-30 flex flex-col gap-2 border-y bg-background/95 px-2 pt-2 pb-[calc(0.5rem+env(safe-area-inset-bottom))] shadow-lg backdrop-blur lg:static lg:rounded-lg lg:border lg:p-2 lg:shadow-none">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p role="status" aria-live="polite" aria-atomic="true" className="text-xs font-medium">
              {status ??
                selectedStatus ??
                "후보를 선택하면 일괄 처리할 수 있습니다."}
            </p>
            {dialogState && !dialogOpen ? (
              <Button
                ref={reopenButtonRef}
                type="button"
                size="xs"
                variant="outline"
                onClick={reopenDialog}
              >
                {dialogState.phase === "running"
                  ? "진행 상황 보기"
                  : dialogState.phase === "ready"
                    ? "확인 계속"
                    : "일괄 처리 결과 보기"}
              </Button>
            ) : null}
          </div>

          <div className="grid grid-cols-2 gap-2 sm:flex sm:flex-wrap sm:items-center">
            {mode === "review" ? (
              <>
                <Button
                  type="button"
                  size="xs"
                  variant="destructive"
                  disabled={selectedActionsDisabled}
                  onClick={(event) =>
                    requestPreview(event, {
                      action: "ignore",
                      scope: "selection",
                    })
                  }
                >
                  선택 제외
                </Button>
                <Button
                  type="button"
                  size="xs"
                  variant="destructive"
                  disabled={selectedActionsDisabled}
                  onClick={(event) =>
                    requestPreview(event, {
                      action: "delete",
                      scope: "selection",
                    })
                  }
                >
                  <Trash2Icon data-icon="inline-start" />
                  선택 삭제
                </Button>
              </>
            ) : (
              <Button
                type="button"
                size="xs"
                variant="outline"
                disabled={selectedActionsDisabled}
                onClick={(event) =>
                  requestPreview(event, {
                    action: "reopen",
                    scope: "selection",
                  })
                }
              >
                <RotateCcwIcon data-icon="inline-start" />
                선택 복구
              </Button>
            )}

            <Button
              type="button"
              size="xs"
              variant="ghost"
              disabled={selectedCount <= 0 || panelActionsDisabled}
              onClick={onClearSelection}
            >
              선택 해제
            </Button>

            {mode === "review" ? (
              <Button
                type="button"
                size="xs"
                variant="outline"
                className="col-span-2 sm:ml-auto"
                disabled={panelActionsDisabled || foreignActionDisabled}
                onClick={(event) =>
                  requestPreview(event, {
                    action: "ignore",
                    scope: "foreign_filter",
                  })
                }
              >
                현재 필터의 해외 판정 후보 모두 제외
              </Button>
            ) : null}
          </div>
        </div>
      </section>

      <AlertDialog
        open={isDialogVisible}
        onOpenChange={handleDialogOpenChange}
      >
        {dialogState ? (
          <AlertDialogContent
            data-phase={dialogState.phase}
            aria-busy={bulkBusy}
            className="max-w-lg"
          >
            <AlertDialogHeader>
              <AlertDialogTitle>{dialogTitle(dialogState)}</AlertDialogTitle>
              <AlertDialogDescription>
                {dialogDescription(dialogState)}
              </AlertDialogDescription>
            </AlertDialogHeader>

            {dialogState.phase === "previewing" ? (
              <div role="status" aria-live="polite" className="flex items-center gap-2 text-sm">
                <Loader2Icon className="animate-spin" />
                정확한 대상 건수를 확인하는 중…
              </div>
            ) : null}

            {dialogState.phase === "ready" && dialogState.expiresAtLabel ? (
              <p className="rounded-lg border px-3 py-2 text-xs text-muted-foreground">
                확인 유효 시간: {dialogState.expiresAtLabel}
              </p>
            ) : null}

            {dialogState.phase === "running" ||
            dialogState.phase === "succeeded" ||
            dialogState.phase === "partial" ? (
              <BulkProgress
                processed={dialogState.processed}
                total={dialogState.total}
              />
            ) : null}

            {dialogState.phase === "partial" ? (
              <p role="alert" className="rounded-lg border border-warning/40 bg-warning/5 p-3 text-xs text-warning">
                {dialogState.message ??
                  `상태 충돌 ${formatCount(dialogState.conflictCount)}건은 목록에서 직접 다시 선택해야 하며, 처리 실패 ${formatCount(dialogState.failedCount)}건만 다시 확인할 수 있습니다.`}
              </p>
            ) : null}

            {(dialogState.phase === "expired" ||
              dialogState.phase === "failed") &&
            dialogState.progress ? (
              <BulkProgressSummary progress={dialogState.progress} />
            ) : null}

            {dialogState.phase === "failed" &&
            dialogState.currentChunkOutcomeUnknown ? (
              <p role="alert" className="rounded-lg border border-warning/40 bg-warning/5 p-3 text-xs text-warning">
                {dialogState.retryable
                  ? "현재 묶음은 응답이 끊겨 반영 여부를 알 수 없습니다. 새 request로 넘기지 말고 같은 묶음을 다시 요청해 저장된 처리 결과를 확인해야 합니다."
                  : "현재 묶음의 응답 계약을 신뢰할 수 없어 반영 여부를 알 수 없습니다. 확인 token은 폐기했으므로 목록을 새로고침해 실제 상태를 확인해야 합니다."}
              </p>
            ) : null}

            {dialogState.phase === "expired" ||
            dialogState.phase === "failed" ? (
              <p role="alert" className="sr-only">
                {dialogDescription(dialogState)}
              </p>
            ) : null}

            <RecoveryNotice intent={dialogState.intent} />
            <ProgressPersistenceNotice />

            <AlertDialogFooter>
              {dialogState.phase === "running" ? (
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  autoFocus
                  onClick={closeRunningDialog}
                >
                  창 닫기 · 작업은 계속됨
                </Button>
              ) : (
                <AlertDialogClose
                  render={
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      autoFocus
                    >
                      {dialogState.phase === "ready" ? "취소" : "닫기"}
                    </Button>
                  }
                />
              )}

              {dialogState.phase === "ready" &&
              dialogState.exactCount > 0 ? (
                <Button
                  type="button"
                  size="sm"
                  variant={
                    dialogState.intent.action === "reopen"
                      ? "default"
                      : "destructive"
                  }
                  disabled={confirmGuarded}
                  onClick={confirmReadyState}
                >
                  {confirmGuarded ? (
                    <Loader2Icon data-icon="inline-start" className="animate-spin" />
                  ) : null}
                  {formatCount(dialogState.exactCount)}건 {actionLabel(dialogState.intent.action)} 시작
                </Button>
              ) : null}

              {retryLabel ? (
                <Button
                  type="button"
                  size="sm"
                  disabled={retryGuarded}
                  onClick={retryOperation}
                >
                  {retryGuarded ? (
                    <Loader2Icon data-icon="inline-start" className="animate-spin" />
                  ) : null}
                  {retryLabel}
                </Button>
              ) : null}

              {abandonLabel ? (
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  onClick={onAbandon}
                >
                  {abandonLabel}
                </Button>
              ) : null}
            </AlertDialogFooter>
          </AlertDialogContent>
        ) : null}
      </AlertDialog>
    </>
  );
}
