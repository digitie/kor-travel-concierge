import type {
  InfiniteData,
  QueryClient,
  QueryKey,
} from "@tanstack/react-query";

import {
  ApiRequestError,
  type CandidateDetail,
  type ListEnvelope,
  type UnmatchedCandidate,
} from "./api";

export const REVIEW_CANDIDATE_PAGE_QUERY_PREFIX = [
  "unmatched-candidates",
  "pages",
] as const;

export const REVIEW_CANDIDATE_NEWER_QUERY_PREFIX = [
  "unmatched-candidates",
  "newer",
] as const;

export function removeCandidatesFromQueue(
  data: InfiniteData<ListEnvelope<UnmatchedCandidate>> | undefined,
  ids: readonly number[],
): InfiniteData<ListEnvelope<UnmatchedCandidate>> | undefined {
  if (!data || ids.length === 0) return data;
  const removed = new Set(ids);
  const removedCount = new Set(
    data.pages.flatMap((page) =>
      page.items
        .filter((candidate) => removed.has(candidate.id))
        .map((candidate) => candidate.id),
    ),
  ).size;
  if (removedCount === 0) return data;
  return {
    ...data,
    pages: data.pages.map((page) => ({
      ...page,
      items: page.items.filter((candidate) => !removed.has(candidate.id)),
      // 각 page의 total은 같은 filter 전체 건수다. 실제로 이 cache에 있던 ID만
      // 빼서 다른 status/filter cache의 미적재 항목 때문에 total이 틀어지지 않게 한다.
      total: Math.max(0, page.total - removedCount),
    })),
  };
}

/** 현재 scope뿐 아니라 보관 중인 모든 검수 page cache에서 처리된 ID를 제거한다. */
export function removeCandidatesFromReviewPageCaches(
  queryClient: QueryClient,
  ids: readonly number[],
): void {
  if (ids.length === 0) return;
  queryClient.setQueriesData<
    InfiniteData<ListEnvelope<UnmatchedCandidate>>
  >({ queryKey: REVIEW_CANDIDATE_PAGE_QUERY_PREFIX }, (data) =>
    removeCandidatesFromQueue(data, ids),
  );
}

function sameQueryKey(left: QueryKey, right: QueryKey): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}

/**
 * 실패한 mutation 뒤 exact 재조회가 성공한 active page에서 후보의 최신 membership을
 * 읽는다. `undefined`는 재조회 결과를 신뢰할 수 없음, `null`은 서버 목록에서 사라짐이다.
 */
export function getCandidateFromReviewPageCache(
  queryClient: QueryClient,
  pageKey: QueryKey,
  candidateId: number,
): UnmatchedCandidate | null | undefined {
  if (queryClient.getQueryState(pageKey)?.status !== "success") {
    return undefined;
  }
  const data = queryClient.getQueryData<
    InfiniteData<ListEnvelope<UnmatchedCandidate>>
  >(pageKey);
  if (!data) return undefined;
  return (
    data.pages
      .flatMap((page) => page.items)
      .find((candidate) => candidate.id === candidateId) ?? null
  );
}

export type ReconcileProcessedCandidateCachesOptions = {
  ids: readonly number[];
  capturedPageKey?: QueryKey;
  activePageKey?: QueryKey;
  pageOut?: boolean;
};

export type CandidateDetailRevalidation =
  | { status: "success"; detail: CandidateDetail }
  | { status: "not_found" }
  | { status: "error"; error: unknown };

/**
 * 실패한 쓰기의 결과를 단건 상세로 다시 확인한 뒤 선택을 유지할지 판정한다.
 * 목록 page 부재는 pagination 이동일 수 있으므로 판정 근거로 사용하지 않는다.
 */
export function candidateActionFailureDecision(
  detail: CandidateDetailRevalidation,
  actionableInCurrentFilter: boolean,
): "keep" | "advance" {
  if (detail.status === "not_found") return "advance";
  if (detail.status === "error") return "keep";
  return actionableInCurrentFilter ? "keep" : "advance";
}

export type CandidateFailureSelectionDecision =
  | "keep"
  | "cleanup_candidate"
  | "advance_current";

