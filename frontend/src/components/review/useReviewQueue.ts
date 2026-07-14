"use client";

import { useSearchParams } from "next/navigation";
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useSyncExternalStore,
} from "react";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";

import {
  listDestinationFacets,
  listUnmatchedCandidatesPage,
  type DestinationGroupDim,
  type ReviewGroundingStatus,
  type ReviewQueueReason,
  type ReviewSourceKind,
  type UnmatchedCandidate,
} from "@/lib/api";
import {
  reviewCandidatePaginationContractError,
  reviewQueueProbeNotice,
} from "@/lib/review-candidate-cache";
import {
  applyReviewListStatePatch,
  DEFAULT_REVIEW_LIST_STATE,
  hasReviewListStateParams,
  parseReviewListState,
  reviewListStateHasFilters,
  reviewListStateScopeKey,
  reviewListStateToFilter,
  writeReviewListState,
  type ReviewListState,
} from "@/lib/review-list-state";

const INITIAL_REVIEW_CANDIDATE_LIMIT = 300;
const REVIEW_URL_CHANGE_EVENT = "ktc:review-url-change";

export type ReviewCandidatesKey = readonly [
  "unmatched-candidates",
  "pages",
  DestinationGroupDim,
  string | null,
  string,
  "newest" | "oldest",
  boolean | null,
  ReviewQueueReason | null,
  ReviewSourceKind | null,
  ReviewGroundingStatus | null,
  "needs_review" | "removed",
];

function subscribeReviewUrl(onStoreChange: () => void): () => void {
  window.addEventListener("popstate", onStoreChange);
  window.addEventListener(REVIEW_URL_CHANGE_EVENT, onStoreChange);
  return () => {
    window.removeEventListener("popstate", onStoreChange);
    window.removeEventListener(REVIEW_URL_CHANGE_EVENT, onStoreChange);
  };
}

function getReviewUrlSnapshot(): string {
  return window.location.search.slice(1);
}

