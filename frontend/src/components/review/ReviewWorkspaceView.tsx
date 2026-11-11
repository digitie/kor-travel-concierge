"use client";

import { triageProgressPanelProps,
  reviewCandidateDeleteDialogProps,
  reviewCandidateDetailDialogProps,
  reviewCandidateEditorProps,
  reviewCandidateMapProps,
  reviewQueueSidebarProps,
  reviewShortcutDialogProps } from "./review-view-props";

import { AppShell } from "@/components/AppShell";
import { ReviewUndoSnackbar } from "@/components/ReviewUndoSnackbar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { dismissReviewUndo } from "@/lib/review-undo";
import { KeyboardIcon, RefreshCwIcon, RotateCcwIcon } from "lucide-react";

import { type ReviewWorkspaceModel } from "./review-view-props";
import { ReviewCandidateEditor } from "./ReviewCandidateEditor";
import { ReviewCandidateMap } from "./ReviewCandidateMap";
import { ReviewQueueSidebar } from "./ReviewQueueSidebar";
import {
  ReviewCandidateDeleteDialog,
  ReviewCandidateDetailDialog,
  ReviewShortcutDialog,
} from "./ReviewWorkspaceDialogs";

export function ReviewWorkspaceView(model: ReviewWorkspaceModel) {
  const {
    setShortcutHelpOpen,
    candidates,
    candidateTotal,
    isTriage,
    candidateActionPending,
    reviewUndoStateRef,
    requestCandidateReopen,
    reviewUndoError,
    reopenMutation,
    updateReviewUndoState,
    setReviewUndoError,
    reviewUndoState,
    reviewMode,
    setReviewMode,
  } = model;
  const modeToggle = (
    <div
      role="group"
      aria-label="검수 화면 모드"
      className="inline-flex overflow-hidden rounded-control border border-border"
    >
      {(["triage", "table"] as const).map((mode) => (
        <button
          key={mode}
          type="button"
          aria-pressed={reviewMode === mode}
          onClick={() => setReviewMode(mode)}
          className="h-control-sm px-2.5 text-xs font-medium transition-[color,background-color] duration-fast aria-pressed:bg-brand aria-pressed:text-brand-foreground"
        >
          {mode === "triage" ? "처리 모드" : "목록/관리"}
        </button>
      ))}
    </div>
  );
  return (
    <AppShell
      title="검수 큐"
      actions={
        <div className="flex items-center gap-2">
          {modeToggle}
          <Button
            type="button"
            size="icon-xs"
            variant="ghost"
            aria-label="검수 단축키 도움말"
            title="단축키 도움말 (?)"
            onClick={() => setShortcutHelpOpen(true)}
          >
            <KeyboardIcon />
          </Button>
          <Badge variant="secondary">
            {candidates.length}/{candidateTotal}개 불러옴
          </Badge>
        </div>
      }
      contentClassName="flex min-h-0 flex-1 flex-col p-0"
      viewportLocked
    >
      <div
        className={
          isTriage
            ? "grid h-full min-h-0 flex-1 grid-cols-1 bg-surface-page lg:grid-cols-[15rem_minmax(0,1fr)_minmax(0,0.82fr)] lg:overflow-hidden"
            : "grid h-full min-h-0 flex-1 grid-cols-1 bg-surface-page lg:grid-cols-[20rem_minmax(0,1fr)_minmax(19rem,0.82fr)] lg:overflow-hidden"
        }
      >
        {isTriage ? (
          <TriageProgressPanel {...triageProgressPanelProps(model)} />
        ) : (
          <ReviewQueueSidebar {...reviewQueueSidebarProps(model)} />
        )}

        <ReviewCandidateEditor {...reviewCandidateEditorProps(model)} />
        <ReviewCandidateMap {...reviewCandidateMapProps(model)} />
      </div>

      <ReviewCandidateDetailDialog
        {...reviewCandidateDetailDialogProps(model)}
      />

      {/* 행 삭제 확인 — 페이지 공용 단일 다이얼로그 */}
      <ReviewCandidateDeleteDialog
        {...reviewCandidateDeleteDialogProps(model)}
      />

      {reviewUndoState.current ? (
        <ReviewUndoSnackbar
          candidateName={reviewUndoState.current.candidateName}
          actionLabel={
            reviewUndoState.current.action === "create_place" ||
            reviewUndoState.current.action === "match_existing"
              ? "저장"
              : reviewUndoState.current.action === "ignore"
                ? "제외"
                : "삭제"
          }
          pending={
            reopenMutation.isPending &&
            reopenMutation.variables?.source === "snackbar" &&
            reopenMutation.variables.descriptor.token ===
              reviewUndoState.current.descriptor.token
          }
          disabled={candidateActionPending}
          error={reviewUndoError}
          onUndo={() => {
            const entry = reviewUndoStateRef.current.current;
            if (!entry) return;
            requestCandidateReopen(
              {
                id: entry.descriptor.candidate_id,
                ai_place_name: entry.candidateName,
                review_state: entry.expectedReviewState,
                undo: entry.descriptor,
              },
              "snackbar",
            );
          }}
          onDismiss={() => {
            updateReviewUndoState(dismissReviewUndo);
            setReviewUndoError(null);
          }}
        />
      ) : null}

      <ReviewShortcutDialog {...reviewShortcutDialogProps(model)} />
    </AppShell>
  );
}