/**
 * 실패 action의 최신 상세 판정과 현재 선택을 결합한다. 처리된 후보가 예전 workflow의
 * 대상이어도 후보 단위 state는 정리하되, 사용자가 이동한 다른 후보 화면은 건드리지 않는다.
 */
export function candidateFailureSelectionDecision({
  failureDecision,
  candidateId,
  currentCandidateId,
}: {
  failureDecision: "keep" | "advance";
  candidateId: number;
  currentCandidateId: number | null;
}): CandidateFailureSelectionDecision {
  if (failureDecision === "keep") return "keep";
  return candidateId === currentCandidateId
    ? "advance_current"
    : "cleanup_candidate";
}

/**
 * mutation commit 이전에 시작된 page/newer 요청이 늦게 완료되어 처리 후보를 되살리는
 * 일을 막는다. 진행 중 요청만 취소하고 idle multi-page snapshot은 그대로 보존한다.
 */
export async function reconcileProcessedCandidateCaches(
  queryClient: QueryClient,
  {
    ids,
    capturedPageKey,
    activePageKey,
    pageOut = false,
  }: ReconcileProcessedCandidateCachesOptions,
): Promise<{
  cancelledQueryCount: number;
  postCommitRefreshFailed: boolean;
}> {
  if (ids.length === 0) {
    return { cancelledQueryCount: 0, postCommitRefreshFailed: false };
  }

  const pageQueries = queryClient
    .getQueryCache()
    .findAll({ queryKey: REVIEW_CANDIDATE_PAGE_QUERY_PREFIX });
  const newerQueries = queryClient
    .getQueryCache()
    .findAll({ queryKey: REVIEW_CANDIDATE_NEWER_QUERY_PREFIX });
  const activeNewerKeys = newerQueries
    .filter((query) => query.getObserversCount() > 0)
    .map((query) => query.queryKey);
  const fetchingQueries = Array.from(
    new Map(
      [...pageQueries, ...newerQueries]
        .filter((query) => query.state.fetchStatus === "fetching")
        .map((query) => [query.queryHash, query]),
    ).values(),
  );
  const activePageWasFetching = Boolean(
    activePageKey &&
      fetchingQueries.some((query) =>
        sameQueryKey(query.queryKey, activePageKey),
      ),
  );

  await Promise.all(
    fetchingQueries.map((query) =>
      queryClient.cancelQueries({ queryKey: query.queryKey, exact: true }),
    ),
  );
  removeCandidatesFromReviewPageCaches(queryClient, ids);
  await Promise.all([
    queryClient.invalidateQueries({
      queryKey: REVIEW_CANDIDATE_PAGE_QUERY_PREFIX,
      refetchType: "none",
    }),
    queryClient.invalidateQueries({
      queryKey: REVIEW_CANDIDATE_NEWER_QUERY_PREFIX,
      refetchType: "none",
    }),
  ]);

  const postCommitRefreshKeys: QueryKey[] = [...activeNewerKeys];
  const postCommitRefreshes: Promise<unknown>[] = activeNewerKeys.map(
    (queryKey) =>
      queryClient.refetchQueries({ queryKey, exact: true, type: "all" }),
  );
  if (
    activePageKey &&
    (!capturedPageKey ||
      !sameQueryKey(capturedPageKey, activePageKey) ||
      activePageWasFetching)
  ) {
    // 새 scope cache에는 처리 ID가 아직 적재되지 않아 membership/total을 로컬로
    // 판정할 수 없다. 같은 scope라도 success 시점에 진행 중이던 snapshot reset을
    // 취소했다면 no-data revert 상태가 될 수 있으므로 exact 응답으로 다시 만든다.
    postCommitRefreshes.push(
      queryClient.refetchQueries({
        queryKey: activePageKey,
        exact: true,
        type: "all",
      }),
    );
    postCommitRefreshKeys.push(activePageKey);
  } else if (capturedPageKey && pageOut) {
    // page-out 후보는 현재 snapshot에 ID가 없어 total을 줄일 근거가 없다.
    postCommitRefreshes.push(
      queryClient.resetQueries({ queryKey: capturedPageKey, exact: true }),
    );
    postCommitRefreshKeys.push(capturedPageKey);
  }
  const postCommitRefreshResults = await Promise.allSettled(postCommitRefreshes);
  // TanStack Query의 background refetch는 HTTP 오류에도 기본적으로 reject하지 않을
  // 수 있다. 마지막 setQueriesData가 query.error를 지우기 전에 query state를 읽어
  // 호출자가 사용자에게 snapshot 재시작 필요성을 계속 알릴 수 있게 한다.
  const postCommitRefreshFailed =
    postCommitRefreshResults.some((result) => result.status === "rejected") ||
    postCommitRefreshKeys.some(
      (queryKey) => queryClient.getQueryState(queryKey)?.status === "error",
    );
  removeCandidatesFromReviewPageCaches(queryClient, ids);
  // 마지막 setQueriesData는 page query의 isInvalidated를 false로 되돌린다.
  // active exact refresh를 즉시 반복하지 않으면서 inactive scope가 재진입 때
  // 서버 snapshot을 다시 읽도록, 모든 cache 정리가 끝난 뒤 stale 표식을 복구한다.
  await Promise.all([
    queryClient.invalidateQueries({
      queryKey: REVIEW_CANDIDATE_PAGE_QUERY_PREFIX,
      refetchType: "none",
    }),
    queryClient.invalidateQueries({
      queryKey: REVIEW_CANDIDATE_NEWER_QUERY_PREFIX,
      refetchType: "none",
    }),
  ]);
  return {
    cancelledQueryCount: fetchingQueries.length,
    postCommitRefreshFailed,
  };
}

