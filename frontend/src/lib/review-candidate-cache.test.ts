import {
  InfiniteQueryObserver,
  QueryClient,
  type InfiniteData,
} from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";

import {
  ApiRequestError,
  type CandidateDetail,
  type ListEnvelope,
  type UnmatchedCandidate,
} from "./api";
import {
  candidateActionFailureDecision,
  candidateFailureSelectionDecision,
  getCandidateFromReviewPageCache,
  reconcileProcessedCandidateCaches,
  revalidateCandidateActionFailure,
  removeCandidatesFromReviewPageCaches,
  reviewCandidatePaginationContractError,
  reviewQueueProbeNotice,
  settleCandidateDeletes,
} from "./review-candidate-cache";

function candidate(id: number): UnmatchedCandidate {
  return {
    id,
    video_id: `video-${id}`,
    video_title: `영상 ${id}`,
    channel_title: null,
    ai_place_name: `후보 ${id}`,
    location_hint: null,
    candidate_category: null,
    candidate_category_code: null,
    match_status: "needs_review",
    confidence_score: null,
    source_kind: "transcript",
    grounding_status: "unverified",
    created_at: "2026-07-13T00:00:00Z",
    queue_reason: "ungrounded",
    timestamp_start: null,
    is_domestic: true,
  };
}

function detail(
  id: number,
  matchStatus = "needs_review",
): CandidateDetail {
  const listItem = { ...candidate(id), match_status: matchStatus };
  return {
    list_item: listItem,
    candidate: {
      id,
      video_id: listItem.video_id,
      source_channel_id: null,
      source_playlist_id: null,
      ai_place_name: listItem.ai_place_name,
      location_hint: listItem.location_hint,
      candidate_category: listItem.candidate_category,
      candidate_category_code: listItem.candidate_category_code,
      match_status: matchStatus,
      confidence_score: listItem.confidence_score,
      grounding_status: listItem.grounding_status,
      is_domestic: listItem.is_domestic,
      speaker_note: null,
      source_kind: listItem.source_kind,
      feature_export_status: "pending",
      timestamp_start: null,
      timestamp_end: null,
      source_text: null,
    },
    video: null,
    source_run: null,
    provider_evidence: null,
    sibling_candidates: [],
  };
}

function data(
  ids: number[],
  total = ids.length,
): InfiniteData<ListEnvelope<UnmatchedCandidate>> {
  return {
    pageParams: [null],
    pages: [
      {
        items: ids.map(candidate),
        next_cursor: null,
        has_more: false,
        total,
        newest_id: Math.max(0, ...ids),
        newer_than: 0,
      },
    ],
  };
}

describe("실패 action 선택 ABA 판정", () => {
  it("A 처리 확인 뒤 사용자가 B로 이동했으면 A state만 정리한다", () => {
    expect(
      candidateFailureSelectionDecision({
        failureDecision: candidateActionFailureDecision(
          { status: "success", detail: detail(1, "ignored") },
          false,
        ),
        candidateId: 1,
        currentCandidateId: 2,
      }),
    ).toBe("cleanup_candidate");
  });

  it("A→B→A 중 A 처리 확인이면 예전 epoch과 무관하게 현재 A를 진행시킨다", () => {
    expect(
      candidateFailureSelectionDecision({
        failureDecision: candidateActionFailureDecision(
          { status: "not_found" },
          false,
        ),
        candidateId: 1,
        currentCandidateId: 1,
      }),
    ).toBe("advance_current");
  });

  it("network error 또는 actionable 상세이면 현재 B 화면을 덮어쓰지 않는다", () => {
    expect(
      candidateFailureSelectionDecision({
        failureDecision: candidateActionFailureDecision(
          { status: "error", error: new Error("detail 500") },
          false,
        ),
        candidateId: 1,
        currentCandidateId: 2,
      }),
    ).toBe("keep");
    expect(
      candidateFailureSelectionDecision({
        failureDecision: candidateActionFailureDecision(
          { status: "success", detail: detail(1) },
          true,
        ),
        candidateId: 1,
        currentCandidateId: 2,
      }),
    ).toBe("keep");
  });
});