function TriageProgressPanel({
  candidatesQuery,
  restartCandidateSnapshot,
  facetsQuery,
  triagePosition,
  candidateTotal,
  queueCompleted,
  triageRemaining,
  lastProcessed,
  candidateActionPending,
  reviewUndoStateRef,
  requestCandidateReopen,
  reviewUndoError,
}: ReturnType<typeof triageProgressPanelProps>) {
  return (
    <aside className="flex min-h-0 max-h-[40vh] flex-col gap-3 overflow-y-auto border-b border-border bg-card p-4 lg:h-full lg:max-h-none lg:border-r lg:border-b-0">
      <div className="flex items-center justify-between gap-2">
        <p className="px-1 text-xs font-medium text-muted-foreground">
          처리 진행
        </p>
        <Button
          type="button"
          size="icon-xs"
          variant="ghost"
          aria-label="검수 후보 수동 새로고침"
          title="현재 조건을 첫 페이지부터 새로고침"
          disabled={candidatesQuery.isFetching}
          onClick={() => {
            void restartCandidateSnapshot();
            void facetsQuery.refetch();
          }}
        >
          <RefreshCwIcon
            className={candidatesQuery.isFetching ? "animate-spin" : undefined}
          />
        </Button>
      </div>
      <div className="rounded-control border border-border bg-surface-subtle p-3">
        <p className="text-2xl font-semibold tabular-nums">
          {triagePosition > 0 ? triagePosition : "–"}
          <span className="text-sm font-normal text-muted-foreground">
            {" "}
            / {candidateTotal}
          </span>
        </p>
        <p className="mt-1 text-xs text-muted-foreground">
          {queueCompleted
            ? "현재 조건을 모두 처리했습니다."
            : `남은 후보 약 ${triageRemaining}건`}
        </p>
      </div>
      {lastProcessed ? (
        <div className="flex flex-col gap-2 rounded-control border border-brand bg-brand-tint p-3">
          <p className="text-xs font-medium">최근 처리</p>
          <p className="truncate text-sm" title={lastProcessed.candidateName}>
            {lastProcessed.candidateName}
          </p>
          <p className="text-xs text-muted-foreground">
            {lastProcessed.action === "create_place" ||
            lastProcessed.action === "match_existing"
              ? "저장됨"
              : lastProcessed.action === "ignore"
                ? "제외됨"
                : "삭제됨"}
          </p>
          <Button
            type="button"
            size="xs"
            variant="outline"
            disabled={candidateActionPending}
            onClick={() => {
              const entry = reviewUndoStateRef.current.current;
              if (!entry) return;
              requestCandidateReopen(
                {
                  id: entry.descriptor.candidate_id,
                  ai_place_name: entry.candidateName,
                  review_state: entry.expectedReviewState,
                  undo: entry.descriptor,
                },
                "snackbar",
              );
            }}
          >
            <RotateCcwIcon data-icon="inline-start" />
            되돌리기 (U)
          </Button>
          {reviewUndoError ? (
            <p role="alert" className="text-xs text-destructive">
              {reviewUndoError}
            </p>
          ) : null}
        </div>
      ) : (
        <p className="rounded-control border border-border bg-surface-subtle p-3 text-xs text-text-secondary">
          처리한 후보가 여기에 표시되고 U로 되돌릴 수 있습니다.
        </p>
      )}
      <p className="mt-auto rounded-control border border-border p-2 text-2xs leading-relaxed text-text-secondary">
        J/K 다음·이전 · 1–9 검색결과 · Enter 저장 · X 제외 · U 되돌리기 · / 검색
        · ? 도움말. 필터·일괄 처리는 &ldquo;목록/관리&rdquo; 모드에서.
      </p>
    </aside>
  );
}