export type PrepareCandidateReopenCachesResult = {
  cancelledQueryCount: number;
};

/**
 * reopen POST보다 먼저 실행해 이전 page/probe/detail 응답이 복구 뒤 상태를 되감지
 * 못하게 한다. 처리 대상은 모든 page cache에서 빼되 서버 결과가 불명확하면 후속 exact
 * reset이 원 상태를 다시 가져오므로 optimistic snapshot을 판정 근거로 쓰지 않는다.
 */
export async function prepareCandidateReopenCaches(
  queryClient: QueryClient,
  candidateId: number,
): Promise<PrepareCandidateReopenCachesResult> {
  const detailKey = ["candidate-detail", candidateId] as const;
  const queries = [
    ...queryClient
      .getQueryCache()
      .findAll({ queryKey: REVIEW_CANDIDATE_PAGE_QUERY_PREFIX }),
    ...queryClient
      .getQueryCache()
      .findAll({ queryKey: REVIEW_CANDIDATE_NEWER_QUERY_PREFIX }),
    ...queryClient.getQueryCache().findAll({ queryKey: detailKey, exact: true }),
  ];
  const fetchingQueries = Array.from(
    new Map(
      queries
        .filter((query) => query.state.fetchStatus === "fetching")
        .map((query) => [query.queryHash, query]),
    ).values(),
  );
  await Promise.all(
    fetchingQueries.map((query) =>
      queryClient.cancelQueries({ queryKey: query.queryKey, exact: true }),
    ),
  );
  removeCandidatesFromReviewPageCaches(queryClient, [candidateId]);
  await Promise.all([
    queryClient.invalidateQueries({
      queryKey: REVIEW_CANDIDATE_PAGE_QUERY_PREFIX,
      refetchType: "none",
    }),
    queryClient.invalidateQueries({
      queryKey: REVIEW_CANDIDATE_NEWER_QUERY_PREFIX,
      refetchType: "none",
    }),
    queryClient.invalidateQueries({
      queryKey: detailKey,
      exact: true,
      refetchType: "none",
    }),
  ]);
  return { cancelledQueryCount: fetchingQueries.length };
}

export type ReconcileCandidateReopenCachesResult = {
  detail: CandidateDetailRevalidation;
  canReselect: boolean;
  activePageRefreshed: boolean;
  refreshFailed: boolean;
};

/**
 * reopen 응답 직후 active infinite snapshot을 첫 page부터 exact 재시작하고 상세도 실제
 * HTTP로 확인한다. 반환된 최신 `review_state=needs_review`만 UI 재선택 근거가 된다.
 */
