"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useReducer,
  useTransition,
} from "react";
import {
  useQuery,
  useQueryClient,
  type QueryClient,
} from "@tanstack/react-query";

import {
  getPlaceOpinion,
  searchPlaces,
  type PlaceOpinionResult,
  type PlaceSearchHit,
  type PlaceSearchResult,
} from "@/lib/api";
import { isPlaceHitStorageAllowed } from "@/lib/review-provenance";

export const CANDIDATE_SEARCH_DEBOUNCE_MS = 300;
export const CANDIDATE_PROVIDER_QUERY_ROOT = ["place-search"] as const;
export const CANDIDATE_OPINION_QUERY_ROOT = ["place-opinion"] as const;

/**
 * `requestIdentity`에는 queue scope/workflow 세대처럼 같은 candidate ID의 ABA를
 * 구분하는 값을 넣는다. 후보 선택 강조와 form 초기화는 이 hook 밖에서 먼저 처리한다.
 */
export type CandidateSearchIntent = {
  candidateId: number;
  requestIdentity: string;
  query: string;
};

export type CandidateSearchPending = CandidateSearchIntent & {
  generation: number;
};

export type CandidateSearchActivation = CandidateSearchPending & {
  searchNonce: number;
};

export type CandidateSearchState = {
  generation: number;
  searchNonce: number;
  pending: CandidateSearchPending | null;
  active: CandidateSearchActivation | null;
  opinionRequested: boolean;
};

export const INITIAL_CANDIDATE_SEARCH_STATE: CandidateSearchState = {
  generation: 0,
  searchNonce: 0,
  pending: null,
  active: null,
  opinionRequested: false,
};

export type CandidateSearchAction =
  | {
      type: "prepare_candidate";
      intent: CandidateSearchIntent | null;
      autoSearch: boolean;
      providerEnabled: boolean;
    }
  | {
      type: "run_manual";
      intent: CandidateSearchIntent;
      providerEnabled: boolean;
    }
  | { type: "activate_auto"; pending: CandidateSearchPending }
  | {
      type: "request_opinion";
      activation: CandidateSearchActivation;
      hitCount: number;
    }
  | { type: "stop" }
  | { type: "disable" };

export type CandidateProviderSearch = (
  query: string,
  signal?: AbortSignal,
) => Promise<PlaceSearchResult>;

export type CandidateOpinionSearch = (
  query: string,
  hits: PlaceSearchHit[],
  signal?: AbortSignal,
) => Promise<PlaceOpinionResult>;

export type CandidateProviderSearchResponse = {
  activation: CandidateSearchActivation;
  result: PlaceSearchResult;
};

export type CandidateOpinionSearchResponse = {
  activation: CandidateSearchActivation;
  hitsFingerprint: string;
  result: PlaceOpinionResult;
};

function normalizeCandidateSearchIntent(
  intent: CandidateSearchIntent | null,
): CandidateSearchIntent | null {
  if (
    intent == null ||
    !Number.isSafeInteger(intent.candidateId) ||
    intent.candidateId <= 0
  ) {
    return null;
  }
  const requestIdentity = intent.requestIdentity.trim();
  const query = intent.query.trim();
  if (!requestIdentity || !query) return null;
  return { candidateId: intent.candidateId, requestIdentity, query };
}

export function sameCandidateSearchActivation(
  left: CandidateSearchActivation | null,
  right: CandidateSearchActivation | null,
): boolean {
  return (
    left != null &&
    right != null &&
    left.candidateId === right.candidateId &&
    left.requestIdentity === right.requestIdentity &&
    left.query === right.query &&
    left.generation === right.generation &&
    left.searchNonce === right.searchNonce
  );
}

function sameCandidateSearchPending(
  left: CandidateSearchPending | null,
  right: CandidateSearchPending,
): boolean {
  return (
    left != null &&
    left.candidateId === right.candidateId &&
    left.requestIdentity === right.requestIdentity &&
    left.query === right.query &&
    left.generation === right.generation
  );
}