export function useReviewQueue() {
  const searchParams = useSearchParams();
  const searchString = searchParams.toString();
  const getReviewServerSnapshot = useCallback(
    () => searchString,
    [searchString],
  );
  // native History patch와 back/forward를 외부 store로 구독해 목록 요청과 deep-link
  // 판정이 언제나 실제 browser URL의 같은 snapshot을 읽게 한다.
  const reviewUrlSnapshot = useSyncExternalStore(
    subscribeReviewUrl,
    getReviewUrlSnapshot,
    getReviewServerSnapshot,
  );
  const reviewSearchParams = useMemo(
    () => new URLSearchParams(reviewUrlSnapshot),
    [reviewUrlSnapshot],
  );
  const hasListUrlState = hasReviewListStateParams(reviewSearchParams);
  const reviewListState = useMemo(
    () => parseReviewListState(reviewSearchParams),
    [reviewSearchParams],
  );
  const {
    groupDim,
    groupValue,
    query: reviewQuery,
    sort: reviewSort,
    isDomestic,
    queueReason,
    sourceKind,
    groundingStatus,
    status: reviewStatus,
  } = reviewListState;
  const isRemovedView = reviewStatus === "removed";
  const hasReviewFilters = reviewListStateHasFilters({
    ...reviewListState,
    status: "needs_review",
  });
  const initialUrlNormalizationRef = useRef(false);
  const commitReviewUrl = useCallback((params: URLSearchParams) => {
    const url = new URL(window.location.href);
    url.search = params.toString();
    const next = `${url.pathname}${url.search}${url.hash}`;
    const current = `${window.location.pathname}${window.location.search}${window.location.hash}`;
    if (next === current) return;
    window.history.replaceState(window.history.state, "", next);
    window.dispatchEvent(new Event(REVIEW_URL_CHANGE_EVENT));
  }, []);

  const updateReviewListState = useCallback(
    (patch: Partial<ReviewListState>) => {
      const current = new URL(window.location.href);
      const optimistic = applyReviewListStatePatch(
        current.searchParams,
        parseReviewListState(current.searchParams),
        patch,
      );
      commitReviewUrl(optimistic.params);
    },
    [commitReviewUrl],
  );
  const updateReviewQuery = useCallback(
    (query: string) => updateReviewListState({ query }),
    [updateReviewListState],
  );

  // URL에 목록 상태가 전혀 없는 최초 진입에서만 sessionStorage를 기본값으로 승격한다.
  // 이후에는 sort가 항상 URL에 남으므로 URL이 유일한 정본이다.
  useEffect(() => {
    const current = new URL(window.location.href);
    if (hasReviewListStateParams(current.searchParams)) {
      initialUrlNormalizationRef.current = false;
      const canonical = writeReviewListState(
        current.searchParams,
        parseReviewListState(current.searchParams),
      );
      if (canonical.toString() !== current.searchParams.toString()) {
        commitReviewUrl(canonical);
      }
      return;
    }
    if (initialUrlNormalizationRef.current) return;
    initialUrlNormalizationRef.current = true;

    let initial = DEFAULT_REVIEW_LIST_STATE;
    try {
      const stored = window.sessionStorage.getItem("ktc.review.listSearch");
      if (stored) {
        initial = parseReviewListState(new URLSearchParams(stored));
      } else {
        const legacyDim = JSON.parse(
          window.sessionStorage.getItem("ktc.review.groupDim") ?? '"none"',
        ) as unknown;
        const legacyValue = JSON.parse(
          window.sessionStorage.getItem("ktc.review.groupValue") ?? "null",
        ) as unknown;
        const legacyParams = new URLSearchParams({ sort: "oldest" });
        if (typeof legacyDim === "string") legacyParams.set("group", legacyDim);
        if (typeof legacyValue === "string") {
          legacyParams.set("group_value", legacyValue);
        }
        initial = parseReviewListState(legacyParams);
      }
    } catch {
      initial = DEFAULT_REVIEW_LIST_STATE;
    }
    commitReviewUrl(writeReviewListState(current.searchParams, initial));
  }, [commitReviewUrl, searchString]);

  useEffect(() => {
    if (!hasListUrlState) return;
    try {
      const persisted = writeReviewListState(
        new URLSearchParams(),
        reviewListState,
      );
      window.sessionStorage.setItem("ktc.review.listSearch", persisted.toString());
    } catch {
      // sessionStorage 비활성/용량 초과는 URL 정본 동작에 영향을 주지 않는다.
    }
  }, [hasListUrlState, reviewListState]);

  const facetsQuery = useQuery({
    queryKey: ["destination-facets"],
    queryFn: listDestinationFacets,
    staleTime: 10 * 60 * 1000,
    refetchInterval: 10 * 60 * 1000,
  });
  const filter = useMemo(
    () => reviewListStateToFilter(reviewListState),
    [reviewListState],
  );
  const candidatesKey = useMemo<ReviewCandidatesKey>(
    () => [
      "unmatched-candidates",
      "pages",
      groupDim,
      groupValue,
      reviewQuery,
      reviewSort,
      isDomestic,
      queueReason,
      sourceKind,
      groundingStatus,
      reviewStatus,
    ],
    [
      groupDim,
      groupValue,
      groundingStatus,
      isDomestic,
      queueReason,
      reviewQuery,
      reviewSort,
      reviewStatus,
      sourceKind,
    ],
  );
  const candidatesQuery = useInfiniteQuery({
    queryKey: candidatesKey,
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) =>
      listUnmatchedCandidatesPage(filter, {
        limit: INITIAL_REVIEW_CANDIDATE_LIMIT,
        cursor: pageParam,
      }),
    getNextPageParam: (lastPage) =>
      lastPage.has_more ? (lastPage.next_cursor ?? undefined) : undefined,
    enabled: hasListUrlState,
    staleTime: Infinity,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });
  const candidates = useMemo(() => {
    const orderedIds: number[] = [];
    const latestById = new Map<number, UnmatchedCandidate>();
    for (const page of candidatesQuery.data?.pages ?? []) {
      for (const candidate of page.items) {
        if (!latestById.has(candidate.id)) orderedIds.push(candidate.id);
        latestById.set(candidate.id, candidate);
      }
    }
    return orderedIds.flatMap((candidateId) => {
      const candidate = latestById.get(candidateId);
      return candidate ? [candidate] : [];
    });
  }, [candidatesQuery.data]);
  const candidatePages = useMemo(
    () => candidatesQuery.data?.pages ?? [],
    [candidatesQuery.data?.pages],
  );
  const firstCandidatePage = candidatePages[0];
  const candidatePaginationContractError =
    reviewCandidatePaginationContractError(candidatePages);
  const canLoadMoreCandidates =
    Boolean(candidatesQuery.hasNextPage) && !candidatePaginationContractError;
  const candidateTotal = firstCandidatePage?.total ?? 0;
  const candidateNewestId = firstCandidatePage?.newest_id ?? 0;
  const newCandidatesQuery = useQuery({
    queryKey: [
      "unmatched-candidates",
      "newer",
      groupDim,
      groupValue,
      reviewQuery,
      reviewSort,
      isDomestic,
      queueReason,
      sourceKind,
      groundingStatus,
      reviewStatus,
      candidateNewestId,
    ],
    queryFn: () =>
      listUnmatchedCandidatesPage(filter, {
        limit: 1,
        newerThanId: candidateNewestId,
      }),
    enabled: hasListUrlState && firstCandidatePage != null,
    staleTime: 60_000,
    refetchInterval: 60_000,
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: false,
  });
  const newCandidateCount = newCandidatesQuery.data?.newer_than ?? 0;
  const newCandidateNotice = newCandidatesQuery.data
    ? reviewQueueProbeNotice({
        snapshotTotal: candidateTotal,
        probeTotal: newCandidatesQuery.data.total,
        newerThan: newCandidateCount,
      })
    : null;
  const queueScope = useMemo(
    () => reviewListStateScopeKey(reviewListState),
    [reviewListState],
  );
  const queueScopeRef = useRef(queueScope);
  const reviewListStateRef = useRef(reviewListState);
  const candidatesKeyRef = useRef<ReviewCandidatesKey>(candidatesKey);
  useLayoutEffect(() => {
    queueScopeRef.current = queueScope;
    reviewListStateRef.current = reviewListState;
    candidatesKeyRef.current = candidatesKey;
  }, [candidatesKey, queueScope, reviewListState]);

  return {
    candidates,
    candidatePages,
    candidatePaginationContractError,
    candidatesKey,
    candidatesKeyRef,
    candidatesQuery,
    candidateTotal,
    canLoadMoreCandidates,
    commitReviewUrl,
    facetsQuery,
    filter,
    groundingStatus,
    groupDim,
    groupValue,
    hasListUrlState,
    hasReviewFilters,
    isDomestic,
    isRemovedView,
    newCandidateCount,
    newCandidateNotice,
    newCandidatesQuery,
    queueReason,
    queueScope,
    queueScopeRef,
    reviewListState,
    reviewListStateRef,
    reviewQuery,
    reviewSearchParams,
    reviewSort,
    reviewStatus,
    sourceKind,
    updateReviewListState,
    updateReviewQuery,
  };
}