export async function reconcileCandidateReopenCaches(
  queryClient: QueryClient,
  {
    candidateId,
    activePageKey,
    fetchCandidateDetail,
  }: {
    candidateId: number;
    activePageKey?: QueryKey;
    fetchCandidateDetail: (candidateId: number) => Promise<CandidateDetail>;
  },
): Promise<ReconcileCandidateReopenCachesResult> {
  const detailKey = ["candidate-detail", candidateId] as const;
  let activePageRefreshed = false;
  let activePageRefreshRejected = false;
  if (activePageKey) {
    try {
      const activePageQuery = queryClient
        .getQueryCache()
        .find({ queryKey: activePageKey, exact: true });
      const wasActive = activePageQuery?.isActive() ?? false;
      // resetQueries는 infinite pages/pageParams를 폐기하고 active observer를 첫 page부터
      // 다시 조회한다. observer가 없는 retained query는 자동 fetch되지 않으므로 저장된
      // queryFn을 명시적으로 exact refetch해야 서버 snapshot을 확인했다고 볼 수 있다.
      await queryClient.resetQueries({ queryKey: activePageKey, exact: true });
      if (
        activePageQuery &&
        (!wasActive ||
          queryClient.getQueryState(activePageKey)?.status !== "success")
      ) {
        await activePageQuery.fetch();
      } else if (queryClient.getQueryState(activePageKey)?.status !== "success") {
        await queryClient.refetchQueries({
          queryKey: activePageKey,
          exact: true,
          type: "all",
        });
      }
      activePageRefreshed =
        queryClient.getQueryState(activePageKey)?.status === "success";
    } catch {
      activePageRefreshRejected = true;
    }
  }

  let detail: CandidateDetailRevalidation;
  try {
    // prepare 이후 사용자가 상세를 열어 POST commit 전 snapshot 요청이 다시 시작될 수
    // 있다. fetchQuery가 그 promise에 합류하지 않도록 직후 경계에서도 exact 취소한다.
    await queryClient.cancelQueries({ queryKey: detailKey, exact: true });
    const latest = await queryClient.fetchQuery({
      queryKey: detailKey,
      staleTime: 0,
      retry: false,
      queryFn: async () => {
        const response = await fetchCandidateDetail(candidateId);
        if (response.list_item.id !== candidateId) {
          throw new Error("후보 상세 응답의 ID가 요청과 일치하지 않습니다.");
        }
        return response;
      },
    });
    detail = { status: "success", detail: latest };
  } catch (error) {
    detail =
      error instanceof ApiRequestError && error.status === 404
        ? { status: "not_found" }
        : { status: "error", error };
  }

  // exact 성공을 보존하면서 다른 filter snapshot만 stale로 둔다. current page까지 다시
  // invalidate하면 성공 직후 중복 refetch가 발생하고 복구한 후보의 선택 근거도 흔들린다.
  await Promise.all([
    queryClient.invalidateQueries({
      queryKey: REVIEW_CANDIDATE_PAGE_QUERY_PREFIX,
      refetchType: "none",
      predicate: (query) =>
        !activePageKey || !sameQueryKey(query.queryKey, activePageKey),
    }),
    queryClient.invalidateQueries({
      queryKey: REVIEW_CANDIDATE_NEWER_QUERY_PREFIX,
      refetchType: "none",
    }),
  ]);

  const activePageErrored = Boolean(
    activePageKey && queryClient.getQueryState(activePageKey)?.status === "error",
  );
  return {
    detail,
    canReselect:
      detail.status === "success" &&
      detail.detail.list_item.review_state === "needs_review",
    activePageRefreshed,
    refreshFailed:
      activePageRefreshRejected ||
      Boolean(activePageKey && !activePageRefreshed) ||
      activePageErrored ||
      detail.status === "error",
  };
}

/**
 * 실패한 resolve/delete 뒤 Infinity cache의 active page와 후보 단건 상세를 서버에서
 * 다시 읽는다. 상세 cache가 없던 목록 후보도 반드시 실제 요청하고, page에서 사라졌다는
 * 사실만으로 다른 검수자가 처리했다고 단정하지 않게 호출자에게 후보별 결과를 돌려준다.
 */
