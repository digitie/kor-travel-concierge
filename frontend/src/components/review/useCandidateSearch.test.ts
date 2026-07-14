import { afterEach, describe, expect, it, vi } from "vitest";
import { QueryClient } from "@tanstack/react-query";

import type {
  PlaceSearchHit,
  PlaceSearchResult,
} from "@/lib/api";
import {
  CANDIDATE_OPINION_QUERY_ROOT,
  CANDIDATE_PROVIDER_QUERY_ROOT,
  CANDIDATE_SEARCH_DEBOUNCE_MS,
  INITIAL_CANDIDATE_SEARCH_STATE,
  cancelCandidateSearchQueries,
  candidateOpinionQueryEnabled,
  candidateOpinionQueryKey,
  candidateOpinionResponseMatches,
  candidateProviderQueryEnabled,
  candidateProviderQueryKey,
  candidateProviderResponseMatches,
  candidateSearchReducer,
  collectCandidateSearchHits,
  runCandidateOpinionSearch,
  runCandidateProviderSearch,
  scheduleCandidateSearchActivation,
  type CandidateSearchActivation,
  type CandidateSearchIntent,
  type CandidateSearchState,
} from "./useCandidateSearch";

function intent(
  candidateId: number,
  requestIdentity: string,
  query: string,
): CandidateSearchIntent {
  return { candidateId, requestIdentity, query };
}

function prepare(
  state: CandidateSearchState,
  value: CandidateSearchIntent,
  providerEnabled = true,
): CandidateSearchState {
  return candidateSearchReducer(state, {
    type: "prepare_candidate",
    intent: value,
    autoSearch: true,
    providerEnabled,
  });
}

function runManual(
  state: CandidateSearchState,
  value: CandidateSearchIntent,
  providerEnabled = true,
): CandidateSearchState {
  return candidateSearchReducer(state, {
    type: "run_manual",
    intent: value,
    providerEnabled,
  });
}

function activeFrom(
  value: CandidateSearchIntent = intent(1, "candidate-a", "제주 카페"),
): CandidateSearchActivation {
  const state = runManual(INITIAL_CANDIDATE_SEARCH_STATE, value);
  if (!state.active) throw new Error("수동 검색 activation 생성 실패");
  return state.active;
}

function hit(
  provider: PlaceSearchHit["provider"],
  name: string,
  storageAllowed = true,
): PlaceSearchHit {
  return {
    provider,
    native_id: `${provider}-${name}`,
    name,
    address: `${name} 지번 주소`,
    road_address: `${name} 도로명 주소`,
    latitude: 33.5,
    longitude: 126.5,
    category: "카페",
    storage_allowed: storageAllowed,
    storage_block_reason: storageAllowed ? null : "provider_policy",
  };
}

function providerResult(
  overrides: Partial<PlaceSearchResult> = {},
): PlaceSearchResult {
  return {
    query: "제주 카페",
    searched_at: "2026-07-14T12:00:00Z",
    google: [],
    kakao: [],
    naver: [],
    errors: {},
    ...overrides,
  };
}

afterEach(() => {
  vi.useRealTimers();
});

