"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ExternalLinkIcon,
  Loader2Icon,
  RotateCcwIcon,
  Trash2Icon,
} from "lucide-react";

import {
  ApiRequestError,
  deleteCandidate,
  getCandidateDetail,
  getCandidateTranscript,
  type DeleteCandidateResult,
  type UnmatchedCandidate,
} from "@/lib/api";
import {
  reconcileProcessedCandidateCaches,
  revalidateCandidateActionFailure,
  type CandidateDetailRevalidation,
} from "@/lib/review-candidate-cache";
import { categoryDisplayLabel } from "@/lib/display-labels";
import { timestampedVideoUrl } from "@/lib/format";
import {
  approximateTranscriptEvidenceScrollTop,
  cleanTranscript,
} from "@/lib/transcript";
import {
  confirmCandidateDeleteDetail,
  deleteResponseMatchesConfirmedDetail,
  waitForCandidateOperationMarker,
} from "@/lib/review-undo";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { DetailRow, DetailSection } from "@/components/detail";

function durationLabel(seconds: number | null): string {
  if (seconds == null) return "";
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return m > 0 ? `${m}분 ${s}초` : `${s}초`;
}
function dateLabel(value: string | null): string {
  return value ? value.slice(0, 10) : "";
}

function reviewStateLabel(state: UnmatchedCandidate["review_state"]): string {
  if (state === "ignored") return "제외됨";
  if (state === "deleted") return "삭제됨";
  if (state === "matched") return "자동 확정";
  if (state === "user_corrected") return "검수 확정";
  return "검수 대기";
}

class CandidateDeleteAttemptError extends Error {
  readonly requestAttempted: boolean;
  readonly requestStatus: number | null;
  readonly clientOperationId: string | null;
  readonly expectedRevision: number | null;
  readonly responseReceived: boolean;
  readonly response: DeleteCandidateResult | null;

  constructor(
    cause: unknown,
    requestAttempted: boolean,
    clientOperationId: string | null = null,
    expectedRevision: number | null = null,
    responseReceived = false,
    response: DeleteCandidateResult | null = null,
  ) {
    super(cause instanceof Error ? cause.message : "후보 삭제 요청에 실패했습니다.");
    this.name = "CandidateDeleteAttemptError";
    this.requestAttempted = requestAttempted;
    this.requestStatus =
      !responseReceived && cause instanceof ApiRequestError ? cause.status : null;
    this.clientOperationId = clientOperationId;
    this.expectedRevision = expectedRevision;
    this.responseReceived = responseReceived;
    this.response = response;
  }
}

function siblingHref(sibling: {
  id: number;
  review_state: UnmatchedCandidate["review_state"];
  place_id: number | null;
}) {
  if (
    sibling.place_id != null &&
    (sibling.review_state === "matched" ||
      sibling.review_state === "user_corrected")
  ) {
    return `/?place=${sibling.place_id}`;
  }
  return `/review?candidate=${sibling.id}`;
}