export async function revalidateCandidateActionFailure(
  queryClient: QueryClient,
  {
    candidateIds,
    activePageKey,
    fetchCandidateDetail,
  }: {
    candidateIds: readonly number[];
    activePageKey?: QueryKey;
    fetchCandidateDetail: (candidateId: number) => Promise<CandidateDetail>;
  },
): Promise<{
  refreshedQueryCount: number;
  refreshFailed: boolean;
  candidateDetails: ReadonlyMap<number, CandidateDetailRevalidation>;
}> {
  const uniqueCandidateIds = Array.from(new Set(candidateIds));
  const detailKeys = uniqueCandidateIds.map(
    (candidateId) => ["candidate-detail", candidateId] as const,
  );
  const pageQueries = queryClient
    .getQueryCache()
    .findAll({ queryKey: REVIEW_CANDIDATE_PAGE_QUERY_PREFIX });
  const newerQueries = queryClient
    .getQueryCache()
    .findAll({ queryKey: REVIEW_CANDIDATE_NEWER_QUERY_PREFIX });
  const activeNewerKeys = newerQueries
    .filter((query) => query.getObserversCount() > 0)
    .map((query) => query.queryKey);
  const detailQueries = detailKeys.flatMap((queryKey) => {
    const query = queryClient
      .getQueryCache()
      .find({ queryKey, exact: true });
    return query ? [query] : [];
  });
  const fetchingQueries = Array.from(
    new Map(
      [...pageQueries, ...newerQueries, ...detailQueries]
        .filter((query) => query.state.fetchStatus === "fetching")
        .map((query) => [query.queryHash, query]),
    ).values(),
  );
  await Promise.all(
    fetchingQueries.map((query) =>
      queryClient.cancelQueries({ queryKey: query.queryKey, exact: true }),
    ),
  );
  // 결과 불명/409는 서버에서 이미 처리됐을 수 있다. Infinity cache의 다른 filter
  // scope가 재진입 때 후보를 되살리지 않도록 전체를 stale로 만들고 active만 즉시 확인한다.
  await Promise.all([
    queryClient.invalidateQueries({
      queryKey: REVIEW_CANDIDATE_PAGE_QUERY_PREFIX,
      refetchType: "none",
    }),
    queryClient.invalidateQueries({
      queryKey: REVIEW_CANDIDATE_NEWER_QUERY_PREFIX,
      refetchType: "none",
    }),
  ]);
  const pageKeys = activePageKey
    ? [activePageKey]
    : queryClient
        .getQueryCache()
        .findAll({ queryKey: REVIEW_CANDIDATE_PAGE_QUERY_PREFIX })
        .filter((query) => query.getObserversCount() > 0)
        .map((query) => query.queryKey);
  const refreshKeys = Array.from(
    new Map(
      [...pageKeys, ...activeNewerKeys].map((queryKey) => [
        JSON.stringify(queryKey),
        queryKey,
      ]),
    ).values(),
  );
  const [refreshResults, detailEntries] = await Promise.all([
    Promise.allSettled(
      refreshKeys.map((queryKey) =>
        queryClient.refetchQueries({ queryKey, exact: true, type: "all" }),
      ),
    ),
    Promise.all(
      detailKeys.map(async (queryKey) => {
        const candidateId = queryKey[1];
        await queryClient.invalidateQueries({
          queryKey,
          exact: true,
          refetchType: "none",
        });
        try {
          const detail = await queryClient.fetchQuery({
            queryKey,
            staleTime: 0,
            retry: false,
            queryFn: async () => {
              const latest = await fetchCandidateDetail(candidateId);
              if (latest.list_item.id !== candidateId) {
                throw new Error("후보 상세 응답의 ID가 요청과 일치하지 않습니다.");
              }
              return latest;
            },
          });
          return [
            candidateId,
            { status: "success", detail } satisfies CandidateDetailRevalidation,
          ] as const;
        } catch (error) {
          return [
            candidateId,
            error instanceof ApiRequestError && error.status === 404
              ? ({ status: "not_found" } satisfies CandidateDetailRevalidation)
              : ({
                  status: "error",
                  error,
                } satisfies CandidateDetailRevalidation),
          ] as const;
        }
      }),
    ),
  ]);
  const candidateDetails = new Map<number, CandidateDetailRevalidation>(
    detailEntries,
  );
  const refreshFailed =
    refreshResults.some((result) => result.status === "rejected") ||
    refreshKeys.some(
      (queryKey) => queryClient.getQueryState(queryKey)?.status === "error",
    ) ||
    detailEntries.some(([, detail]) => detail.status === "error");
  // active exact 성공이 invalidation을 지운 뒤에도 inactive scope와 late navigation은
  // 반드시 서버를 다시 읽게 한다. refetchType:none이라 현재 화면의 중복 요청은 없다.
  await Promise.all([
    queryClient.invalidateQueries({
      queryKey: REVIEW_CANDIDATE_PAGE_QUERY_PREFIX,
      refetchType: "none",
    }),
    queryClient.invalidateQueries({
      queryKey: REVIEW_CANDIDATE_NEWER_QUERY_PREFIX,
      refetchType: "none",
    }),
  ]);
  return {
    refreshedQueryCount: refreshKeys.length + detailKeys.length,
    refreshFailed,
    candidateDetails,
  };
}

