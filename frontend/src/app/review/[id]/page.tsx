"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowLeftIcon } from "lucide-react";

import { AppShell } from "@/components/AppShell";
import { CandidateDetailView } from "@/components/CandidateDetailView";
import {
  ApiRequestError,
  getCandidateDetail,
  reopenCandidate,
  type CandidateDetail,
  type UnmatchedCandidate,
} from "@/lib/api";
import {
  prepareCandidateReopenCaches,
  reconcileCandidateReopenCaches,
} from "@/lib/review-candidate-cache";
import {
  parseReviewCandidateIdValue,
  parseReviewListState,
  writeReviewListState,
} from "@/lib/review-list-state";
import {
  classifyReviewUndoOutcome,
  REVIEW_UNDO_HANDOFF_STORAGE_KEY,
  serializeReviewUndoHandoff,
} from "@/lib/review-undo";

export default function CandidateDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const queryClient = useQueryClient();
  const [restoreError, setRestoreError] = useState<string | null>(null);
  const id = parseReviewCandidateIdValue(params.id);
  const reviewHref = (candidateId: number) => {
    let stored = "";
    try {
      stored = window.sessionStorage.getItem("ktc.review.listSearch") ?? "";
    } catch {
      // URL 기본값으로 계속 진행한다.
    }
    const source = new URLSearchParams(stored);
    const next = writeReviewListState(source, {
      ...parseReviewListState(source),
      status: "needs_review",
    });
    next.set("candidate", String(candidateId));
    return `/review?${next.toString()}`;
  };
  const restoreMutation = useMutation({
    mutationFn: async (candidate: UnmatchedCandidate) => {
      if (
        !candidate.undo ||
        candidate.undo.candidate_id !== candidate.id ||
        candidate.undo.token.length === 0
      ) {
        throw new Error("최신 복구 token이 후보와 일치하지 않습니다.");
      }
      let request:
        | { kind: "success" }
        | { kind: "error"; status: number | null };
      try {
        await prepareCandidateReopenCaches(queryClient, candidate.id);
        await reopenCandidate(candidate.undo);
        request = { kind: "success" };
      } catch (error) {
        request = {
          kind: "error",
          status: error instanceof ApiRequestError ? error.status : null,
        };
      }
      const authoritative = await reconcileCandidateReopenCaches(queryClient, {
        candidateId: candidate.id,
        fetchCandidateDetail: getCandidateDetail,
      });
      return {
        candidate,
        authoritative,
        classification: classifyReviewUndoOutcome({
          request,
          authoritative: authoritative.detail,
          expectedReviewState: candidate.review_state,
        }),
      };
    },
    onMutate: () => setRestoreError(null),
    onSuccess: ({ candidate, authoritative, classification }) => {
      if (
        classification === "restored" &&
        authoritative.canReselect
      ) {
        router.push(reviewHref(candidate.id));
        return;
      }
      setRestoreError(
        classification === "stale"
          ? "다른 작업으로 후보 상태가 바뀌어 이 복구 요청을 사용할 수 없습니다. 최신 검수 큐에서 확인해 주세요."
          : "복구 결과를 확인하지 못했습니다. 같은 버튼으로 다시 시도해 주세요.",
      );
    },
    onError: () => {
      setRestoreError(
        "복구 뒤 최신 후보 상태를 확인하지 못했습니다. 잠시 후 다시 시도해 주세요.",
      );
    },
  });

  return (
    <AppShell title="검수 후보 상세">
      <div className="mx-auto w-full max-w-2xl p-4">
        <Link
          href="/review"
          className="inline-flex items-center gap-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground"
        >
          <ArrowLeftIcon className="size-4" />
          검수 큐로
        </Link>
        <div className="mt-3 rounded-xl border p-4">
          {id != null ? (
            <CandidateDetailView
              candidateId={id}
              restorePending={restoreMutation.isPending}
              onRestoreRequested={(candidate) => {
                if (
                  !candidate.undo ||
                  candidate.undo.candidate_id !== candidate.id ||
                  candidate.undo.token.length === 0
                ) {
                  setRestoreError(
                    "최신 복구 token이 없습니다. 상세를 새로 불러와 주세요.",
                  );
                  return;
                }
                restoreMutation.mutate(candidate);
              }}
              onDeleted={(result) => {
                const detail = queryClient.getQueryData<CandidateDetail>([
                  "candidate-detail",
                  result.id,
                ]);
                try {
                  window.sessionStorage.removeItem(
                    REVIEW_UNDO_HANDOFF_STORAGE_KEY,
                  );
                  window.sessionStorage.setItem(
                    REVIEW_UNDO_HANDOFF_STORAGE_KEY,
                    serializeReviewUndoHandoff({
                      candidateId: result.id,
                      candidateName:
                        detail?.candidate.ai_place_name ?? `후보 #${result.id}`,
                      action: "delete",
                      reviewState: "deleted",
                      clientOperationId: result.client_operation_id,
                      undo: result.undo,
                    }),
                  );
                } catch {
                  // 새 handoff 기록이 실패하면 과거 token을 최신 결과로 오인하지 않는다.
                  try {
                    window.sessionStorage.removeItem(
                      REVIEW_UNDO_HANDOFF_STORAGE_KEY,
                    );
                  } catch {
                    // sessionStorage 자체가 비활성이어도 큐 이동은 유지한다.
                  }
                }
                router.push("/review");
              }}
            />
          ) : (
            <p role="alert" className="text-sm text-destructive">
              잘못된 후보 ID
            </p>
          )}
          {restoreError ? (
            <p role="alert" className="mt-3 text-sm text-destructive">
              {restoreError}
            </p>
          ) : null}
        </div>
      </div>
    </AppShell>
  );
}
