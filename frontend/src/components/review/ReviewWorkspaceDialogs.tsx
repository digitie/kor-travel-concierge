"use client";

import {
  reviewCandidateDeleteDialogProps,
  reviewCandidateDetailDialogProps,
  reviewShortcutDialogProps,
} from "./review-view-props";

import { CandidateDetailView } from "@/components/CandidateDetailView";
import { REVIEW_SHORTCUTS } from "@/components/review/useReviewKeyboard";
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { reconcileProcessedCandidateCaches } from "@/lib/review-candidate-cache";
import {
  applyReviewActionSuccess,
  reconcileReviewUndoAfterActionFailure,
} from "@/lib/review-undo";

import { candidateFailureShouldAdvance } from "./review-workspace-model";

export function ReviewCandidateDetailDialog({
  detailId,
  detailDeletePending,
  setDetailId,
  candidateActionPending,
  reopenMutation,
  requestCandidateReopen,
  setDetailDeletePending,
  detailDeleteSnapshotRef,
  candidates,
  candidatePages,
  queueScope,
  selectionScopeEpochRef,
  candidatesKey,
  reviewUndoStateRef,
  detailCandidate,
  updateReviewUndoState,
  setCandidateActionError,
  setReviewUndoError,
  reviewListStateRef,
  removeCandidateSelections,
  reconcileFailedCandidateSelection,
  candidatesKeyRef,
  queueScopeRef,
  markCandidateCacheRefreshError,
  queryClient,
  selectedCandidateIdRef,
  advanceAfterProcessing,
  clearProcessedCandidateParam,
  initialSelectionDoneRef,
  setQueueCompleted,
  setSelectedCandidateSnapshot,
  setSelectedId,
}: ReturnType<typeof reviewCandidateDetailDialogProps>) {
  return (
    <Dialog
      open={detailId != null}
      onOpenChange={(open) => {
        if (!open && !detailDeletePending) setDetailId(null);
      }}
    >
      <DialogContent className="max-h-[85vh] max-w-2xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>검수 후보 상세</DialogTitle>
        </DialogHeader>
        {detailId != null ? (
          <CandidateDetailView
            candidateId={detailId}
            cacheHandledByOnDeleted
            actionsDisabled={candidateActionPending || detailDeletePending}
            restorePending={
              reopenMutation.isPending &&
              reopenMutation.variables?.descriptor.candidate_id === detailId
            }
            onRestoreRequested={(candidate) =>
              requestCandidateReopen(candidate, "detail")
            }
            onDeleteStarted={(candidateId) => {
              setDetailDeletePending(true);
              detailDeleteSnapshotRef.current = {
                candidateId,
                visibleIndex: candidates.findIndex(
                  (candidate) => candidate.id === candidateId,
                ),
                orderedCandidateIds: candidates.map(
                  (candidate) => candidate.id,
                ),
                loadedPageCount: candidatePages.length,
                queueScope,
                workflowEpoch: selectionScopeEpochRef.current,
                candidatesKey,
              };
            }}
            onDeleteFailureRevalidated={(
              candidateId,
              detailRevalidation,
              requestStatus,
              requestAttempted,
              clientOperationId,
            ) => {
              const snapshot = detailDeleteSnapshotRef.current;
              if (!snapshot || snapshot.candidateId !== candidateId) return;
              const undoReconciliation = reconcileReviewUndoAfterActionFailure(
                reviewUndoStateRef.current,
                {
                  authoritative: detailRevalidation,
                  requestAttempted,
                  requestStatus,
                  clientOperationId,
                  candidateId,
                  candidateName:
                    detailCandidate?.ai_place_name ?? `후보 #${candidateId}`,
                  action: "delete",
                  expectedReviewState: "deleted",
                },
              );
              updateReviewUndoState(() => undoReconciliation.state);
              if (undoReconciliation.outcome === "confirmed_committed") {
                setCandidateActionError(
                  `${detailCandidate?.ai_place_name ?? `후보 #${candidateId}`} 후보의 응답은 끊겼지만 최신 상태에서 삭제 완료를 확인했습니다.`,
                );
              } else if (undoReconciliation.outcome === "foreign_or_stale") {
                setCandidateActionError(
                  `${detailCandidate?.ai_place_name ?? `후보 #${candidateId}`} 후보는 다른 작업으로 상태가 바뀌어 최신 상태를 반영했습니다.`,
                );
              }
              if (
                detailRevalidation?.status !== "success" ||
                detailRevalidation.detail.list_item.review_state !==
                  "needs_review"
              ) {
                setReviewUndoError(null);
              }
              if (
                candidateFailureShouldAdvance(
                  detailRevalidation,
                  reviewListStateRef.current,
                )
              ) {
                removeCandidateSelections([candidateId]);
              }
              const advanced = reconcileFailedCandidateSelection(
                candidateId,
                {
                  visibleIndex: snapshot.visibleIndex,
                  orderedCandidateIds: snapshot.orderedCandidateIds,
                  loadedPageCount: snapshot.loadedPageCount,
                  queueScope: snapshot.queueScope,
                  workflowEpoch: snapshot.workflowEpoch,
                  activePageKey: candidatesKeyRef.current,
                },
                detailRevalidation,
              );
              if (advanced) setDetailId(null);
            }}
            onDeleteSettled={() => {
              setDetailDeletePending(false);
              detailDeleteSnapshotRef.current = null;
            }}
            onCacheRefreshFailed={() => {
              if (
                detailDeleteSnapshotRef.current?.queueScope ===
                queueScopeRef.current
              ) {
                markCandidateCacheRefreshError();
              }
            }}
            onDeleted={async (result) => {
              const deletedId = result.id;
              const snapshot = detailDeleteSnapshotRef.current;
              const deletedCandidateName =
                detailCandidate?.ai_place_name ?? `후보 #${deletedId}`;
              const activeCandidatesKey = candidatesKeyRef.current;
              const activeQueueScope = queueScopeRef.current;
              const cacheResult = await reconcileProcessedCandidateCaches(
                queryClient,
                {
                  ids: [deletedId],
                  capturedPageKey: snapshot?.candidatesKey,
                  activePageKey: activeCandidatesKey,
                  pageOut: snapshot != null && snapshot.visibleIndex < 0,
                },
              );
              if (
                cacheResult.postCommitRefreshFailed &&
                activeQueueScope === queueScopeRef.current
              ) {
                markCandidateCacheRefreshError();
              }
              setDetailId((current) =>
                current === deletedId ? null : current,
              );
              if (
                deletedId === selectedCandidateIdRef.current &&
                snapshot?.candidateId === deletedId &&
                snapshot.visibleIndex >= 0 &&
                snapshot.queueScope === queueScopeRef.current &&
                snapshot.workflowEpoch === selectionScopeEpochRef.current
              ) {
                advanceAfterProcessing(
                  deletedId,
                  [deletedId],
                  snapshot.visibleIndex,
                  snapshot.orderedCandidateIds,
                  snapshot.loadedPageCount,
                );
              } else {
                removeCandidateSelections([deletedId]);
                clearProcessedCandidateParam(deletedId, false);
                if (deletedId === selectedCandidateIdRef.current) {
                  initialSelectionDoneRef.current = false;
                  selectedCandidateIdRef.current = null;
                  setQueueCompleted(false);
                  setSelectedCandidateSnapshot(null);
                  setSelectedId(null);
                }
              }
              // active cache/selection 정리가 끝난 뒤에만 undo를 노출한다. 먼저
              // 노출하면 즉시 reopen과 늦은 delete reconcile이 후보를 다시 지운다.
              updateReviewUndoState((current) =>
                applyReviewActionSuccess(current, {
                  candidateId: deletedId,
                  candidateName: deletedCandidateName,
                  action: "delete",
                  reviewState: "deleted",
                  undo: result.undo,
                }),
              );
              setReviewUndoError(null);
            }}
          />
        ) : null}
      </DialogContent>
    </Dialog>
  );
}