export function candidateSearchReducer(
  state: CandidateSearchState,
  action: CandidateSearchAction,
): CandidateSearchState {
  if (action.type === "prepare_candidate") {
    const generation = state.generation + 1;
    const intent = normalizeCandidateSearchIntent(action.intent);
    return {
      ...state,
      generation,
      pending:
        action.autoSearch && action.providerEnabled && intent
          ? { ...intent, generation }
          : null,
      active: null,
      opinionRequested: false,
    };
  }

  if (action.type === "run_manual") {
    const generation = state.generation + 1;
    const intent = normalizeCandidateSearchIntent(action.intent);
    if (!action.providerEnabled || !intent) {
      return {
        ...state,
        generation,
        pending: null,
        active: null,
        opinionRequested: false,
      };
    }
    const searchNonce = state.searchNonce + 1;
    return {
      ...state,
      generation,
      searchNonce,
      pending: null,
      active: { ...intent, generation, searchNonce },
      opinionRequested: false,
    };
  }

  if (action.type === "activate_auto") {
    if (!sameCandidateSearchPending(state.pending, action.pending)) return state;
    const searchNonce = state.searchNonce + 1;
    return {
      ...state,
      searchNonce,
      pending: null,
      active: { ...action.pending, searchNonce },
      opinionRequested: false,
    };
  }

  if (action.type === "request_opinion") {
    if (
      action.hitCount <= 0 ||
      !sameCandidateSearchActivation(state.active, action.activation)
    ) {
      return state;
    }
    return state.opinionRequested
      ? state
      : { ...state, opinionRequested: true };
  }

  return {
    ...state,
    generation: state.generation + 1,
    pending: null,
    active: null,
    opinionRequested: false,
  };
}

export function scheduleCandidateSearchActivation(
  pending: CandidateSearchPending,
  onElapsed: (pending: CandidateSearchPending) => void,
  delayMs = CANDIDATE_SEARCH_DEBOUNCE_MS,
): () => void {
  const safeDelay = Number.isFinite(delayMs)
    ? Math.max(0, delayMs)
    : CANDIDATE_SEARCH_DEBOUNCE_MS;
  const timer = globalThis.setTimeout(() => onElapsed(pending), safeDelay);
  return () => globalThis.clearTimeout(timer);
}

export function candidateProviderQueryEnabled(
  enabled: boolean,
  activation: CandidateSearchActivation | null,
): boolean {
  return enabled && activation != null && activation.query.length > 0;
}

export function candidateProviderQueryKey(
  activation: CandidateSearchActivation | null,
) {
  if (!activation) return [...CANDIDATE_PROVIDER_QUERY_ROOT, "inactive"] as const;
  return [
    ...CANDIDATE_PROVIDER_QUERY_ROOT,
    activation.candidateId,
    activation.requestIdentity,
    activation.generation,
    activation.query,
    activation.searchNonce,
  ] as const;
}

export async function runCandidateProviderSearch(
  activation: CandidateSearchActivation | null,
  enabled: boolean,
  search: CandidateProviderSearch,
  signal: AbortSignal,
): Promise<CandidateProviderSearchResponse | null> {
  if (!candidateProviderQueryEnabled(enabled, activation) || !activation) {
    return null;
  }
  const result = await search(activation.query, signal);
  return { activation, result };
}

export function candidateProviderResponseMatches(
  response: CandidateProviderSearchResponse | null | undefined,
  activation: CandidateSearchActivation | null,
): response is CandidateProviderSearchResponse {
  return Boolean(
    response &&
      sameCandidateSearchActivation(response.activation, activation) &&
      response.result.query.trim() === activation?.query,
  );
}

export function collectCandidateSearchHits(
  result: PlaceSearchResult | null | undefined,
  enabled: boolean,
): PlaceSearchHit[] {
  if (!enabled || !result) return [];
  return [...result.google, ...result.kakao, ...result.naver].filter(
    isPlaceHitStorageAllowed,
  );
}

export function candidateOpinionHitsFingerprint(
  hits: readonly PlaceSearchHit[],
): string {
  return JSON.stringify(
    hits.map((hit) => [
      hit.provider,
      hit.native_id,
      hit.name,
      hit.address,
      hit.road_address,
      hit.latitude,
      hit.longitude,
      hit.category,
      hit.storage_allowed,
      hit.storage_block_reason,
    ]),
  );
}