export function CandidateDetailView({
  candidateId,
  onDeleted,
  onRestoreRequested,
  onDeleteStarted,
  onDeleteFailureRevalidated,
  onDeleteSettled,
  onCacheRefreshFailed,
  cacheHandledByOnDeleted = false,
  actionsDisabled = false,
  restorePending = false,
}: {
  candidateId: number;
  onDeleted?: (result: DeleteCandidateResult) => void | Promise<void>;
  onRestoreRequested?: (candidate: UnmatchedCandidate) => void;
  onDeleteStarted?: (candidateId: number) => void;
  onDeleteFailureRevalidated?: (
    candidateId: number,
    detailRevalidation: CandidateDetailRevalidation | undefined,
    requestStatus: number | null,
    requestAttempted: boolean,
    clientOperationId: string | null,
  ) => void | Promise<void>;
  onDeleteSettled?: () => void;
  onCacheRefreshFailed?: () => void;
  cacheHandledByOnDeleted?: boolean;
  actionsDisabled?: boolean;
  restorePending?: boolean;
}) {
  const queryClient = useQueryClient();
  const detailQuery = useQuery({
    queryKey: ["candidate-detail", candidateId],
    queryFn: () => getCandidateDetail(candidateId),
  });
  // 보정 자막은 상세가 열릴 때 함께(지연) 불러온다(RustFS에서 텍스트 로드).
  const transcriptQuery = useQuery({
    queryKey: ["candidate-transcript", candidateId],
    queryFn: () => getCandidateTranscript(candidateId),
  });
  const detail = detailQuery.data;
  const [confirmDeleteCandidateId, setConfirmDeleteCandidateId] = useState<
    number | null
  >(null);
  const [cacheRefreshError, setCacheRefreshError] = useState<{
    candidateId: number;
    message: string;
  } | null>(null);
  const confirmDelete = confirmDeleteCandidateId === candidateId;
  const [transcriptTab, setTranscriptTab] = useState("raw");
  const transcriptRef = useRef<HTMLPreElement>(null);
  const transcriptText = transcriptQuery.data?.text ?? "";
  const evidenceStart = detail?.candidate.timestamp_start ?? null;
  const scrollTranscriptToEvidence = useCallback(() => {
    const element = transcriptRef.current;
    if (!element || !transcriptText) return;
    element.scrollTop = approximateTranscriptEvidenceScrollTop(
      transcriptText,
      evidenceStart,
      element.scrollHeight,
    );
  }, [evidenceStart, transcriptText]);
  const deleteMutation = useMutation({
    mutationFn: async (targetCandidateId: number) => {
      let latest: Awaited<ReturnType<typeof getCandidateDetail>>;
      try {
        latest = await getCandidateDetail(targetCandidateId);
      } catch (error) {
        throw new CandidateDeleteAttemptError(error, false);
      }
      queryClient.setQueryData(["candidate-detail", targetCandidateId], latest);
      if (latest.candidate.review_state !== "needs_review") {
        throw new CandidateDeleteAttemptError(
          new Error("검수 대기 상태의 후보만 삭제할 수 있습니다."),
          false,
        );
      }
      const clientOperationId = crypto.randomUUID();
      let responseReceived = false;
      let response: DeleteCandidateResult | null = null;
      try {
        response = await deleteCandidate(
          targetCandidateId,
          latest.candidate.state_revision,
          clientOperationId,
        );
        responseReceived = true;
        const firstDetail = await getCandidateDetail(targetCandidateId);
        const authoritative = await waitForCandidateOperationMarker({
          initial: { status: "success", detail: firstDetail },
          candidateId: targetCandidateId,
          expectedReviewState: "deleted",
          fetchCandidateDetail: getCandidateDetail,
        });
        if (authoritative?.status !== "success") {
          throw new Error("삭제 뒤 최신 후보 상세를 확인하지 못했습니다.");
        }
        const confirmed = confirmCandidateDeleteDetail({
          detail: authoritative.detail,
          candidateId: targetCandidateId,
          expectedRevision: latest.candidate.state_revision,
          clientOperationId,
        });
        if (
          !confirmed ||
          !deleteResponseMatchesConfirmedDetail({
            response,
            confirmed,
            candidateId: targetCandidateId,
            clientOperationId,
          })
        ) {
          throw new Error("삭제 응답이 요청 후보의 완료 상태와 일치하지 않습니다.");
        }
        queryClient.setQueryData(
          ["candidate-detail", targetCandidateId],
          authoritative.detail,
        );
        return response;
      } catch (error) {
        throw new CandidateDeleteAttemptError(
          error,
          true,
          clientOperationId,
          latest.candidate.state_revision,
          responseReceived,
          response,
        );
      }
    },
    onMutate: (targetCandidateId) => {
      setCacheRefreshError(null);
      onDeleteStarted?.(targetCandidateId);
    },
    onSuccess: async (result) => {
      const deletedCandidateId = result.id;
      if (!cacheHandledByOnDeleted) {
        const cacheResult = await reconcileProcessedCandidateCaches(queryClient, {
          ids: [deletedCandidateId],
        });
        if (cacheResult.postCommitRefreshFailed) {
          setCacheRefreshError({
            candidateId: deletedCandidateId,
            message: "후보는 삭제됐지만 최신 검수 목록을 다시 확인하지 못했습니다.",
          });
          onCacheRefreshFailed?.();
        }
      }
      await onDeleted?.(result);
      queryClient.removeQueries({
        queryKey: ["candidate-detail", deletedCandidateId],
      });
      queryClient.removeQueries({
        queryKey: ["candidate-transcript", deletedCandidateId],
      });
    },
    onError: async (error, targetCandidateId) => {
      const failureRefresh = await revalidateCandidateActionFailure(queryClient, {
        candidateIds: [targetCandidateId],
        fetchCandidateDetail: getCandidateDetail,
      });
      if (failureRefresh.refreshFailed) {
        setCacheRefreshError({
          candidateId: targetCandidateId,
          message:
            "삭제 결과를 확인하지 못했고 최신 검수 목록과 상세도 다시 확인하지 못했습니다.",
        });
        onCacheRefreshFailed?.();
      }
      const requestAttempted =
        error instanceof CandidateDeleteAttemptError && error.requestAttempted;
      const requestStatus =
        error instanceof CandidateDeleteAttemptError
          ? error.requestStatus
          : error instanceof ApiRequestError
            ? error.status
            : null;
      const initialAuthoritative = failureRefresh.candidateDetails.get(
        targetCandidateId,
      );
      const authoritative =
        requestAttempted && (requestStatus == null || requestStatus >= 500)
          ? await waitForCandidateOperationMarker({
              initial: initialAuthoritative,
              candidateId: targetCandidateId,
              expectedReviewState: "deleted",
              fetchCandidateDetail: getCandidateDetail,
            })
          : initialAuthoritative;
      if (authoritative?.status === "success") {
        queryClient.setQueryData(
          ["candidate-detail", targetCandidateId],
          authoritative.detail,
        );
      }
      const clientOperationId =
        error instanceof CandidateDeleteAttemptError
          ? error.clientOperationId
          : null;
      const expectedRevision =
        error instanceof CandidateDeleteAttemptError
          ? error.expectedRevision
          : null;
      const responseReceived =
        error instanceof CandidateDeleteAttemptError && error.responseReceived;
      const response =
        error instanceof CandidateDeleteAttemptError ? error.response : null;
      const confirmed =
        authoritative?.status === "success" &&
        clientOperationId != null &&
        expectedRevision != null
          ? confirmCandidateDeleteDetail({
              detail: authoritative.detail,
              candidateId: targetCandidateId,
              expectedRevision,
              clientOperationId,
            })
          : null;
      const responseMatches =
        responseReceived &&
        confirmed != null &&
        clientOperationId != null &&
        deleteResponseMatchesConfirmedDetail({
          response,
          confirmed,
          candidateId: targetCandidateId,
          clientOperationId,
        });
      const responseWasLost =
        !responseReceived && (requestStatus == null || requestStatus >= 500);
      if (
        requestAttempted &&
        clientOperationId != null &&
        confirmed != null &&
        (responseMatches || responseWasLost)
      ) {
        // DELETE 응답만 유실되고 commit은 끝난 경우 exact detail을 성공 정본으로
        // 승격한다. 모바일 handoff와 데스크톱 snackbar 모두 같은 경로를 탄다.
        if (!cacheHandledByOnDeleted) {
          const cacheResult = await reconcileProcessedCandidateCaches(
            queryClient,
            { ids: [targetCandidateId] },
          );
          if (cacheResult.postCommitRefreshFailed) {
            setCacheRefreshError({
              candidateId: targetCandidateId,
              message:
                "후보는 삭제됐지만 최신 검수 목록을 다시 확인하지 못했습니다.",
            });
            onCacheRefreshFailed?.();
          }
        }
        await onDeleted?.({
          deleted: true,
          id: targetCandidateId,
          client_operation_id: clientOperationId,
          state_revision: confirmed.stateRevision,
          review_state: "deleted",
          undo: confirmed.undo,
        });
        queryClient.removeQueries({
          queryKey: ["candidate-detail", targetCandidateId],
        });
        queryClient.removeQueries({
          queryKey: ["candidate-transcript", targetCandidateId],
        });
        return;
      }
      await onDeleteFailureRevalidated?.(
        targetCandidateId,
        authoritative,
        requestStatus,
        requestAttempted,
        clientOperationId,
      );
    },
    onSettled: () => {
      onDeleteSettled?.();
    },
  });

  useEffect(() => {
    if (transcriptText) {
      requestAnimationFrame(scrollTranscriptToEvidence);
    }
  }, [candidateId, scrollTranscriptToEvidence, transcriptText]);

  if (detailQuery.isLoading) {
    return (
      <p role="status" className="p-2 text-sm text-muted-foreground">
        불러오는 중…
      </p>
    );
  }
  if (!detail) {
    return (
      <div
        role="alert"
        className="flex flex-col items-start gap-2 p-2 text-sm text-destructive"
      >
        <p>{detailQuery.error?.message ?? "불러오지 못했습니다."}</p>
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={detailQuery.isFetching}
          onClick={() => void detailQuery.refetch()}
        >
          다시 시도
        </Button>
      </div>
    );
  }

  const c = detail.candidate;
  const destructiveActionsDisabled =
    actionsDisabled ||
    detailQuery.isError ||
    c.review_state !== "needs_review";
  const restorable = c.review_state !== "needs_review";
  const cleanedTranscript = transcriptText ? cleanTranscript(transcriptText) : "";

  return (
    <div className="flex flex-col gap-4">
      {detailQuery.data != null && detailQuery.isError ? (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-2 text-xs text-destructive">
          <span role="alert">
            최신 후보 상세를 다시 확인하지 못해 이전 정보를 표시합니다.
          </span>
          <Button
            type="button"
            size="xs"
            variant="outline"
            disabled={detailQuery.isFetching}
            onClick={() => void detailQuery.refetch()}
          >
            다시 확인
          </Button>
        </div>
      ) : null}
      <div>
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="text-base font-semibold">{c.ai_place_name}</h3>
          <Badge variant="outline">
            {categoryDisplayLabel(c.candidate_category)}
          </Badge>
          <Badge variant="secondary">
            {reviewStateLabel(c.review_state)}
          </Badge>
          {c.confidence_score != null ? (
            <Badge variant="outline">
              신뢰도 {Math.round(c.confidence_score * 100)}%
            </Badge>
          ) : null}
        </div>
        {c.location_hint ? (
          <p className="mt-1 text-sm text-muted-foreground">
            위치 힌트: {c.location_hint}
          </p>
        ) : null}
      </div>

      {c.video_is_excluded ? (
        <p
          role="status"
          className="rounded-lg border border-warning/40 bg-warning/5 p-2 text-xs text-warning"
        >
          출처 영상은 제외 상태입니다. 후보를 복구해도 영상 제외는 그대로
          유지됩니다.
        </p>
      ) : null}

      {detail.source_run ? (
        <DetailSection title="추출 작업(어느 큐)">
          <DetailRow
            label="작업 유형"
            value={
              detail.source_run.run_type_label ??
              detail.source_run.run_type ??
              "-"
            }
          />
          <DetailRow label="상태" value={detail.source_run.state ?? "-"} />
          {detail.source_run.model ? (
            <DetailRow label="모델" value={detail.source_run.model} />
          ) : null}
        </DetailSection>
      ) : null}

      {detail.video ? (
        <DetailSection title="동영상">
          <a
            href={timestampedVideoUrl(detail.video.url, c.timestamp_start)}
            target="_blank"
            rel="noreferrer"
            className="flex max-w-full items-start gap-1 font-medium text-primary hover:underline"
          >
            <span className="min-w-0 break-words">
              {detail.video.title ?? detail.video.video_id}
            </span>
            <ExternalLinkIcon className="mt-1 size-3 shrink-0" />
          </a>
          <p className="text-xs text-muted-foreground">
            {[
              detail.video.channel_title,
              durationLabel(detail.video.duration_seconds),
              dateLabel(detail.video.published_at),
            ]
              .filter(Boolean)
              .join(" · ")}
          </p>
          {detail.video.description ? (
            <p className="line-clamp-4 text-xs text-muted-foreground">
              {detail.video.description}
            </p>
          ) : null}
        </DetailSection>
      ) : null}

      <DetailSection
        title={
          transcriptQuery.data?.kind === "raw"
            ? "자막 (원본 — 보정본 없음)"
            : "보정 자막"
        }
      >
        <div className="mb-2 flex justify-end">
          <Button
            type="button"
            size="xs"
            variant="outline"
            disabled={!transcriptText}
            onClick={scrollTranscriptToEvidence}
          >
            근거 위치로 이동
          </Button>
        </div>
        {transcriptQuery.isLoading ? (
          <p className="text-xs text-muted-foreground">불러오는 중…</p>
        ) : transcriptText ? (
          <Tabs value={transcriptTab} onValueChange={(value) => setTranscriptTab(value ?? "raw")}>
            <TabsList className="w-full">
              <TabsTrigger value="raw">타임스탬프 포함</TabsTrigger>
              <TabsTrigger value="clean">정리본</TabsTrigger>
            </TabsList>
            <TabsContent value="raw" className="mt-2">
              <pre
                ref={transcriptRef}
                className="max-h-64 overflow-y-auto rounded-lg border bg-muted/30 p-2 text-xs whitespace-pre-wrap"
              >
                {transcriptText}
              </pre>
            </TabsContent>
            <TabsContent value="clean" className="mt-2">
              <pre className="max-h-64 overflow-y-auto rounded-lg border bg-muted/30 p-2 text-xs whitespace-pre-wrap">
                {cleanedTranscript}
              </pre>
            </TabsContent>
          </Tabs>
        ) : (
          <p className="text-xs text-muted-foreground">보정 자막 없음</p>
        )}
      </DetailSection>

      <DetailSection title="동영상 내 근거(어디에 나왔는지)">
        <DetailRow
          label="구간"
          value={
            [c.timestamp_start, c.timestamp_end].filter(Boolean).join(" ~ ") ||
            "-"
          }
        />
        <DetailRow label="출처" value={c.source_kind ?? "-"} />
        {c.source_text ? (
          <p className="rounded-lg border bg-muted/30 p-2 text-xs whitespace-pre-wrap">
            {c.source_text}
          </p>
        ) : null}
        {c.speaker_note ? (
          <p className="text-xs text-muted-foreground">메모: {c.speaker_note}</p>
        ) : null}
      </DetailSection>

      {detail.sibling_candidates.length > 0 ? (
        <DetailSection
          title={`같은 동영상의 다른 장소 (${detail.sibling_candidates.length})`}
        >
          <div className="flex flex-col gap-1">
            {detail.sibling_candidates.map((sibling) => (
              <Link
                key={sibling.id}
                className="flex items-center justify-between gap-2 rounded-md px-2 py-1 text-xs transition-colors hover:bg-surface-subtle"
                href={siblingHref(sibling)}
              >
                <span className="truncate">{sibling.ai_place_name}</span>
                <Badge variant="outline">
                  {reviewStateLabel(sibling.review_state)}
                </Badge>
              </Link>
            ))}
          </div>
        </DetailSection>
      ) : null}

      <div className="border-t pt-3">
        {restorable ? (
          <div className="flex flex-col items-start gap-2">
            <p className="text-xs text-muted-foreground">
              {c.review_state === "deleted"
                ? "삭제된 후보입니다. 복구하면 검수 대기로 돌아갑니다."
                : c.review_state === "ignored"
                  ? "제외된 후보입니다. 복구하면 검수 대기로 돌아갑니다."
                  : "확정된 후보입니다. 복구하면 장소 연결을 해제하고 검수 대기로 돌아갑니다."}
            </p>
            <Button
              type="button"
              size="sm"
              disabled={
                actionsDisabled ||
                restorePending ||
                detailQuery.isError ||
                detail.list_item.undo == null ||
                onRestoreRequested == null
              }
              onClick={() => onRestoreRequested?.(detail.list_item)}
            >
              {restorePending ? (
                <Loader2Icon data-icon="inline-start" className="animate-spin" />
              ) : (
                <RotateCcwIcon data-icon="inline-start" />
              )}
              복구
            </Button>
          </div>
        ) : confirmDelete ? (
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-medium text-destructive">
              정말 삭제할까요? 삭제 후 제외·삭제 목록에서 복구할 수 있습니다.
            </span>
            <Button
              type="button"
              size="sm"
              variant="destructive"
              disabled={deleteMutation.isPending || destructiveActionsDisabled}
              onClick={() => deleteMutation.mutate(candidateId)}
            >
              {deleteMutation.isPending ? (
                <Loader2Icon data-icon="inline-start" className="animate-spin" />
              ) : null}
              삭제
            </Button>
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={() => setConfirmDeleteCandidateId(null)}
            >
              취소
            </Button>
          </div>
        ) : (
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={destructiveActionsDisabled || deleteMutation.isPending}
            onClick={() => setConfirmDeleteCandidateId(candidateId)}
          >
            <Trash2Icon data-icon="inline-start" />
            후보 삭제
          </Button>
        )}
        {deleteMutation.error ? (
          <p
            role="alert"
            aria-live="assertive"
            className="mt-1 text-xs text-destructive"
          >
            {deleteMutation.error.message}
          </p>
        ) : null}
        {cacheRefreshError?.candidateId === candidateId ? (
          <p
            role="alert"
            aria-live="assertive"
            className="mt-1 text-xs text-destructive"
          >
            {cacheRefreshError.message}
          </p>
        ) : null}
      </div>
    </div>
  );
}