export function reviewCandidatePaginationContractError(
  pages: readonly ListEnvelope<UnmatchedCandidate>[],
): string | null {
  if (pages.length === 0) return null;
  const seenCursors = new Set<string>();
  for (const page of pages) {
    if (page.has_more && !page.next_cursor) {
      return "다음 후보 cursor가 없어 검수 큐의 끝을 확인할 수 없습니다.";
    }
    if (page.next_cursor) {
      if (seenCursors.has(page.next_cursor)) {
        return "동일한 다음 후보 cursor가 반복되어 검수 큐 진행을 중단했습니다.";
      }
      seenCursors.add(page.next_cursor);
    }
  }

  const lastPage = pages[pages.length - 1];
  const loadedUniqueCount = new Set(
    pages.flatMap((page) => page.items.map((candidate) => candidate.id)),
  ).size;
  if (!lastPage.has_more && lastPage.total > loadedUniqueCount) {
    return `서버는 ${lastPage.total}건을 알렸지만 ${loadedUniqueCount}건만 받아 검수 큐가 중간에 끊겼습니다.`;
  }
  return null;
}

export function reviewQueueProbeNotice({
  snapshotTotal,
  probeTotal,
  newerThan,
}: {
  snapshotTotal: number;
  probeTotal: number;
  newerThan: number;
}): string | null {
  if (probeTotal !== snapshotTotal) {
    return newerThan > 0
      ? `검수 큐가 변경됨 · 새 후보 ${newerThan}건 — 새로 불러오기`
      : "검수 큐가 변경됨 — 새로 불러오기";
  }
  return newerThan > 0 ? `새 후보 ${newerThan}건 — 불러오기` : null;
}

export type CandidateDeleteFailure = {
  id: number;
  reason: unknown;
};

export type CandidateDeleteBatchResult = {
  attemptedIds: number[];
  succeededIds: number[];
  failures: CandidateDeleteFailure[];
};

/** 일부 DELETE가 실패해도 성공/실패 ID를 잃지 않고 모두 수집한다. */
export async function settleCandidateDeletes(
  ids: readonly number[],
  deleteOne: (id: number) => Promise<unknown>,
): Promise<CandidateDeleteBatchResult> {
  const attemptedIds = Array.from(new Set(ids));
  const results = await Promise.allSettled(
    attemptedIds.map(async (id) => {
      await deleteOne(id);
      return id;
    }),
  );
  const succeededIds: number[] = [];
  const failures: CandidateDeleteFailure[] = [];
  results.forEach((result, index) => {
    const id = attemptedIds[index];
    if (result.status === "fulfilled") {
      succeededIds.push(result.value);
    } else {
      failures.push({ id, reason: result.reason });
    }
  });
  return { attemptedIds, succeededIds, failures };
}