export function candidateOpinionQueryEnabled(
  enabled: boolean,
  activation: CandidateSearchActivation | null,
  opinionRequested: boolean,
  hits: readonly PlaceSearchHit[],
): boolean {
  return (
    candidateProviderQueryEnabled(enabled, activation) &&
    opinionRequested &&
    hits.length > 0
  );
}

export function candidateOpinionQueryKey(
  activation: CandidateSearchActivation | null,
  hits: readonly PlaceSearchHit[],
) {
  if (!activation) return [...CANDIDATE_OPINION_QUERY_ROOT, "inactive"] as const;
  return [
    ...CANDIDATE_OPINION_QUERY_ROOT,
    activation.candidateId,
    activation.requestIdentity,
    activation.generation,
    activation.query,
    activation.searchNonce,
    candidateOpinionHitsFingerprint(hits),
  ] as const;
}

export async function runCandidateOpinionSearch(
  activation: CandidateSearchActivation | null,
  enabled: boolean,
  opinionRequested: boolean,
  hits: PlaceSearchHit[],
  search: CandidateOpinionSearch,
  signal: AbortSignal,
): Promise<CandidateOpinionSearchResponse | null> {
  if (
    !candidateOpinionQueryEnabled(
      enabled,
      activation,
      opinionRequested,
      hits,
    ) ||
    !activation
  ) {
    return null;
  }
  const hitsFingerprint = candidateOpinionHitsFingerprint(hits);
  const result = await search(activation.query, hits, signal);
  return { activation, hitsFingerprint, result };
}

export function candidateOpinionResponseMatches(
  response: CandidateOpinionSearchResponse | null | undefined,
  activation: CandidateSearchActivation | null,
  hits: readonly PlaceSearchHit[],
): response is CandidateOpinionSearchResponse {
  return Boolean(
    response &&
      sameCandidateSearchActivation(response.activation, activation) &&
      response.hitsFingerprint === candidateOpinionHitsFingerprint(hits),
  );
}

export function cancelCandidateSearchQueries(
  queryClient: Pick<QueryClient, "cancelQueries" | "removeQueries">,
  remove: boolean,
): void {
  void queryClient.cancelQueries({ queryKey: CANDIDATE_PROVIDER_QUERY_ROOT });
  void queryClient.cancelQueries({ queryKey: CANDIDATE_OPINION_QUERY_ROOT });
  if (!remove) return;
  queryClient.removeQueries({ queryKey: CANDIDATE_PROVIDER_QUERY_ROOT });
  queryClient.removeQueries({ queryKey: CANDIDATE_OPINION_QUERY_ROOT });
}

export type PrepareCandidateSearchOptions = {
  /** false면 이전 intent만 폐기하고 자동 provider 요청은 만들지 않는다. */
  autoSearch?: boolean;
  /** removed/non-actionable 후보는 반드시 false를 넘겨 같은 event 안에서도 차단한다. */
  providerEnabled?: boolean;
};

export type UseCandidateSearchOptions = {
  /** removed 또는 non-actionable 화면이면 false다. 모든 query의 최종 차단선이다. */
  enabled: boolean;
  debounceMs?: number;
  searchProviders?: CandidateProviderSearch;
  searchOpinion?: CandidateOpinionSearch;
};