describe("후보 provider 검색 debounce와 identity fencing", () => {
  it("자동 검색은 정확히 300ms 뒤 activation을 전달한다", () => {
    vi.useFakeTimers();
    const state = prepare(
      INITIAL_CANDIDATE_SEARCH_STATE,
      intent(1, "candidate-a", " 제주 카페 "),
    );
    if (!state.pending) throw new Error("pending intent 생성 실패");
    const onElapsed = vi.fn();

    scheduleCandidateSearchActivation(state.pending, onElapsed);
    vi.advanceTimersByTime(CANDIDATE_SEARCH_DEBOUNCE_MS - 1);
    expect(onElapsed).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1);

    expect(onElapsed).toHaveBeenCalledOnce();
    expect(onElapsed).toHaveBeenCalledWith(
      expect.objectContaining({ query: "제주 카페", generation: 1 }),
    );
  });

  it("A→B에서 늦은 A timer는 B provider query를 활성화하지 못한다", () => {
    let state = prepare(
      INITIAL_CANDIDATE_SEARCH_STATE,
      intent(1, "candidate-a", "검색 A"),
    );
    const pendingA = state.pending;
    if (!pendingA) throw new Error("A pending 생성 실패");
    state = prepare(state, intent(2, "candidate-b", "검색 B"));
    const pendingB = state.pending;
    if (!pendingB) throw new Error("B pending 생성 실패");

    const beforeStaleA = state;
    state = candidateSearchReducer(state, {
      type: "activate_auto",
      pending: pendingA,
    });
    expect(state).toBe(beforeStaleA);
    expect(state.active).toBeNull();

    state = candidateSearchReducer(state, {
      type: "activate_auto",
      pending: pendingB,
    });
    expect(state.active).toMatchObject({
      candidateId: 2,
      requestIdentity: "candidate-b",
      query: "검색 B",
      generation: 2,
      searchNonce: 1,
    });
  });

  it("A→B→A에서 첫 A와 B timer를 모두 버리고 마지막 A 세대만 쓴다", () => {
    let state = prepare(
      INITIAL_CANDIDATE_SEARCH_STATE,
      intent(1, "candidate-a", "검색 A"),
    );
    const firstA = state.pending;
    if (!firstA) throw new Error("첫 A pending 생성 실패");
    state = prepare(state, intent(2, "candidate-b", "검색 B"));
    const middleB = state.pending;
    if (!middleB) throw new Error("B pending 생성 실패");
    state = prepare(state, intent(1, "candidate-a", "검색 A"));
    const latestA = state.pending;
    if (!latestA) throw new Error("마지막 A pending 생성 실패");

    const current = state;
    expect(
      candidateSearchReducer(current, {
        type: "activate_auto",
        pending: firstA,
      }),
    ).toBe(current);
    expect(
      candidateSearchReducer(current, {
        type: "activate_auto",
        pending: middleB,
      }),
    ).toBe(current);

    state = candidateSearchReducer(current, {
      type: "activate_auto",
      pending: latestA,
    });
    expect(state.active).toMatchObject({
      candidateId: 1,
      requestIdentity: "candidate-a",
      generation: 3,
      searchNonce: 1,
    });
  });

  it("동일 문자열 수동 재실행도 nonce와 query key가 달라진다", () => {
    const searchIntent = intent(1, "candidate-a", "제주 카페");
    const first = runManual(INITIAL_CANDIDATE_SEARCH_STATE, searchIntent);
    if (!first.active) throw new Error("첫 수동 activation 생성 실패");
    const second = runManual(first, searchIntent);
    if (!second.active) throw new Error("두 번째 수동 activation 생성 실패");

    expect(first.active.query).toBe(second.active.query);
    expect(first.active.searchNonce).toBe(1);
    expect(second.active.searchNonce).toBe(2);
    expect(candidateProviderQueryKey(first.active)).not.toEqual(
      candidateProviderQueryKey(second.active),
    );
  });
});

describe("검색 중지, AbortSignal, removed 차단", () => {
  it("직전 render가 disabled여도 새 actionable 후보의 명시적 intent는 준비한다", () => {
    const state = candidateSearchReducer(INITIAL_CANDIDATE_SEARCH_STATE, {
      type: "prepare_candidate",
      intent: intent(1, "candidate-a", "검색 A"),
      autoSearch: true,
      providerEnabled: true,
    });

    expect(state.pending).toMatchObject({
      candidateId: 1,
      requestIdentity: "candidate-a",
      query: "검색 A",
    });
  });

  it("stop은 pending을 폐기하고 이미 큐에 든 timer action도 무시한다", () => {
    let state = prepare(
      INITIAL_CANDIDATE_SEARCH_STATE,
      intent(1, "candidate-a", "검색 A"),
    );
    const pending = state.pending;
    if (!pending) throw new Error("pending 생성 실패");
    state = candidateSearchReducer(state, { type: "stop" });
    const stopped = state;

    state = candidateSearchReducer(state, {
      type: "activate_auto",
      pending,
    });
    expect(state).toBe(stopped);
    expect(state.pending).toBeNull();
    expect(state.active).toBeNull();
  });

  it("debounce 취소 함수는 timer callback을 호출하지 않는다", () => {
    vi.useFakeTimers();
    const state = prepare(
      INITIAL_CANDIDATE_SEARCH_STATE,
      intent(1, "candidate-a", "검색 A"),
    );
    if (!state.pending) throw new Error("pending 생성 실패");
    const onElapsed = vi.fn();
    const cancel = scheduleCandidateSearchActivation(state.pending, onElapsed);

    cancel();
    vi.advanceTimersByTime(CANDIDATE_SEARCH_DEBOUNCE_MS);
    expect(onElapsed).not.toHaveBeenCalled();
  });

  it("TanStack Query가 준 AbortSignal을 provider까지 그대로 전달한다", async () => {
    const activation = activeFrom();
    const controller = new AbortController();
    const search = vi.fn(
      (_query: string, signal?: AbortSignal) =>
        new Promise<PlaceSearchResult>((_resolve, reject) => {
          signal?.addEventListener(
            "abort",
            () => {
              const error = new Error("provider 요청 취소");
              error.name = "AbortError";
              reject(error);
            },
            { once: true },
          );
        }),
    );

    const request = runCandidateProviderSearch(
      activation,
      true,
      search,
      controller.signal,
    );
    expect(search).toHaveBeenCalledWith("제주 카페", controller.signal);
    controller.abort();

    await expect(request).rejects.toMatchObject({ name: "AbortError" });
  });

  it("removed/disabled는 pending·active·hits를 비우고 provider를 0회 호출한다", async () => {
    const searchIntent = intent(1, "removed-a", "제주 카페");
    const prepared = prepare(
      INITIAL_CANDIDATE_SEARCH_STATE,
      searchIntent,
      false,
    );
    expect(prepared.pending).toBeNull();
    expect(prepared.active).toBeNull();

    const activation = activeFrom(searchIntent);
    const provider = vi.fn(async () => providerResult());
    const response = await runCandidateProviderSearch(
      activation,
      false,
      provider,
      new AbortController().signal,
    );

    expect(response).toBeNull();
    expect(provider).not.toHaveBeenCalled();
    expect(candidateProviderQueryEnabled(false, activation)).toBe(false);
    expect(collectCandidateSearchHits(providerResult(), false)).toEqual([]);
  });

  it("중지는 provider/opinion query root를 취소하고 cache를 제거한다", () => {
    const client = new QueryClient();
    const providerKey = [...CANDIDATE_PROVIDER_QUERY_ROOT, "cached"];
    const opinionKey = [...CANDIDATE_OPINION_QUERY_ROOT, "cached"];
    client.setQueryData(providerKey, { cached: true });
    client.setQueryData(opinionKey, { cached: true });

    cancelCandidateSearchQueries(client, true);

    expect(client.getQueryData(providerKey)).toBeUndefined();
    expect(client.getQueryData(opinionKey)).toBeUndefined();
  });
});