describe("검수 후보 cache 일관성", () => {
  it("성공한 active page에서 후보 유지·이탈과 신뢰 불가 상태를 구분한다", async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const pageKey = ["unmatched-candidates", "pages", "active-scope"];
    queryClient.setQueryData(pageKey, data([1, 2], 2));

    expect(getCandidateFromReviewPageCache(queryClient, pageKey, 1)?.id).toBe(1);
    expect(getCandidateFromReviewPageCache(queryClient, pageKey, 3)).toBeNull();

    await queryClient
      .fetchQuery({
        queryKey: pageKey,
        staleTime: 0,
        queryFn: async () => {
          throw new Error("page 500");
        },
      })
      .catch(() => undefined);
    expect(getCandidateFromReviewPageCache(queryClient, pageKey, 1)).toBeUndefined();
  });

  it("처리 성공 ID를 모든 page scope에서 제거하되 실제 보유한 cache의 total만 줄인다", () => {
    const queryClient = new QueryClient();
    const oldestKey = ["unmatched-candidates", "pages", "none", null, "", "oldest"];
    const newestKey = ["unmatched-candidates", "pages", "none", null, "", "newest"];
    const unrelatedKey = ["destinations"];
    queryClient.setQueryData(oldestKey, data([1, 2], 4));
    queryClient.setQueryData(newestKey, data([2, 3], 4));
    queryClient.setQueryData(unrelatedKey, { items: [candidate(2)] });

    removeCandidatesFromReviewPageCaches(queryClient, [1]);

    expect(
      queryClient.getQueryData<InfiniteData<ListEnvelope<UnmatchedCandidate>>>(oldestKey)
        ?.pages[0],
    ).toMatchObject({ items: [candidate(2)], total: 3 });
    expect(
      queryClient.getQueryData<InfiniteData<ListEnvelope<UnmatchedCandidate>>>(newestKey)
        ?.pages[0],
    ).toMatchObject({ items: [candidate(2), candidate(3)], total: 4 });
    expect(queryClient.getQueryData(unrelatedKey)).toEqual({ items: [candidate(2)] });
  });

  it("bulk DELETE 부분 성공을 성공 ID와 실패 ID로 분리한다", async () => {
    const result = await settleCandidateDeletes([1, 2, 3], async (id) => {
      if (id === 2) throw new Error("삭제 거부");
    });

    expect(result.attemptedIds).toEqual([1, 2, 3]);
    expect(result.succeededIds).toEqual([1, 3]);
    expect(result.failures).toHaveLength(1);
    expect(result.failures[0]).toMatchObject({ id: 2 });
  });

  it("commit 이전에 시작된 page/newer 요청을 취소하고 처리 ID를 다시 제거한다", async () => {
    const queryClient = new QueryClient();
    const pageKey = ["unmatched-candidates", "pages", "old-scope"];
    const newerKey = ["unmatched-candidates", "newer", "old-scope", 3];
    queryClient.setQueryData(pageKey, data([1, 2], 4));
    queryClient.setQueryData(newerKey, data([1], 1));
    const aborted: string[] = [];
    const startStaleFetch = (queryKey: unknown[], label: string) =>
      queryClient
        .fetchQuery<InfiniteData<ListEnvelope<UnmatchedCandidate>>>({
          queryKey,
          staleTime: 0,
          queryFn: ({ signal }) =>
            new Promise<InfiniteData<ListEnvelope<UnmatchedCandidate>>>(
              (_resolve, reject) => {
                signal.addEventListener("abort", () => {
                  aborted.push(label);
                  reject(new Error("취소됨"));
                });
              },
            ),
        })
        .catch(() => undefined);
    const pageFetch = startStaleFetch(pageKey, "page");
    const newerFetch = startStaleFetch(newerKey, "newer");
    await Promise.resolve();

    const result = await reconcileProcessedCandidateCaches(queryClient, {
      ids: [1],
    });
    await Promise.all([pageFetch, newerFetch]);

    expect(result.cancelledQueryCount).toBe(2);
    expect(aborted.sort()).toEqual(["newer", "page"]);
    expect(
      queryClient.getQueryData<InfiniteData<ListEnvelope<UnmatchedCandidate>>>(pageKey)
        ?.pages[0].items.map((item) => item.id),
    ).toEqual([2]);
    expect(queryClient.getQueryState(pageKey)?.isInvalidated).toBe(true);
    expect(queryClient.getQueryState(newerKey)?.isInvalidated).toBe(true);
  });

  it("같은 scope의 진행 중 snapshot을 취소했으면 commit 이후 exact page를 복구한다", async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const pageKey = ["unmatched-candidates", "pages", "same-scope"];
    let fetchCount = 0;
    const observer = new InfiniteQueryObserver(queryClient, {
      queryKey: pageKey,
      initialPageParam: null as string | null,
      getNextPageParam: () => undefined,
      queryFn: ({ signal }) => {
        fetchCount += 1;
        if (fetchCount > 1) return Promise.resolve(data([2], 3).pages[0]);
        return new Promise<ListEnvelope<UnmatchedCandidate>>(
          (_resolve, reject) => {
            signal.addEventListener("abort", () =>
              reject(new Error("snapshot 취소")),
            );
          },
        );
      },
    });
    const unsubscribe = observer.subscribe(() => {});
    await Promise.resolve();

    const result = await reconcileProcessedCandidateCaches(queryClient, {
      ids: [1],
      capturedPageKey: pageKey,
      activePageKey: pageKey,
    });
    unsubscribe();

    expect(result.cancelledQueryCount).toBe(1);
    expect(result.postCommitRefreshFailed).toBe(false);
    expect(fetchCount).toBe(2);
    expect(
      queryClient.getQueryData<InfiniteData<ListEnvelope<UnmatchedCandidate>>>(
        pageKey,
      )?.pages[0].items.map((item) => item.id),
    ).toEqual([2]);
    expect(queryClient.getQueryState(pageKey)?.fetchStatus).toBe("idle");
  });

  it("scope가 바뀌면 새 active exact page를 commit 이후 다시 조회한다", async () => {
    const queryClient = new QueryClient();
    const capturedPageKey = ["unmatched-candidates", "pages", "old-scope"];
    const activePageKey = ["unmatched-candidates", "pages", "new-scope"];
    queryClient.setQueryData(activePageKey, data([1, 2], 4));
    const refetch = vi
      .spyOn(queryClient, "refetchQueries")
      .mockResolvedValue(undefined);

    await reconcileProcessedCandidateCaches(queryClient, {
      ids: [1],
      capturedPageKey,
      activePageKey,
    });

    expect(refetch).toHaveBeenCalledWith({
      queryKey: activePageKey,
      exact: true,
      type: "all",
    });
    expect(
      queryClient.getQueryData<InfiniteData<ListEnvelope<UnmatchedCandidate>>>(
        activePageKey,
      )?.pages[0].items.map((item) => item.id),
    ).toEqual([2]);
  });

  it("active exact 재조회 실패를 마지막 cache 쓰기 뒤에도 호출자에게 반환한다", async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const capturedPageKey = ["unmatched-candidates", "pages", "old-scope"];
    const activePageKey = ["unmatched-candidates", "pages", "new-scope"];
    let shouldFail = false;
    await queryClient.fetchQuery({
      queryKey: activePageKey,
      queryFn: async () => {
        if (shouldFail) throw new Error("post-commit 500");
        return data([1, 2], 4);
      },
    });
    shouldFail = true;

    const result = await reconcileProcessedCandidateCaches(queryClient, {
      ids: [1],
      capturedPageKey,
      activePageKey,
    });

    expect(result.postCommitRefreshFailed).toBe(true);
    // 최종 ID 재제거가 TanStack Query의 error를 지워도 반환값은 보존된다.
    expect(queryClient.getQueryState(activePageKey)?.error).toBeNull();
    expect(queryClient.getQueryState(activePageKey)?.isInvalidated).toBe(true);
  });

  it("action 실패 뒤 active page와 retained detail을 exact 재검증하고 실패를 반환한다", async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const pageKey = ["unmatched-candidates", "pages", "active-scope"];
    const inactivePageKey = [
      "unmatched-candidates",
      "pages",
      "inactive-scope",
    ];
    const detailKey = ["candidate-detail", 1];
    let shouldFail = false;
    await Promise.all([
      queryClient.fetchQuery({
        queryKey: pageKey,
        queryFn: async () => {
          if (shouldFail) throw new Error("page 500");
          return data([1], 1);
        },
      }),
      queryClient.fetchQuery({
        queryKey: detailKey,
        queryFn: async () => detail(1),
      }),
      queryClient.fetchQuery({
        queryKey: inactivePageKey,
        queryFn: async () => data([1], 1),
      }),
    ]);
    shouldFail = true;

    const result = await revalidateCandidateActionFailure(queryClient, {
      candidateIds: [1],
      activePageKey: pageKey,
      fetchCandidateDetail: async () => {
        throw new Error("detail 500");
      },
    });

    expect(result.refreshedQueryCount).toBe(2);
    expect(result.refreshFailed).toBe(true);
    const detailRevalidation = result.candidateDetails.get(1);
    expect(detailRevalidation?.status).toBe("error");
    if (!detailRevalidation) throw new Error("단건 상세 재검증 결과 누락");
    expect(candidateActionFailureDecision(detailRevalidation, true)).toBe(
      "keep",
    );
    expect(queryClient.getQueryState(pageKey)?.status).toBe("error");
    expect(queryClient.getQueryState(detailKey)?.status).toBe("error");
    expect(queryClient.getQueryData(detailKey)).toEqual(detail(1));
    expect(queryClient.getQueryState(inactivePageKey)?.isInvalidated).toBe(true);
  });

  it("oldest 300 page-out 후보는 actionable 상세에서 유지하고 retry 404에서 진행한다", async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const pageKey = [
      "unmatched-candidates",
      "pages",
      "none",
      null,
      "",
      "oldest",
    ];
    const initialIds = Array.from({ length: 300 }, (_, index) => index + 2);
    const shiftedIds = Array.from({ length: 300 }, (_, index) => index + 1);
    let reopened = false;
    await queryClient.fetchQuery({
      queryKey: pageKey,
      queryFn: async () => {
        const snapshot = data(
          reopened ? shiftedIds : initialIds,
          reopened ? 301 : 300,
        );
        if (reopened) {
          snapshot.pages[0].has_more = true;
          snapshot.pages[0].next_cursor = "oldest-after-300";
        }
        return snapshot;
      },
    });
    expect(queryClient.getQueryState(["candidate-detail", 301])).toBeUndefined();
    reopened = true;
    const fetchCandidateDetail = vi.fn(async () => detail(301));

    const result = await revalidateCandidateActionFailure(queryClient, {
      candidateIds: [301],
      activePageKey: pageKey,
      fetchCandidateDetail,
    });

    expect(fetchCandidateDetail).toHaveBeenCalledWith(301);
    expect(result.refreshedQueryCount).toBe(2);
    expect(result.refreshFailed).toBe(false);
    expect(
      getCandidateFromReviewPageCache(queryClient, pageKey, 301),
    ).toBeNull();
    const detailRevalidation = result.candidateDetails.get(301);
    expect(detailRevalidation?.status).toBe("success");
    if (!detailRevalidation) throw new Error("단건 상세 재검증 결과 누락");
    expect(candidateActionFailureDecision(detailRevalidation, true)).toBe(
      "keep",
    );
    expect(queryClient.getQueryData(["candidate-detail", 301])).toEqual(
      detail(301),
    );

    const retryResult = await revalidateCandidateActionFailure(queryClient, {
      candidateIds: [301],
      activePageKey: pageKey,
      fetchCandidateDetail: async () => {
        throw new ApiRequestError(404, { detail: "not found" }, "404");
      },
    });
    const retryDetail = retryResult.candidateDetails.get(301);
    expect(retryResult.refreshFailed).toBe(false);
    expect(retryDetail?.status).toBe("not_found");
    if (!retryDetail) throw new Error("retry 단건 상세 재검증 결과 누락");
    expect(candidateActionFailureDecision(retryDetail, false)).toBe("advance");
  });

  it("실패한 action의 단건 상세가 404면 다른 검수자 처리로 판단한다", async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });

    const result = await revalidateCandidateActionFailure(queryClient, {
      candidateIds: [7],
      fetchCandidateDetail: async () => {
        throw new ApiRequestError(404, { detail: "not found" }, "404");
      },
    });

    const detailRevalidation = result.candidateDetails.get(7);
    expect(result.refreshFailed).toBe(false);
    expect(detailRevalidation?.status).toBe("not_found");
    if (!detailRevalidation) throw new Error("단건 상세 재검증 결과 누락");
    expect(candidateActionFailureDecision(detailRevalidation, false)).toBe(
      "advance",
    );
  });

  it("oldest 300 page-out 후보의 retry 상세가 non-actionable이면 다음 후보로 진행한다", async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const pageKey = [
      "unmatched-candidates",
      "pages",
      "none",
      null,
      "",
      "oldest",
    ];
    const initialIds = Array.from({ length: 300 }, (_, index) => index + 2);
    const shiftedIds = Array.from({ length: 300 }, (_, index) => index + 1);
    let reopened = false;
    await queryClient.fetchQuery({
      queryKey: pageKey,
      queryFn: async () => {
        const snapshot = data(
          reopened ? shiftedIds : initialIds,
          reopened ? 301 : 300,
        );
        if (reopened) {
          snapshot.pages[0].has_more = true;
          snapshot.pages[0].next_cursor = "oldest-after-300";
        }
        return snapshot;
      },
    });
    reopened = true;
    const firstResult = await revalidateCandidateActionFailure(queryClient, {
      candidateIds: [301],
      activePageKey: pageKey,
      fetchCandidateDetail: async () => detail(301),
    });
    const firstDetail = firstResult.candidateDetails.get(301);
    expect(
      getCandidateFromReviewPageCache(queryClient, pageKey, 301),
    ).toBeNull();
    expect(firstDetail?.status).toBe("success");
    if (!firstDetail) throw new Error("최초 단건 상세 재검증 결과 누락");
    expect(candidateActionFailureDecision(firstDetail, true)).toBe("keep");

    const result = await revalidateCandidateActionFailure(queryClient, {
      candidateIds: [301],
      activePageKey: pageKey,
      fetchCandidateDetail: async () => detail(301, "ignored"),
    });

    const detailRevalidation = result.candidateDetails.get(301);
    expect(result.refreshFailed).toBe(false);
    expect(detailRevalidation?.status).toBe("success");
    if (!detailRevalidation) throw new Error("단건 상세 재검증 결과 누락");
    expect(candidateActionFailureDecision(detailRevalidation, false)).toBe(
      "advance",
    );
    expect(queryClient.getQueryData(["candidate-detail", 301])).toEqual(
      detail(301, "ignored"),
    );
  });

  it("실패한 action의 단건 상세가 network error면 기존 선택을 유지한다", async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const detailKey = ["candidate-detail", 9];
    queryClient.setQueryData(detailKey, detail(9));

    const result = await revalidateCandidateActionFailure(queryClient, {
      candidateIds: [9],
      fetchCandidateDetail: async () => {
        throw new TypeError("Failed to fetch");
      },
    });

    const detailRevalidation = result.candidateDetails.get(9);
    expect(result.refreshFailed).toBe(true);
    expect(detailRevalidation?.status).toBe("error");
    if (!detailRevalidation) throw new Error("단건 상세 재검증 결과 누락");
    expect(candidateActionFailureDecision(detailRevalidation, true)).toBe(
      "keep",
    );
    expect(queryClient.getQueryData(detailKey)).toEqual(detail(9));
  });

  it("cursor 누락·반복과 terminal total 누락을 pagination 계약 오류로 막는다", () => {
    const missingCursor = data([1], 2).pages[0];
    missingCursor.has_more = true;
    expect(reviewCandidatePaginationContractError([missingCursor])).toContain(
      "cursor",
    );

    const first = data([1], 2).pages[0];
    first.has_more = true;
    first.next_cursor = "same";
    const second = data([2], 2).pages[0];
    second.has_more = true;
    second.next_cursor = "same";
    expect(reviewCandidatePaginationContractError([first, second])).toContain(
      "반복",
    );

    const truncated = data([1, 2], 3).pages[0];
    expect(reviewCandidatePaginationContractError([truncated])).toContain(
      "중간에 끊겼습니다",
    );
  });

  it("probe total 또는 newer_than 변화만 사용자 재시작 안내로 만든다", () => {
    expect(
      reviewQueueProbeNotice({
        snapshotTotal: 10,
        probeTotal: 9,
        newerThan: 0,
      }),
    ).toBe("검수 큐가 변경됨 — 새로 불러오기");
    expect(
      reviewQueueProbeNotice({
        snapshotTotal: 10,
        probeTotal: 11,
        newerThan: 1,
      }),
    ).toContain("새 후보 1건");
    expect(
      reviewQueueProbeNotice({
        snapshotTotal: 10,
        probeTotal: 10,
        newerThan: 0,
      }),
    ).toBeNull();
  });
});