export function useCandidateSearch({
  enabled,
  debounceMs = CANDIDATE_SEARCH_DEBOUNCE_MS,
  searchProviders = searchPlaces,
  searchOpinion = getPlaceOpinion,
}: UseCandidateSearchOptions) {
  const queryClient = useQueryClient();
  const [state, dispatch] = useReducer(
    candidateSearchReducer,
    INITIAL_CANDIDATE_SEARCH_STATE,
  );
  const [isProviderActivationPending, startProviderActivationTransition] =
    useTransition();

  const cancelRequests = useCallback(
    (remove: boolean) => {
      cancelCandidateSearchQueries(queryClient, remove);
    },
    [queryClient],
  );

  const prepareCandidate = useCallback(
    (
      intent: CandidateSearchIntent | null,
      options: PrepareCandidateSearchOptions = {},
    ) => {
      // 후보 강조/form 초기화는 호출자가 이미 urgent state로 반영한 뒤 이 API를 부른다.
      // 여기서는 이전 provider 요청을 끊고 debounce intent만 준비한다.
      cancelRequests(false);
      dispatch({
        type: "prepare_candidate",
        intent,
        autoSearch: options.autoSearch ?? true,
        // 후보 선택 event에서는 hook의 enabled가 직전 render 값일 수 있다. 호출자가
        // 새 후보의 최신 상태로 명시한 값이 있으면 그 값을 우선하고, 최종 query는
        // 다음 render의 enabled가 다시 차단한다.
        providerEnabled: options.providerEnabled ?? enabled,
      });
    },
    [cancelRequests, enabled],
  );

  const runSearch = useCallback(
    (intent: CandidateSearchIntent) => {
      cancelRequests(false);
      dispatch({ type: "run_manual", intent, providerEnabled: enabled });
    },
    [cancelRequests, enabled],
  );

  const stopSearch = useCallback(() => {
    // cancelQueries의 TanStack Query AbortSignal이 BFF/upstream까지 전파된다.
    // cache도 함께 지워 동일 문자열 수동 재실행이 항상 새 nonce/request가 되게 한다.
    cancelRequests(true);
    dispatch({ type: "stop" });
  }, [cancelRequests]);

  useEffect(() => {
    const pending = state.pending;
    if (!pending) return;
    return scheduleCandidateSearchActivation(
      pending,
      (elapsed) => {
        // 후보 선택 강조/form 초기화는 transition 대상이 아니다. 300ms debounce가
        // 끝난 provider query 활성화만 낮은 우선순위로 전환한다.
        startProviderActivationTransition(() => {
          dispatch({ type: "activate_auto", pending: elapsed });
        });
      },
      debounceMs,
    );
  }, [debounceMs, startProviderActivationTransition, state.pending]);

  useEffect(() => {
    if (enabled) return;
    cancelRequests(true);
    dispatch({ type: "disable" });
  }, [cancelRequests, enabled]);

  useEffect(
    () => () => {
      cancelRequests(false);
    },
    [cancelRequests],
  );

  const active = state.active;
  const providerEnabled = candidateProviderQueryEnabled(enabled, active);
  const searchQuery = useQuery({
    queryKey: candidateProviderQueryKey(active),
    queryFn: ({ signal }) =>
      runCandidateProviderSearch(active, enabled, searchProviders, signal),
    enabled: providerEnabled,
  });
  const providerResponse = searchQuery.data;
  const result = candidateProviderResponseMatches(providerResponse, active)
    ? providerResponse.result
    : null;
  const allHits = useMemo(
    () => collectCandidateSearchHits(result, providerEnabled),
    [providerEnabled, result],
  );

  const requestOpinion = useCallback((): boolean => {
    if (!active || !enabled || allHits.length === 0) return false;
    dispatch({
      type: "request_opinion",
      activation: active,
      hitCount: allHits.length,
    });
    return true;
  }, [active, allHits.length, enabled]);

  const opinionEnabled = candidateOpinionQueryEnabled(
    enabled,
    active,
    state.opinionRequested,
    allHits,
  );
  const opinionQuery = useQuery({
    queryKey: candidateOpinionQueryKey(active, allHits),
    queryFn: ({ signal }) =>
      runCandidateOpinionSearch(
        active,
        enabled,
        state.opinionRequested,
        allHits,
        searchOpinion,
        signal,
      ),
    enabled: opinionEnabled,
  });
  const currentOpinionResponse = opinionQuery.data;
  const opinionResult = candidateOpinionResponseMatches(
    currentOpinionResponse,
    active,
    allHits,
  )
    ? currentOpinionResponse.result
    : null;

  return {
    state,
    activeQuery: active?.query ?? "",
    searchNonce: state.searchNonce,
    autoSearchPending: state.pending != null,
    isProviderActivationPending,
    searchQuery,
    result,
    allHits,
    opinionRequested: state.opinionRequested,
    opinionQuery,
    opinionResult,
    gemini: opinionResult?.gemini ?? null,
    prepareCandidate,
    runSearch,
    stopSearch,
    requestOpinion,
  };
}