export function ReviewCandidateDeleteDialog({
  deleteTarget,
  deleteTargetScopeRef,
  setDeleteTarget,
  candidateActionPending,
  deleteTargetActionable,
  queueScopeRef,
  deleteCandidatesMutation,
  setCandidateActionError,
}: ReturnType<typeof reviewCandidateDeleteDialogProps>) {
  return (
    <AlertDialog
      open={deleteTarget != null}
      onOpenChange={(open) => {
        if (!open) {
          deleteTargetScopeRef.current = null;
          setDeleteTarget(null);
        }
      }}
    >
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>
            {deleteTarget?.ai_place_name} 후보를 삭제할까요?
          </AlertDialogTitle>
          <AlertDialogDescription>
            삭제 후 제외·삭제 목록에서 이 후보를 복구할 수 있습니다.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel asChild>
            <Button type="button" variant="outline" size="sm">
              취소
            </Button>
          </AlertDialogCancel>
          <Button
            type="button"
            size="sm"
            variant="destructive"
            disabled={candidateActionPending || !deleteTargetActionable}
            onClick={() => {
              if (
                deleteTarget &&
                deleteTargetActionable &&
                deleteTargetScopeRef.current === queueScopeRef.current
              ) {
                deleteCandidatesMutation.mutate([deleteTarget]);
              } else if (deleteTarget) {
                setCandidateActionError(
                  `${deleteTarget.ai_place_name} 후보는 표시 조건이 바뀌어 삭제하지 않았습니다. 현재 목록에서 다시 선택해 주세요.`,
                );
              }
              deleteTargetScopeRef.current = null;
              setDeleteTarget(null);
            }}
          >
            삭제
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

export function ReviewShortcutDialog({
  shortcutHelpOpen,
  setShortcutHelpOpen,
}: ReturnType<typeof reviewShortcutDialogProps>) {
  return (
    <Dialog open={shortcutHelpOpen} onOpenChange={setShortcutHelpOpen}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle>검수 단축키</DialogTitle>
        </DialogHeader>
        <ul className="flex flex-col gap-1.5 text-sm">
          {REVIEW_SHORTCUTS.map((shortcut) => (
            <li
              key={shortcut.keys}
              className="flex items-center justify-between gap-3"
            >
              <span className="text-muted-foreground">{shortcut.label}</span>
              <kbd className="rounded border bg-muted px-1.5 py-0.5 font-mono text-xs">
                {shortcut.keys}
              </kbd>
            </li>
          ))}
        </ul>
        <p className="text-xs text-muted-foreground">
          입력창·버튼·대화상자에 포커스가 있거나 한글 조합 중에는 단축키가
          동작하지 않습니다.
        </p>
      </DialogContent>
    </Dialog>
  );
}
