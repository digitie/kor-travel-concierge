import type { UnmatchedCandidate } from "@/lib/api";
import type { SelectedPlaceHit } from "@/lib/review-provenance";
import type { SetStateAction } from "react";
import { createStore } from "zustand/vanilla";

export type ReviewFormState = {
  name: string;
  latitude: string;
  longitude: string;
  category: string;
  categoryCode: string;
};
type ReviewUiState<Advance, Conflict> = {
  selectedId: number | null;
  selectedCandidateSnapshot: UnmatchedCandidate | null;
  deepLinkValidationPending: boolean;
  deepLinkNotFound: string | null;
  pendingCandidateAdvance: Advance | null;
  queueCompleted: boolean;
  candidateActionError: string | null;
  selectedCandidateIds: number[];
  queryEdit: string | null;
  form: ReviewFormState;
  formCandidateId: number | null;
  categoryEdited: boolean;
  selectedHit: SelectedPlaceHit | null;
  nearbyConflict: Conflict | null;
};

/** 화면 인스턴스 전용 UI 상태. ref 기반 요청 fencing과 서버 캐시는 이 store에 넣지 않는다. */
export function createReviewUiStore<Advance, Conflict>() {
  type State = ReviewUiState<Advance, Conflict>;
  const store = createStore<State>(() => ({
    selectedId: null,
    selectedCandidateSnapshot: null,
    deepLinkValidationPending: false,
    deepLinkNotFound: null,
    pendingCandidateAdvance: null,
    queueCompleted: false,
    candidateActionError: null,
    selectedCandidateIds: [],
    queryEdit: null,
    form: {
      name: "",
      latitude: "",
      longitude: "",
      category: "",
      categoryCode: "",
    },
    formCandidateId: null,
    categoryEdited: false,
    selectedHit: null,
    nearbyConflict: null,
  }));
  let depth = 0;
  let pending: Partial<State> | null = null;
  function setter<K extends keyof State>(key: K) {
    return (action: SetStateAction<State[K]>) => {
      const current = { ...store.getState(), ...pending }[key];
      const value =
        typeof action === "function"
          ? (action as (previous: State[K]) => State[K])(current)
          : action;
      if (Object.is(current, value)) return;
      const patch = { [key]: value } as Pick<State, K>;
      if (depth) pending = { ...pending, ...patch };
      else store.setState(patch);
    };
  }
  function batch<T>(work: () => T): T {
    depth++;
    try {
      return work();
    } finally {
      depth--;
      if (!depth && pending) {
        const patch = pending;
        pending = null;
        store.setState(patch);
      }
    }
  }
  return {
    store,
    batch,
    actions: {
      setSelectedId: setter("selectedId"),
      setSelectedCandidateSnapshot: setter("selectedCandidateSnapshot"),
      setDeepLinkValidationPending: setter("deepLinkValidationPending"),
      setDeepLinkNotFound: setter("deepLinkNotFound"),
      setPendingCandidateAdvance: setter("pendingCandidateAdvance"),
      setQueueCompleted: setter("queueCompleted"),
      setCandidateActionError: setter("candidateActionError"),
      setSelectedCandidateIds: setter("selectedCandidateIds"),
      setQueryEdit: setter("queryEdit"),
      setForm: setter("form"),
      setFormCandidateId: setter("formCandidateId"),
      setCategoryEdited: setter("categoryEdited"),
      setSelectedHit: setter("selectedHit"),
      setNearbyConflict: setter("nearbyConflict"),
    },
  };
}