describe("provider response와 Gemini opinion 결합", () => {
  it("후보/request 세대가 다른 provider 응답을 현재 결과로 채택하지 않는다", async () => {
    const firstActivation = activeFrom(
      intent(1, "candidate-a", "제주 카페"),
    );
    const provider = vi.fn(async () => providerResult());
    const response = await runCandidateProviderSearch(
      firstActivation,
      true,
      provider,
      new AbortController().signal,
    );
    const nextState = runManual(
      {
        ...INITIAL_CANDIDATE_SEARCH_STATE,
        generation: firstActivation.generation,
        searchNonce: firstActivation.searchNonce,
        active: firstActivation,
      },
      intent(2, "candidate-b", "제주 카페"),
    );

    expect(candidateProviderResponseMatches(response, firstActivation)).toBe(
      true,
    );
    expect(candidateProviderResponseMatches(response, nextState.active)).toBe(
      false,
    );
  });

  it("저장 허용 allHits만 exact fingerprint로 opinion 요청에 결합한다(Google은 저장 정책상 제외)", async () => {
    const allowedGoogle = hit("google", "허용 Google");
    const blockedKakao = hit("kakao", "차단 Kakao", false);
    const allowedNaver = hit("naver", "허용 Naver");
    const result = providerResult({
      google: [allowedGoogle],
      kakao: [blockedKakao],
      naver: [allowedNaver],
    });
    const allHits = collectCandidateSearchHits(result, true);
    // isPlaceHitStorageAllowed(storage_allowed && provider!=="google")로 Google은
    // storage_allowed=true여도 저장 정책상 제외된다(origin/main page.tsx allHits 보존).
    expect(allHits).toEqual([allowedNaver]);

    let state = runManual(
      INITIAL_CANDIDATE_SEARCH_STATE,
      intent(1, "candidate-a", "제주 카페"),
    );
    if (!state.active) throw new Error("opinion activation 생성 실패");
    state = candidateSearchReducer(state, {
      type: "request_opinion",
      activation: state.active,
      hitCount: allHits.length,
    });
    expect(state.opinionRequested).toBe(true);
    expect(
      candidateOpinionQueryEnabled(
        true,
        state.active,
        state.opinionRequested,
        allHits,
      ),
    ).toBe(true);

    const opinion = vi.fn(async () => ({
      gemini: { best_name: "허용 Google" },
      error: null,
    }));
    const signal = new AbortController().signal;
    const response = await runCandidateOpinionSearch(
      state.active,
      true,
      state.opinionRequested,
      allHits,
      opinion,
      signal,
    );

    expect(opinion).toHaveBeenCalledWith("제주 카페", allHits, signal);
    expect(candidateOpinionResponseMatches(response, state.active, allHits)).toBe(
      true,
    );
    expect(
      candidateOpinionResponseMatches(response, state.active, [allowedGoogle]),
    ).toBe(false);
    expect(candidateOpinionQueryKey(state.active, allHits).at(-1)).not.toBe(
      candidateOpinionQueryKey(state.active, [allowedGoogle]).at(-1),
    );
  });

  it("hit 0건이면 opinionRequested를 올리지 않고 opinion provider도 호출하지 않는다", async () => {
    let state = runManual(
      INITIAL_CANDIDATE_SEARCH_STATE,
      intent(1, "candidate-a", "제주 카페"),
    );
    if (!state.active) throw new Error("opinion activation 생성 실패");
    const before = state;
    state = candidateSearchReducer(state, {
      type: "request_opinion",
      activation: state.active,
      hitCount: 0,
    });
    expect(state).toBe(before);

    const opinion = vi.fn(async () => ({ gemini: null, error: null }));
    const response = await runCandidateOpinionSearch(
      state.active,
      true,
      state.opinionRequested,
      [],
      opinion,
      new AbortController().signal,
    );
    expect(response).toBeNull();
    expect(opinion).not.toHaveBeenCalled();
  });
});
