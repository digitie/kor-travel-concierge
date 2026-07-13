"use client";

import { useRouter } from "next/navigation";
import {
  memo,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
  type MouseEvent,
} from "react";
import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
  type InfiniteData,
} from "@tanstack/react-query";
import {
  ExternalLinkIcon,
  InfoIcon,
  Loader2Icon,
  MapPinIcon,
  SearchIcon,
  SparklesIcon,
  SquareIcon,
  Trash2Icon,
} from "lucide-react";

import {
  deleteCandidate,
  getPlaceOpinion,
  listCategories,
  matchCategory,
  listDestinationFacets,
  listUnmatchedCandidatesPage,
  reprocessVideos,
  resolveCandidate,
  searchPlaces,
  type DestinationFacets,
  type DestinationFilter,
  type DestinationGroupDim,
  type DestinationSummary,
  type PlaceOpinion,
  type PlaceSearchHit,
  type PlaceSearchProvider,
  type ReprocessStage,
  type ListEnvelope,
  type UnmatchedCandidate,
} from "@/lib/api";
import {
  candidateStatusLabel,
  categoryDisplayLabel,
  queueReasonBadgeVariant,
  queueReasonLabel,
  sourceKindLabel,
} from "@/lib/display-labels";
import { formatDateTimeShort, youtubeWatchUrl } from "@/lib/format";
import {
  buildCreatePlaceResolution,
  isPlaceHitStorageAllowed,
  isSelectedHitModified,
  parseNearbyPlaceConflict,
  placeHitStorageBlockReason,
  type NearbyPlaceCandidate,
  type ReviewResolutionForm,
  type SelectedPlaceHit,
} from "@/lib/review-provenance";
import { useIsMobile } from "@/lib/use-is-mobile";
import { usePersistedState } from "@/lib/use-persisted-state";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  AlertDialog,
  AlertDialogClose,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Checkbox } from "@/components/ui/checkbox";
import { Switch } from "@/components/ui/switch";
import { AppShell } from "@/components/AppShell";
import { CandidateDetailView } from "@/components/CandidateDetailView";
import { ConfirmActionButton } from "@/components/ConfirmActionButton";
import { VWorldMap } from "@/components/VWorldMap";

const PROVIDER_LABELS: Record<PlaceSearchProvider, string> = {
  google: "Google Places",
  kakao: "Kakao",
  naver: "Naver",
};
const PROVIDER_ORDER = ["google", "kakao", "naver"] as const;
const INITIAL_REVIEW_CANDIDATE_LIMIT = 300;

type ReviewCandidatesKey = readonly [
  "unmatched-candidates",
  "pages",
  DestinationGroupDim,
  string | null,
];

type ResolveCommand = {
  candidateId: number;
  candidateName: string;
  visibleIndex: number;
  orderedCandidateIds: number[];
  loadedPageCount: number;
  queueScope: string;
  candidatesKey: ReviewCandidatesKey;
  action: "create_place" | "ignore";
  form: ReviewResolutionForm;
  selectedHit: SelectedPlaceHit | null;
  duplicate?: {
    resolution: "merge_existing" | "create_new";
    placeId?: number;
  };
};

type PendingCandidateAdvance = {
  processedIds: number[];
  anchorIndex: number;
  orderedCandidateIds: number[];
  loadedPageCount: number;
};

function removeCandidatesFromQueue(
  data: InfiniteData<ListEnvelope<UnmatchedCandidate>> | undefined,
  ids: number[],
): InfiniteData<ListEnvelope<UnmatchedCandidate>> | undefined {
  if (!data) return data;
  const removed = new Set(ids);
  const removedCount = new Set(
    data.pages.flatMap((page) =>
      page.items
        .filter((candidate) => removed.has(candidate.id))
        .map((candidate) => candidate.id),
    ),
  ).size;
  return {
    ...data,
    pages: data.pages.map((page) => ({
      ...page,
      items: page.items.filter((candidate) => !removed.has(candidate.id)),
      total: Math.max(0, page.total - removedCount),
    })),
  };
}

type NearbyConflict = {
  command: ResolveCommand;
  places: NearbyPlaceCandidate[];
};

function hitPlace(hit: PlaceSearchHit, placeId: number): DestinationSummary {
  return {
    place_id: placeId,
    name: hit.name,
    description: null,
    gemini_enriched_description: null,
    latitude: hit.latitude ?? 0,
    longitude: hit.longitude ?? 0,
    category: hit.category,
    official_address: hit.address,
    road_address: hit.road_address,
    is_geocoded: true,
    mention_count: 0,
    source_channel_count: 0,
    source_videos: [],
  };
}

// location_hint는 종종 AI가 쓴 장황한 문장("인천 (영상 설명에 언급)", "불확실함 (…)")이라
// 그대로 붙이면 검색이 망가진다. 괄호 설명을 떼고, 불확실/미상류는 힌트로 쓰지 않는다.
function cleanLocationHint(hint: string | null): string {
  if (!hint) return "";
  const stripped = hint
    .replace(/\([^)]*\)/g, " ") // 괄호 안 설명 제거
    .replace(/\s+/g, " ")
    .trim();
  if (!stripped) return "";
  if (/불확실|불명확|미상|없음|모름|unknown|n\/?a/i.test(stripped)) return "";
  // 앞쪽 2단어 정도의 지역명만 사용(예: "서울 강남" 유지, 긴 설명은 절단).
  return stripped.split(" ").slice(0, 2).join(" ");
}

function buildHintedQuery(candidate: UnmatchedCandidate): string {
  const name = candidate.ai_place_name.trim();
  const hint = cleanLocationHint(candidate.location_hint);
  if (hint && !name.toLowerCase().includes(hint.toLowerCase())) {
    return `${hint} ${name}`;
  }
  return name;
}

function candidateCategoryForm(candidate: UnmatchedCandidate) {
  return {
    category: categoryDisplayLabel(
      candidate.candidate_category ?? candidate.candidate_category_code,
    ),
    categoryCode: candidate.candidate_category_code ?? "0",
  };
}

export default function ReviewPage() {
  const queryClient = useQueryClient();
  // 결과 보기와 동일한 출처 필터(유튜버/재생목록/검색어별). 상세 페이지를 다녀와도
  // 필터가 유지되도록 sessionStorage에 보존한다.
  const [groupDim, setGroupDim] = usePersistedState<DestinationGroupDim>(
    "ktc.review.groupDim",
    "none",
  );
  const [groupValue, setGroupValue] = usePersistedState<string | null>(
    "ktc.review.groupValue",
    null,
  );
  const facetsQuery = useQuery({
    queryKey: ["destination-facets"],
    queryFn: listDestinationFacets,
    refetchInterval: 60_000,
  });
  // 카테고리 강제 드롭다운 목록(정적 카탈로그 — 오래 캐시).
  const categoriesQuery = useQuery({
    queryKey: ["categories"],
    queryFn: listCategories,
    staleTime: 60 * 60 * 1000,
  });
  const filter = useMemo<DestinationFilter | undefined>(() => {
    if (!groupValue || groupDim === "none") return undefined;
    if (groupDim === "channel") return { channelId: groupValue };
    if (groupDim === "playlist") return { playlistId: groupValue };
    return { keyword: groupValue };
  }, [groupDim, groupValue]);
  const candidatesKey = useMemo(
    () => ["unmatched-candidates", "pages", groupDim, groupValue] as const,
    [groupDim, groupValue],
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
    refetchInterval: 60_000,
  });
  // 장바구니: 선택한 영상 id를 sessionStorage에 보존 → 그룹 필터를 바꿔도(테이블 필터링)
  // 선택이 유지된다(쇼핑몰 장바구니). 영상 단위로 dedup.
  const [cart, setCart] = usePersistedState<string[]>("ktc.review.cart", []);
  const [reprocessStage, setReprocessStage] =
    useState<ReprocessStage>("transcript");
  // 해외(국내 아님) 후보 숨기기 토글(기본 보기). 상세 왕복에도 유지(sessionStorage).
  const [hideForeign, setHideForeign] = usePersistedState<boolean>(
    "ktc.review.hideForeign",
    false,
  );
  const cartSet = useMemo(() => new Set(cart), [cart]);
  const toggleCart = useCallback(
    (videoId: string) => {
      setCart((prev) =>
        prev.includes(videoId)
          ? prev.filter((v) => v !== videoId)
          : [...prev, videoId],
      );
    },
    [setCart],
  );
  const reprocessMutation = useMutation({
    mutationFn: () => reprocessVideos(cart, reprocessStage),
    onSuccess: () => {
      setCart([]);
    },
  });
  const candidates = useMemo(
    () => {
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
    },
    [candidatesQuery.data],
  );
  const candidatePages = useMemo(
    () => candidatesQuery.data?.pages ?? [],
    [candidatesQuery.data?.pages],
  );
  const lastCandidatePage = candidatePages[candidatePages.length - 1];
  const candidatePaginationContractError =
    lastCandidatePage?.has_more && !lastCandidatePage.next_cursor
      ? "다음 후보 cursor가 없어 검수 큐의 끝을 확인할 수 없습니다."
      : null;
  const canLoadMoreCandidates = Boolean(candidatesQuery.hasNextPage);
  // 해외 후보 숨기기 토글 적용(장바구니/그룹 필터는 그대로 — 순수 표시 필터).
  const visibleCandidates = useMemo(
    () =>
      hideForeign
        ? candidates.filter((c) => c.is_domestic !== false)
        : candidates,
    [candidates, hideForeign],
  );
  const queueScope = useMemo(
    () => JSON.stringify([groupDim, groupValue, hideForeign]),
    [groupDim, groupValue, hideForeign],
  );
  const queueScopeRef = useRef(queueScope);
  const previousQueueScopeRef = useRef(queueScope);
  useEffect(() => {
    queueScopeRef.current = queueScope;
  }, [queueScope]);
  const [selectedCandidateIds, setSelectedCandidateIds] = useState<number[]>([]);
  const selectedCandidateSet = useMemo(
    () => new Set(selectedCandidateIds),
    [selectedCandidateIds],
  );
  const visibleCandidateIds = useMemo(
    () => new Set(visibleCandidates.map((candidate) => candidate.id)),
    [visibleCandidates],
  );
  const allVisibleCandidatesSelected =
    visibleCandidates.length > 0 &&
    visibleCandidates.every((candidate) => selectedCandidateSet.has(candidate.id));
  const toggleCandidateSelection = useCallback((candidateId: number) => {
    setSelectedCandidateIds((current) =>
      current.includes(candidateId)
        ? current.filter((id) => id !== candidateId)
        : [...current, candidateId],
    );
  }, []);
  function toggleAllVisibleCandidates() {
    setSelectedCandidateIds((current) =>
      allVisibleCandidatesSelected
        ? current.filter((id) => !visibleCandidateIds.has(id))
        : Array.from(new Set([...current, ...visibleCandidates.map((c) => c.id)])),
    );
  }
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [selectedCandidateSnapshot, setSelectedCandidateSnapshot] =
    useState<UnmatchedCandidate | null>(null);
  const initialSelectionDoneRef = useRef(false);
  const [deepLinkedCandidateId, setDeepLinkedCandidateId] = useState<
    number | null
  >(null);
  const [deepLinkNotFound, setDeepLinkNotFound] = useState<string | null>(null);
  const pendingCandidateAdvanceRef = useRef<PendingCandidateAdvance | null>(null);
  const [pendingCandidateAdvance, setPendingCandidateAdvance] =
    useState<PendingCandidateAdvance | null>(null);
  const updatePendingCandidateAdvance = useCallback(
    (pending: PendingCandidateAdvance | null) => {
      const current = pendingCandidateAdvanceRef.current;
      if (
        current?.anchorIndex === pending?.anchorIndex &&
        current?.loadedPageCount === pending?.loadedPageCount &&
        current?.processedIds.length === pending?.processedIds.length &&
        current?.processedIds.every(
          (id, index) => id === pending?.processedIds[index],
        ) &&
        current?.orderedCandidateIds.length ===
          pending?.orderedCandidateIds.length &&
        current?.orderedCandidateIds.every(
          (id, index) => id === pending?.orderedCandidateIds[index],
        )
      ) {
        return;
      }
      if (current == null && pending == null) return;
      pendingCandidateAdvanceRef.current = pending;
      setPendingCandidateAdvance(pending);
    },
    [],
  );
  const [queueCompleted, setQueueCompleted] = useState(false);
  const [candidateActionError, setCandidateActionError] = useState<string | null>(
    null,
  );

  // 작업 상세에서 검수 대기 POI를 누르면 `?candidate=<id>`로 들어온다. 그 후보가 필터에
  // 가려지지 않도록 그룹 필터를 해제하고 해당 후보를 선택한다(딥링크, 최초 1회).
  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    const candidateParam = new URLSearchParams(window.location.search).get(
      "candidate",
    );
    if (!candidateParam) return;
    const candidateId = Number(candidateParam);
    if (!Number.isFinite(candidateId)) return;
    setDeepLinkNotFound(null);
    setDeepLinkedCandidateId(candidateId);
    setGroupDim("none");
    setGroupValue(null);
    setHideForeign(false);
    setSelectedId(candidateId);
  }, [setGroupDim, setGroupValue, setHideForeign]);
  /* eslint-enable react-hooks/set-state-in-effect */

  const selected = useMemo(
    () =>
      selectedId == null
        ? null
        : (candidates.find((candidate) => candidate.id === selectedId) ??
          (selectedCandidateSnapshot?.id === selectedId
            ? selectedCandidateSnapshot
            : null)),
    [candidates, selectedCandidateSnapshot, selectedId],
  );

  const [queryEdit, setQueryEdit] = useState<string | null>(null);
  const [activeQuery, setActiveQuery] = useState("");
  const autoSearchTimerRef = useRef<number | null>(null);
  // 검색 버튼은 검색어가 그대로여도 항상 재요청해야 한다. queryKey에 nonce를 넣어
  // runSearch/pickCandidate마다 증가시키면 동일 검색어로도 강제 refetch된다(무반응 방지).
  const [searchNonce, setSearchNonce] = useState(0);
  const query = queryEdit ?? (selected ? buildHintedQuery(selected) : "");

  const searchQuery = useQuery({
    queryKey: ["place-search", activeQuery, searchNonce],
    queryFn: ({ signal }) => searchPlaces(activeQuery, signal),
    enabled: activeQuery.trim().length > 0,
  });
  const result = searchQuery.data;

  // 검색 결과가 도착하면(검색 버튼/후보 선택 자동검색 모두) 결과 영역을 화면에 보이도록
  // 스크롤한다. 확정 정보 폼(#3)이 위에 있어 검색 결과가 폴드 아래로 밀리던 문제 해결.
  const resultsRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (result) {
      resultsRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }, [result]);

  // provider hits를 모아 Gemini 의견을 별도(비동기)로 호출 → 검색 자체는 빠르게.
  const allHits = useMemo(
    () => [
      ...(result?.google ?? []),
      ...(result?.kakao ?? []),
      ...(result?.naver ?? []),
    ].filter(isPlaceHitStorageAllowed),
    [result],
  );
  // AI(Gemini) 의견은 자동이 아니라 사용자가 버튼으로 수동 요청한다(쿼터 절약).
  const [opinionRequested, setOpinionRequested] = useState(false);
  const opinionQuery = useQuery({
    queryKey: ["place-opinion", activeQuery, searchNonce],
    queryFn: ({ signal }) => getPlaceOpinion(activeQuery, allHits, signal),
    enabled:
      opinionRequested && activeQuery.trim().length > 0 && allHits.length > 0,
  });
  const gemini = opinionQuery.data?.gemini ?? null;

  const router = useRouter();
  const isMobile = useIsMobile();
  const [detailId, setDetailId] = useState<number | null>(null);
  const [detailDeletePending, setDetailDeletePending] = useState(false);
  const detailDeleteSnapshotRef = useRef<{
    candidateId: number;
    visibleIndex: number;
    orderedCandidateIds: number[];
    loadedPageCount: number;
    queueScope: string;
    candidatesKey: ReviewCandidatesKey;
  } | null>(null);
  // 행 단위 삭제 확인: 2,000행에 AlertDialog를 하나씩 두면 렌더 비용이 폭증하므로
  // 페이지에 공용 다이얼로그 하나만 두고 대상 후보를 상태로 넘긴다.
  const [deleteTarget, setDeleteTarget] = useState<UnmatchedCandidate | null>(
    null,
  );

  const [form, setForm] = useState({
    name: "",
    latitude: "",
    longitude: "",
    category: "",
    // 강제 카테고리 코드(드롭다운). category(label)는 코드 선택 시 함께 채운다.
    categoryCode: "",
  });
  const [formCandidateId, setFormCandidateId] = useState<number | null>(null);
  const [categoryEdited, setCategoryEdited] = useState(false);
  const [selectedHit, setSelectedHit] = useState<SelectedPlaceHit | null>(null);
  const [nearbyConflict, setNearbyConflict] = useState<NearbyConflict | null>(null);
  const categoryMatchAbortRef = useRef<AbortController | null>(null);
  const categoryMatchRequestRef = useRef(0);
  const selectedCandidateIdRef = useRef<number | null>(selected?.id ?? null);

  useEffect(() => {
    if (previousQueueScopeRef.current === queueScope) return;
    previousQueueScopeRef.current = queueScope;
    initialSelectionDoneRef.current = false;
    updatePendingCandidateAdvance(null);
    selectedCandidateIdRef.current = null;
    setQueueCompleted(false);
    setSelectedCandidateSnapshot(null);
    setSelectedId(null);
  }, [queueScope, updatePendingCandidateAdvance]);

  const clearAutoSearchTimer = useCallback(() => {
    if (autoSearchTimerRef.current != null) {
      window.clearTimeout(autoSearchTimerRef.current);
      autoSearchTimerRef.current = null;
    }
  }, []);

  const cancelCategoryMatch = useCallback(() => {
    categoryMatchRequestRef.current += 1;
    categoryMatchAbortRef.current?.abort();
    categoryMatchAbortRef.current = null;
  }, []);

  useEffect(
    () => () => {
      clearAutoSearchTimer();
      cancelCategoryMatch();
    },
    [cancelCategoryMatch, clearAutoSearchTimer],
  );
  useEffect(() => {
    if (selected?.id != null) {
      selectedCandidateIdRef.current = selected.id;
    } else if (selectedId == null) {
      selectedCandidateIdRef.current = null;
    }
  }, [selected?.id, selectedId]);

  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    const candidateId = selected?.id ?? null;
    if (candidateId === formCandidateId) return;
    clearAutoSearchTimer();
    cancelCategoryMatch();
    setActiveQuery("");
    setQueryEdit(null);
    setOpinionRequested(false);
    setFormCandidateId(candidateId);
    setSelectedHit(null);
    setNearbyConflict(null);
    setCategoryEdited(false);
    setForm(
      selected
        ? {
            name: "",
            latitude: "",
            longitude: "",
            ...candidateCategoryForm(selected),
          }
        : {
            name: "",
            latitude: "",
            longitude: "",
            category: "",
            categoryCode: "",
          },
    );
  }, [cancelCategoryMatch, clearAutoSearchTimer, formCandidateId, selected]);
  /* eslint-enable react-hooks/set-state-in-effect */

  function runSearch() {
    if (query.trim()) {
      clearAutoSearchTimer();
      setOpinionRequested(false);
      setSearchNonce((n) => n + 1);
      setActiveQuery(query.trim());
    }
  }
  function stopSearch() {
    // 진행 중 요청을 취소(BFF가 upstream abort까지 전파)하고, 취소된 쿼리 캐시를
    // 제거해 같은 검색어로 재검색할 때 깨끗하게 다시 가져오도록 한다.
    void queryClient.cancelQueries({ queryKey: ["place-search", activeQuery] });
    void queryClient.cancelQueries({ queryKey: ["place-opinion", activeQuery] });
    queryClient.removeQueries({ queryKey: ["place-search", activeQuery] });
    queryClient.removeQueries({ queryKey: ["place-opinion", activeQuery] });
    clearAutoSearchTimer();
    setOpinionRequested(false);
    setActiveQuery("");
  }
  // 검수 상세: 모바일=새 페이지, PC=모달.
  const openDetail = useCallback(
    (candidateId: number) => {
      if (isMobile) {
        router.push(`/review/${candidateId}`);
      } else {
        detailDeleteSnapshotRef.current = null;
        setDetailId(candidateId);
      }
    },
    [isMobile, router],
  );
  const clearCandidateParam = useCallback(() => {
    const url = new URL(window.location.href);
    if (url.searchParams.has("candidate")) {
      url.searchParams.delete("candidate");
      router.replace(`${url.pathname}${url.search}${url.hash}`, {
        scroll: false,
      });
    }
    setDeepLinkNotFound(null);
    setDeepLinkedCandidateId(null);
  }, [router]);
  const clearProcessedCandidateParam = useCallback(
    (candidateId: number) => {
      const url = new URL(window.location.href);
      if (url.searchParams.get("candidate") !== String(candidateId)) return;
      url.searchParams.delete("candidate");
      setDeepLinkedCandidateId(null);
      setDeepLinkNotFound(null);
      router.replace(`${url.pathname}${url.search}${url.hash}`, {
        scroll: false,
      });
    },
    [router],
  );
  const pickCandidate = useCallback(
    (
      candidate: UnmatchedCandidate,
      {
        autoSearch = true,
        preserveWorkflow = false,
      }: { autoSearch?: boolean; preserveWorkflow?: boolean } = {},
    ) => {
      // 검색 취소와 새 자동 검색을 함께 조금 늦춰 후보 선택/폼 반영이 먼저 그려지게 한다.
      // 이전 검색 결과는 새 검색을 시작하기 직전에 취소해 새 후보에 매달리지 않도록 한다.
      clearAutoSearchTimer();
      if (!preserveWorkflow) {
        initialSelectionDoneRef.current = true;
        updatePendingCandidateAdvance(null);
        clearCandidateParam();
      }
      const nextQuery = buildHintedQuery(candidate);
      selectedCandidateIdRef.current = candidate.id;
      setQueueCompleted(false);
      setSelectedCandidateSnapshot(candidate);
      setSelectedId(candidate.id);
      setQueryEdit(null);
      setOpinionRequested(false);
      cancelCategoryMatch();
      setCategoryEdited(false);
      setSelectedHit(null);
      setNearbyConflict(null);
      setFormCandidateId(candidate.id);
      setActiveQuery("");
      setForm({
        name: "",
        latitude: "",
        longitude: "",
        ...candidateCategoryForm(candidate),
      });
      if (!autoSearch) return;
      autoSearchTimerRef.current = window.setTimeout(() => {
        autoSearchTimerRef.current = null;
        void queryClient.cancelQueries({ queryKey: ["place-search"] });
        void queryClient.cancelQueries({ queryKey: ["place-opinion"] });
        setSearchNonce((n) => n + 1);
        setActiveQuery(nextQuery);
      }, 120);
    },
    [
      cancelCategoryMatch,
      clearAutoSearchTimer,
      clearCandidateParam,
      queryClient,
      updatePendingCandidateAdvance,
    ],
  );

  const continueCandidateAdvance = useCallback(
    (plan: PendingCandidateAdvance) => {
      const processedIdSet = new Set(plan.processedIds);
      const remaining = visibleCandidates.filter(
        (candidate) => !processedIdSet.has(candidate.id),
      );
      const remainingById = new Map(
        remaining.map((candidate) => [candidate.id, candidate]),
      );
      const nextSnapshotId = plan.orderedCandidateIds
        .slice(plan.anchorIndex + 1)
        .find((candidateId) => remainingById.has(candidateId));
      const next =
        nextSnapshotId == null ? null : (remainingById.get(nextSnapshotId) ?? null);
      if (next) {
        updatePendingCandidateAdvance(null);
        setQueueCompleted(false);
        pickCandidate(next, { preserveWorkflow: true });
        return;
      }
      const newlyLoadedCandidate = candidatePages
        .slice(plan.loadedPageCount)
        .flatMap((page) => page.items)
        .find(
          (candidate) =>
            !processedIdSet.has(candidate.id) &&
            (!hideForeign || candidate.is_domestic !== false),
        );
      if (newlyLoadedCandidate) {
        updatePendingCandidateAdvance(null);
        setQueueCompleted(false);
        pickCandidate(newlyLoadedCandidate, { preserveWorkflow: true });
        return;
      }
      if (candidatePaginationContractError) {
        updatePendingCandidateAdvance(plan);
        return;
      }
      if (candidatesQuery.hasNextPage) {
        updatePendingCandidateAdvance(plan);
        if (
          !candidatesQuery.isFetchingNextPage &&
          !candidatesQuery.isFetchNextPageError
        ) {
          void candidatesQuery.fetchNextPage({ cancelRefetch: false });
        }
        return;
      }
      updatePendingCandidateAdvance(null);
      const previousSnapshotId = plan.orderedCandidateIds
        .slice(0, plan.anchorIndex)
        .reverse()
        .find((candidateId) => remainingById.has(candidateId));
      const previous =
        previousSnapshotId == null
          ? null
          : (remainingById.get(previousSnapshotId) ?? null);
      if (previous) {
        setQueueCompleted(false);
        pickCandidate(previous, { preserveWorkflow: true });
        return;
      }
      const firstRemaining = remaining[0] ?? null;
      if (firstRemaining) {
        setQueueCompleted(false);
        pickCandidate(firstRemaining, { preserveWorkflow: true });
        return;
      }
      clearAutoSearchTimer();
      setSelectedCandidateSnapshot(null);
      setSelectedId(null);
      setQueueCompleted(true);
    },
    [
      candidatesQuery,
      candidatePaginationContractError,
      candidatePages,
      clearAutoSearchTimer,
      hideForeign,
      pickCandidate,
      updatePendingCandidateAdvance,
      visibleCandidates,
    ],
  );

  const advanceAfterProcessing = useCallback(
    (
      processedId: number,
      processedIds: number[] = [processedId],
      visibleIndex?: number,
      orderedCandidateIds: number[] = visibleCandidates.map(
        (candidate) => candidate.id,
      ),
      loadedPageCount: number = candidatePages.length,
    ) => {
      const anchorIndex =
        visibleIndex ??
        orderedCandidateIds.findIndex((candidateId) => candidateId === processedId);
      if (anchorIndex < 0) return;
      clearProcessedCandidateParam(processedId);
      continueCandidateAdvance({
        processedIds,
        anchorIndex,
        orderedCandidateIds,
        loadedPageCount,
      });
    }, [
      candidatePages.length,
      clearProcessedCandidateParam,
      continueCandidateAdvance,
      visibleCandidates,
    ]);

  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    const pending = pendingCandidateAdvance;
    if (!pending || candidatesQuery.isFetchingNextPage) return;
    continueCandidateAdvance(pending);
  }, [
    candidatesQuery.isFetchingNextPage,
    candidatesQuery.data,
    continueCandidateAdvance,
    pendingCandidateAdvance,
  ]);
  /* eslint-enable react-hooks/set-state-in-effect */

  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    if (
      candidatesQuery.isFetching ||
      initialSelectionDoneRef.current ||
      pendingCandidateAdvance
    ) {
      return;
    }
    const deepLinkedId = deepLinkedCandidateId;
    if (deepLinkedId != null) {
      const linked = candidates.find((candidate) => candidate.id === deepLinkedId);
      if (linked) {
        setDeepLinkNotFound(null);
        initialSelectionDoneRef.current = true;
        pickCandidate(linked, { autoSearch: false, preserveWorkflow: true });
        return;
      }
      if (
        candidatesQuery.hasNextPage &&
        !candidatesQuery.isFetchNextPageError &&
        !candidatePaginationContractError
      ) {
        void candidatesQuery.fetchNextPage({ cancelRefetch: false });
        return;
      }
      if (
        candidatesQuery.isError ||
        candidatesQuery.isFetchNextPageError ||
        candidatePaginationContractError
      ) {
        return;
      }
      setDeepLinkNotFound(`검수 후보 #${deepLinkedId}을(를) 찾을 수 없습니다.`);
      initialSelectionDoneRef.current = true;
      return;
    }
    if (selectedId != null) return;
    const first = visibleCandidates[0];
    if (first) {
      initialSelectionDoneRef.current = true;
      pickCandidate(first, { autoSearch: false, preserveWorkflow: true });
      return;
    }
    if (
      candidatesQuery.hasNextPage &&
      !candidatesQuery.isFetchNextPageError &&
      !candidatePaginationContractError
    ) {
      void candidatesQuery.fetchNextPage({ cancelRefetch: false });
      return;
    }
    if (!candidatesQuery.isError && !candidatePaginationContractError) {
      initialSelectionDoneRef.current = true;
    }
  }, [
    candidates,
    candidatePaginationContractError,
    candidatesQuery,
    deepLinkedCandidateId,
    pendingCandidateAdvance,
    pickCandidate,
    selectedId,
    visibleCandidates,
  ]);
  /* eslint-enable react-hooks/set-state-in-effect */

  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    if (
      !queueCompleted ||
      candidatesQuery.isFetching ||
      pendingCandidateAdvance ||
      visibleCandidates.length === 0
    ) {
      return;
    }
    initialSelectionDoneRef.current = true;
    pickCandidate(visibleCandidates[0], {
      autoSearch: false,
      preserveWorkflow: true,
    });
  }, [
    candidatesQuery.isFetching,
    pendingCandidateAdvance,
    pickCandidate,
    queueCompleted,
    visibleCandidates,
  ]);
  /* eslint-enable react-hooks/set-state-in-effect */

  const deleteCandidatesMutation = useMutation({
    mutationFn: async (ids: number[]) => {
      await Promise.all(ids.map((id) => deleteCandidate(id)));
      return ids;
    },
    onMutate: async () => {
      await queryClient.cancelQueries({ queryKey: ["unmatched-candidates"] });
      const previous =
        queryClient.getQueryData<InfiniteData<ListEnvelope<UnmatchedCandidate>>>(
          candidatesKey,
        );
      const focusedId = selectedCandidateIdRef.current;
      return {
        previous,
        candidatesKey,
        focusedId,
        visibleIndex:
          focusedId == null
            ? -1
            : visibleCandidates.findIndex((candidate) => candidate.id === focusedId),
        orderedCandidateIds: visibleCandidates.map((candidate) => candidate.id),
        loadedPageCount: candidatePages.length,
        queueScope: queueScopeRef.current,
      };
    },
    onSuccess: async (ids, _variables, context) => {
      await queryClient.cancelQueries({ queryKey: ["unmatched-candidates"] });
      queryClient.setQueryData<InfiniteData<ListEnvelope<UnmatchedCandidate>>>(
        context.candidatesKey,
        (old) => removeCandidatesFromQueue(old, ids),
      );
      queryClient.invalidateQueries({
        queryKey: ["unmatched-candidates"],
        refetchType: "none",
      });
      setSelectedCandidateIds((current) =>
        current.filter((id) => !ids.includes(id)),
      );
      ids.forEach(clearProcessedCandidateParam);
      const focusedId = context.focusedId;
      if (
        focusedId != null &&
        ids.includes(focusedId) &&
        focusedId === selectedCandidateIdRef.current &&
        context.queueScope === queueScopeRef.current
      ) {
        if (ids.length === 1) {
          advanceAfterProcessing(
            focusedId,
            ids,
            context.visibleIndex,
            context.orderedCandidateIds,
            context.loadedPageCount,
          );
        } else {
          clearProcessedCandidateParam(focusedId);
          clearAutoSearchTimer();
          initialSelectionDoneRef.current = false;
          selectedCandidateIdRef.current = null;
          setQueueCompleted(false);
          setSelectedCandidateSnapshot(null);
          setSelectedId(null);
        }
      }
    },
    onError: (_error, _ids, context) => {
      if (!context?.previous) return;
      queryClient.setQueryData(context.candidatesKey, context.previous);
    },
    onSettled: (_data, error) => {
      if (error) {
        queryClient.invalidateQueries({ queryKey: ["unmatched-candidates"] });
      }
    },
  });

  function selectHit(hit: PlaceSearchHit) {
    if (!selected || !isPlaceHitStorageAllowed(hit)) return;
    cancelCategoryMatch();
    const candidateId = selected.id;
    const nextSelectedHit: SelectedPlaceHit = {
      candidateId,
      hit,
      query: result?.query ?? activeQuery,
      searchedAt: result?.searched_at ?? new Date().toISOString(),
      selectedAt: new Date().toISOString(),
    };
    setSelectedHit(nextSelectedHit);
    setNearbyConflict(null);
    setFormCandidateId(candidateId);
    setForm((prev) => ({
      ...prev,
      name: hit.name,
      latitude: hit.latitude == null ? "" : String(hit.latitude),
      longitude: hit.longitude == null ? "" : String(hit.longitude),
    }));
    // 검색결과 카테고리 매칭이 되면 그 값을 쓰고, 실패하면 후보의 기본 카테고리를 유지한다.
    // 사용자가 드롭다운을 직접 바꾼 뒤에는 자동 매칭으로 덮어쓰지 않는다.
    if (hit.category && !categoryEdited) {
      const controller = new AbortController();
      categoryMatchAbortRef.current = controller;
      const requestId = ++categoryMatchRequestRef.current;
      void matchCategory(hit.category, controller.signal)
        .then((match) => {
          if (
            !match ||
            controller.signal.aborted ||
            requestId !== categoryMatchRequestRef.current ||
            candidateId !== selectedCandidateIdRef.current
          ) {
            return;
          }
          setForm((prev) => ({
            ...prev,
            categoryCode: match.code,
            category: match.label,
          }));
        })
        // 카테고리 자동 매핑 실패는 후보 선택 자체를 막지 않는다.
        .catch(() => {})
        .finally(() => {
          if (requestId === categoryMatchRequestRef.current) {
            categoryMatchAbortRef.current = null;
          }
        });
    }
  }
  function applyGemini(gemini: PlaceOpinion) {
    // Gemini 의견도 카테고리는 덮어쓰지 않는다(드롭다운이 단일 출처).
    cancelCategoryMatch();
    setSelectedHit(null);
    setNearbyConflict(null);
    setFormCandidateId(selected?.id ?? null);
    setForm((prev) => ({
      ...prev,
      name: gemini.best_name ?? prev.name,
      latitude: gemini.latitude != null ? String(gemini.latitude) : prev.latitude,
      longitude:
        gemini.longitude != null ? String(gemini.longitude) : prev.longitude,
    }));
  }

  const activeSelectedHit =
    selectedHit?.candidateId === selected?.id ? selectedHit : null;
  const mapHitEntries = useMemo(
    () =>
      allHits
        .filter(
          (hit) =>
            isPlaceHitStorageAllowed(hit) &&
            hit.latitude != null &&
            hit.longitude != null,
        )
        .map((hit, index) => ({ placeId: index + 1, hit })),
    [allHits],
  );
  const mapPlaces = useMemo<DestinationSummary[]>(() => {
    const hits = mapHitEntries.map(({ hit, placeId }) => hitPlace(hit, placeId));
    const lat = Number(form.latitude);
    const lng = Number(form.longitude);
    if (Number.isFinite(lat) && Number.isFinite(lng) && form.latitude) {
      hits.unshift({
        place_id: 9999,
        name: form.name || "선택 위치",
        description: null,
        gemini_enriched_description: null,
        latitude: lat,
        longitude: lng,
        category: form.category || null,
        official_address: activeSelectedHit?.hit.address ?? null,
        road_address: activeSelectedHit?.hit.road_address ?? null,
        is_geocoded: true,
        mention_count: 0,
        source_channel_count: 0,
        source_videos: [],
      });
    }
    return hits;
  }, [activeSelectedHit, form, mapHitEntries]);

  const resolveMutation = useMutation({
    mutationFn: (command: ResolveCommand) => {
      if (command.action === "ignore") {
        return resolveCandidate(command.candidateId, {
          action: "ignore",
          reviewNote: "검수 페이지 제외",
        });
      }
      return resolveCandidate(
        command.candidateId,
        buildCreatePlaceResolution(
          command.form,
          command.selectedHit,
          command.duplicate,
        ),
      );
    },
    onError: (error, command) => {
      const conflict = parseNearbyPlaceConflict(error);
      const isCurrentCommand =
        selectedCandidateIdRef.current === command.candidateId &&
        queueScopeRef.current === command.queueScope;
      if (
        conflict &&
        isCurrentCommand
      ) {
        setNearbyConflict({ command, places: conflict });
        return;
      }
      if (!isCurrentCommand) {
        setCandidateActionError(
          conflict
            ? `${command.candidateName} 후보는 근접 장소 확인이 필요합니다. 후보를 다시 선택해 처리하세요.`
            : `${command.candidateName} 후보 처리 실패: ${error.message}`,
        );
      }
    },
    onSuccess: async (_data, command) => {
      // 409 중복 확인 응답은 성공이 아니므로 여기까지 오지 않는다. 실제 확정 뒤에만
      // 큐에서 제거해 확인 다이얼로그가 뜰 때 후보가 사라졌다 복원되는 깜빡임을 막는다.
      await queryClient.cancelQueries({ queryKey: ["unmatched-candidates"] });
      queryClient.setQueryData<InfiniteData<ListEnvelope<UnmatchedCandidate>>>(
        command.candidatesKey,
        (old) => removeCandidatesFromQueue(old, [command.candidateId]),
      );
      queryClient.invalidateQueries({
        queryKey: ["unmatched-candidates"],
        refetchType: "none",
      });
      queryClient.invalidateQueries({ queryKey: ["destinations"] });
      setNearbyConflict(null);
      setCandidateActionError(null);
      clearProcessedCandidateParam(command.candidateId);
      if (
        selectedCandidateIdRef.current === command.candidateId &&
        queueScopeRef.current === command.queueScope
      ) {
        cancelCategoryMatch();
        clearAutoSearchTimer();
        advanceAfterProcessing(
          command.candidateId,
          [command.candidateId],
          command.visibleIndex,
          command.orderedCandidateIds,
          command.loadedPageCount,
        );
      }
    },
    onSettled: (_data, error) => {
      if (error) {
        queryClient.invalidateQueries({ queryKey: ["unmatched-candidates"] });
      }
    },
  });

  function resolveSelected(
    action: "create_place" | "ignore",
    duplicate?: ResolveCommand["duplicate"],
  ) {
    if (!selected || formCandidateId !== selected.id) return;
    setCandidateActionError(null);
    resolveMutation.mutate({
      candidateId: selected.id,
      candidateName: selected.ai_place_name,
      visibleIndex: visibleCandidates.findIndex(
        (candidate) => candidate.id === selected.id,
      ),
      orderedCandidateIds: visibleCandidates.map((candidate) => candidate.id),
      loadedPageCount: candidatePages.length,
      queueScope,
      candidatesKey,
      action,
      form: { ...form },
      selectedHit: activeSelectedHit,
      duplicate,
    });
  }

  const resetReviewScope = useCallback(() => {
    initialSelectionDoneRef.current = false;
    updatePendingCandidateAdvance(null);
    selectedCandidateIdRef.current = null;
    clearAutoSearchTimer();
    cancelCategoryMatch();
    clearCandidateParam();
    setQueueCompleted(false);
    setSelectedCandidateSnapshot(null);
    setSelectedId(null);
  }, [
    cancelCategoryMatch,
    clearAutoSearchTimer,
    clearCandidateParam,
    updatePendingCandidateAdvance,
  ]);

  // 좌표 입력 검증: 숫자 여부(차단) + 대한민국 대략 범위(경고만, 저장은 허용).
  const latInvalid = Boolean(form.latitude) && !Number.isFinite(Number(form.latitude));
  const lngInvalid =
    Boolean(form.longitude) && !Number.isFinite(Number(form.longitude));
  const coordsFilled =
    Boolean(form.latitude) &&
    Boolean(form.longitude) &&
    !latInvalid &&
    !lngInvalid;
  const coordsOutOfKorea =
    coordsFilled &&
    (Number(form.latitude) < 33 ||
      Number(form.latitude) > 39 ||
      Number(form.longitude) < 124 ||
      Number(form.longitude) > 132);
  const canSave =
    selected != null &&
    formCandidateId === selected.id &&
    Boolean(form.name.trim()) &&
    coordsFilled &&
    (activeSelectedHit == null || isPlaceHitStorageAllowed(activeSelectedHit.hit));
  const candidateAdvancePending = pendingCandidateAdvance != null;
  const candidateAdvanceError =
    candidateAdvancePending
      ? candidatePaginationContractError ??
        (candidatesQuery.isFetchNextPageError
          ? candidatesQuery.error?.message ?? "다음 후보를 불러오지 못했습니다."
          : null)
      : null;
  const candidateLoadError =
    deepLinkNotFound ??
    candidatePaginationContractError ??
    (candidatesQuery.isError || candidatesQuery.isFetchNextPageError
      ? candidatesQuery.error?.message ?? "검수 후보를 불러오지 못했습니다."
      : null);
  const candidateActionPending =
    resolveMutation.isPending || deleteCandidatesMutation.isPending;

  function retryCandidateAdvance() {
    if (candidatePaginationContractError) {
      void candidatesQuery.refetch();
      return;
    }
    if (
      !pendingCandidateAdvance ||
      !candidatesQuery.hasNextPage ||
      candidatesQuery.isFetchingNextPage
    ) {
      return;
    }
    void candidatesQuery.fetchNextPage({ cancelRefetch: false });
  }

  function retryCandidateLoad() {
    setDeepLinkNotFound(null);
    initialSelectionDoneRef.current = false;
    if (
      candidatesQuery.isFetchNextPageError &&
      candidatesQuery.hasNextPage &&
      !candidatesQuery.isFetchingNextPage
    ) {
      void candidatesQuery.fetchNextPage({ cancelRefetch: false });
      return;
    }
    void candidatesQuery.refetch();
  }

  return (
    <AppShell
      title="검수 큐"
      actions={<Badge variant="secondary">{candidates.length}개 표시</Badge>}
      contentClassName="flex min-h-0 flex-1 flex-col p-0"
      viewportLocked
    >
      <div className="grid h-full min-h-0 flex-1 grid-cols-1 lg:grid-cols-3 lg:overflow-hidden">
        <aside className="flex min-h-0 max-h-[48vh] flex-col gap-2 border-b p-3 lg:h-full lg:max-h-none lg:border-r lg:border-b-0">
          <div className="flex items-center justify-between gap-2">
            <p className="px-1 text-xs font-medium text-muted-foreground">
              검수 대기 후보
            </p>
            <Badge variant="secondary">{visibleCandidates.length}</Badge>
          </div>
          <div className="grid grid-cols-2 gap-1.5 pb-1">
            <Select
              value={groupDim}
              onValueChange={(value) => {
                resetReviewScope();
                setGroupDim(value as DestinationGroupDim);
                setGroupValue(null);
              }}
            >
              <SelectTrigger className="w-full" aria-label="검수 그룹 기준">
                <SelectValue>{groupDimLabel(groupDim)}</SelectValue>
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  <SelectItem value="none">전체</SelectItem>
                  <SelectItem value="channel">유튜버별</SelectItem>
                  <SelectItem value="playlist">재생목록별</SelectItem>
                  <SelectItem value="keyword">검색어별</SelectItem>
                </SelectGroup>
              </SelectContent>
            </Select>
            {groupDim !== "none" ? (
              <Select
                value={groupValue ?? ""}
                onValueChange={(value) => {
                  resetReviewScope();
                  setGroupValue(value || null);
                }}
              >
                <SelectTrigger className="w-full" aria-label="그룹 값 선택">
                  <SelectValue placeholder={`${groupDimLabel(groupDim)} 선택`}>
                    {groupValueLabel(groupDim, groupValue, facetsQuery.data)}
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  <SelectGroup>
                    {groupOptions(groupDim, facetsQuery.data).map((opt) => (
                      <SelectItem key={opt.value} value={opt.value}>
                        {opt.label} ({opt.count})
                      </SelectItem>
                    ))}
                  </SelectGroup>
                </SelectContent>
              </Select>
            ) : (
              <div />
            )}
          </div>
          {selectedCandidateIds.length > 0 ? (
            <div className="flex flex-wrap items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-2">
              <span className="text-xs font-medium text-destructive">
                후보 {selectedCandidateIds.length}개 선택됨
              </span>
              <ConfirmActionButton
                title={`선택한 후보 ${selectedCandidateIds.length}개를 삭제할까요?`}
                description="되돌릴 수 없습니다."
                onConfirm={() =>
                  deleteCandidatesMutation.mutate(selectedCandidateIds)
                }
                trigger={
                  <Button
                    type="button"
                    size="xs"
                    variant="destructive"
                    disabled={candidateActionPending}
                  >
                    <Trash2Icon data-icon="inline-start" />
                    선택 삭제
                  </Button>
                }
              />
              <Button
                type="button"
                size="xs"
                variant="outline"
                onClick={() => setSelectedCandidateIds([])}
              >
                선택 해제
              </Button>
            </div>
          ) : null}
          {deleteCandidatesMutation.error ? (
            <p className="rounded-lg border border-destructive/30 bg-destructive/5 p-2 text-xs text-destructive" role="alert">
              {deleteCandidatesMutation.error.message}
            </p>
          ) : null}
          {candidateActionError ? (
            <p className="rounded-lg border border-destructive/30 bg-destructive/5 p-2 text-xs text-destructive" role="alert">
              {candidateActionError}
            </p>
          ) : null}
          {reprocessMutation.isSuccess && reprocessMutation.data ? (
            <p className="rounded-lg bg-primary/10 px-2 py-1 text-xs text-primary">
              영상 {reprocessMutation.data.videos}개를{" "}
              {reprocessMutation.data.enqueued_jobs}개 작업으로 재처리 등록했습니다.
            </p>
          ) : null}
          {cart.length > 0 ? (
            <div className="flex flex-col gap-1.5 rounded-lg border border-primary/40 bg-primary/5 p-2">
              <p className="text-xs font-medium">
                선택한 영상 {cart.length}개 재처리
              </p>
              <Select
                value={reprocessStage}
                onValueChange={(value) =>
                  setReprocessStage(value as ReprocessStage)
                }
              >
                <SelectTrigger className="w-full" aria-label="재처리 시작 단계">
                  <SelectValue>{reprocessStageLabel(reprocessStage)}</SelectValue>
                </SelectTrigger>
                <SelectContent>
                  <SelectGroup>
                    <SelectItem value="transcript">자막 수집부터</SelectItem>
                    <SelectItem value="correction">교정부터</SelectItem>
                    <SelectItem value="poi">POI 추출부터</SelectItem>
                  </SelectGroup>
                </SelectContent>
              </Select>
              <div className="grid grid-cols-2 gap-1.5">
                <Button
                  type="button"
                  size="xs"
                  onClick={() => reprocessMutation.mutate()}
                  disabled={reprocessMutation.isPending}
                >
                  선택 재처리
                </Button>
                <Button
                  type="button"
                  size="xs"
                  variant="outline"
                  onClick={() => setCart([])}
                >
                  비우기
                </Button>
              </div>
              {reprocessMutation.error ? (
                <p className="text-xs text-destructive">
                  {reprocessMutation.error.message}
                </p>
              ) : null}
            </div>
          ) : null}
          <label className="flex items-center gap-1.5 px-1 pb-1 text-xs text-muted-foreground">
            <Switch
              checked={hideForeign}
              onCheckedChange={(checked) => {
                resetReviewScope();
                setHideForeign(Boolean(checked));
              }}
            />
            해외(국내 아님) 후보 숨기기
          </label>
          <div className="min-h-0 flex-1 overflow-y-auto">
            {visibleCandidates.length === 0 ? (
              candidateAdvancePending ? (
                <div className="flex flex-col gap-2 rounded-lg border p-3 text-xs text-muted-foreground">
                  <p role="status">
                    {candidateAdvanceError
                      ? candidateAdvanceError
                      : "다음 검수 후보를 불러오는 중…"}
                  </p>
                  {candidateAdvanceError ? (
                    <Button
                      type="button"
                      size="xs"
                      variant="outline"
                      onClick={retryCandidateAdvance}
                    >
                      다시 시도
                    </Button>
                  ) : null}
                </div>
              ) : candidateLoadError ? (
                <div className="flex flex-col gap-2 rounded-lg border border-destructive/30 p-3 text-xs text-destructive">
                  <p role="alert">{candidateLoadError}</p>
                  <Button
                    type="button"
                    size="xs"
                    variant="outline"
                    onClick={retryCandidateLoad}
                  >
                    다시 시도
                  </Button>
                </div>
              ) : (
                <p
                  role={queueCompleted ? "status" : undefined}
                  className="rounded-lg border p-3 text-xs text-muted-foreground"
                >
                  {queueCompleted
                    ? "현재 표시 조건의 검수 후보를 모두 처리했습니다."
                    : "검수할 후보가 없습니다."}
                </p>
              )
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-10">
                      <Checkbox
                        checked={allVisibleCandidatesSelected}
                        onCheckedChange={toggleAllVisibleCandidates}
                        aria-label="보이는 후보 전체 선택"
                      />
                    </TableHead>
                    <TableHead>후보</TableHead>
                    <TableHead>출처</TableHead>
                    <TableHead>상태</TableHead>
                    <TableHead className="text-right">액션</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {visibleCandidates.map((candidate) => (
                    <CandidateRow
                      key={candidate.id}
                      candidate={candidate}
                      isCurrent={candidate.id === selected?.id}
                      isChecked={selectedCandidateSet.has(candidate.id)}
                      inCart={cartSet.has(candidate.video_id)}
                      onToggleSelect={toggleCandidateSelection}
                      onPick={pickCandidate}
                      onToggleCart={toggleCart}
                      onOpenDetail={openDetail}
                      onRequestDelete={setDeleteTarget}
                    />
                  ))}
                </TableBody>
              </Table>
            )}
            {canLoadMoreCandidates ? (
              <div className="sticky bottom-0 border-t bg-background p-2">
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  className="w-full"
                  disabled={candidatesQuery.isFetchingNextPage}
                  onClick={() => {
                    if (
                      !candidatesQuery.hasNextPage ||
                      candidatesQuery.isFetchingNextPage
                    ) {
                      return;
                    }
                    void candidatesQuery.fetchNextPage({ cancelRefetch: false });
                  }}
                >
                  {candidatesQuery.isFetchingNextPage ? (
                    <Loader2Icon data-icon="inline-start" className="animate-spin" />
                  ) : null}
                  후보 더 불러오기
                </Button>
              </div>
            ) : null}
          </div>
        </aside>

        <section className="flex min-h-0 flex-col gap-4 overflow-y-auto p-5">
          {selected ? (
            <>
              <div className="flex flex-col gap-2 rounded-xl border p-4">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-semibold">
                    {selected.ai_place_name}
                  </span>
                  <Badge variant="outline">
                    {categoryDisplayLabel(selected.candidate_category)}
                  </Badge>
                  <Badge variant="secondary">
                    {candidateStatusLabel(selected.match_status)}
                  </Badge>
                </div>
                {selected.location_hint ? (
                  <p className="text-xs text-muted-foreground">
                    위치 힌트: {selected.location_hint}
                  </p>
                ) : null}
                <div className="flex flex-wrap items-center gap-3">
                  <a
                    href={youtubeWatchUrl(
                      selected.video_id,
                      selected.timestamp_start,
                    )}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex w-fit items-center gap-1 text-xs text-primary hover:underline"
                  >
                    영상 보기 <ExternalLinkIcon className="size-3" />
                  </a>
                  <Button
                    type="button"
                    size="xs"
                    variant="outline"
                    onClick={() => openDetail(selected.id)}
                  >
                    <InfoIcon data-icon="inline-start" />
                    상세 보기
                  </Button>
                </div>
              </div>

              <div className="flex gap-2">
                <Input
                  value={query}
                  placeholder="장소명으로 검색 (Google·Kakao·Naver·Gemini)"
                  onChange={(event) => setQueryEdit(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") {
                      runSearch();
                    }
                  }}
                />
                <Button type="button" onClick={runSearch} disabled={!query.trim()}>
                  {searchQuery.isFetching ? (
                    <Loader2Icon data-icon="inline-start" className="animate-spin" />
                  ) : (
                    <SearchIcon data-icon="inline-start" />
                  )}
                  검색
                </Button>
                {searchQuery.isFetching ? (
                  <Button type="button" variant="outline" onClick={stopSearch}>
                    <SquareIcon data-icon="inline-start" />
                    검색 중지
                  </Button>
                ) : null}
              </div>

              {/* #3: 확정 정보 — 검색 필드 아래, 검색 결과/지도 위에 배치. */}
              <div className="flex flex-col gap-2 rounded-xl border p-3">
                <p className="flex items-center gap-1.5 text-sm font-medium">
                  <MapPinIcon className="size-4 text-muted-foreground" />
                  확정 정보
                </p>
                {activeSelectedHit ? (
                  <div className="flex flex-col gap-1 rounded-lg bg-muted/60 p-2 text-xs">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <span className="font-medium">선택 원본</span>
                      <Badge variant="outline">
                        {PROVIDER_LABELS[activeSelectedHit.hit.provider]}
                      </Badge>
                      {isSelectedHitModified(form, activeSelectedHit) ? (
                        <Badge variant="secondary">최종 입력에서 수정됨</Badge>
                      ) : null}
                    </div>
                    <span>{activeSelectedHit.hit.name}</span>
                    <span className="text-muted-foreground">
                      {activeSelectedHit.hit.road_address ??
                        activeSelectedHit.hit.address ??
                        "주소 없음"}
                    </span>
                    <span className="font-mono text-muted-foreground">
                      {activeSelectedHit.hit.latitude?.toFixed(5)}, {" "}
                      {activeSelectedHit.hit.longitude?.toFixed(5)}
                    </span>
                  </div>
                ) : (
                  <p className="text-xs text-muted-foreground">
                    직접 입력값으로 저장하며 API 출처는 manual로 기록됩니다.
                  </p>
                )}
                <Input
                  aria-label="확정 장소명"
                  placeholder="장소명"
                  value={form.name}
                  onChange={(event) =>
                    setForm((prev) => ({ ...prev, name: event.target.value }))
                  }
                />
                <div className="grid grid-cols-2 gap-2">
                  <Input
                    aria-label="위도"
                    inputMode="decimal"
                    placeholder="위도"
                    aria-invalid={latInvalid}
                    value={form.latitude}
                    onChange={(event) =>
                      setForm((prev) => ({
                        ...prev,
                        latitude: event.target.value,
                      }))
                    }
                  />
                  <Input
                    aria-label="경도"
                    inputMode="decimal"
                    placeholder="경도"
                    aria-invalid={lngInvalid}
                    value={form.longitude}
                    onChange={(event) =>
                      setForm((prev) => ({
                        ...prev,
                        longitude: event.target.value,
                      }))
                    }
                  />
                </div>
                {latInvalid || lngInvalid ? (
                  <p className="text-xs text-destructive" role="alert">
                    위도·경도는 숫자로 입력하세요.
                  </p>
                ) : coordsOutOfKorea ? (
                  <p className="text-xs text-warning">
                    대한민국 범위를 벗어난 좌표입니다. 저장은 가능하지만 다시
                    확인하세요.
                  </p>
                ) : null}
                {/* 카테고리 드롭다운으로 강제(검색결과 카테고리는 #5에서 매핑해 미리 채움). */}
                <Select
                  value={form.categoryCode}
                  onValueChange={(value) => {
                    cancelCategoryMatch();
                    const code = value ?? "";
                    const option = (categoriesQuery.data ?? []).find(
                      (c) => c.code === code,
                    );
                    setCategoryEdited(true);
                    setForm((prev) => ({
                      ...prev,
                      categoryCode: code,
                      category: option?.label ?? prev.category,
                    }));
                  }}
                >
                  <SelectTrigger className="w-full" aria-label="카테고리">
                    <SelectValue placeholder="카테고리 선택(강제)">
                      {form.category}
                    </SelectValue>
                  </SelectTrigger>
                  <SelectContent className="max-h-72">
                    <SelectGroup>
                      {(categoriesQuery.data ?? []).map((option) => (
                        <SelectItem key={option.code} value={option.code}>
                          {option.label}
                        </SelectItem>
                      ))}
                    </SelectGroup>
                  </SelectContent>
                </Select>
                <div className="grid grid-cols-2 gap-2">
                  <Button
                    type="button"
                    disabled={!canSave || candidateActionPending}
                    onClick={() => resolveSelected("create_place")}
                  >
                    저장
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    disabled={candidateActionPending}
                    onClick={() => resolveSelected("ignore")}
                  >
                    제외
                  </Button>
                </div>
                {resolveMutation.error &&
                resolveMutation.variables?.candidateId === selected.id &&
                resolveMutation.variables.queueScope === queueScope &&
                parseNearbyPlaceConflict(resolveMutation.error) == null ? (
                  <p className="text-xs text-destructive">
                    {resolveMutation.error.message}
                  </p>
                ) : null}
              </div>

              <div
                ref={resultsRef}
                className="scroll-mt-3 flex flex-col gap-3"
              >
                {!opinionRequested ? (
                  <Button
                    type="button"
                    variant="outline"
                    className="w-full"
                    disabled={allHits.length === 0}
                    onClick={() => setOpinionRequested(true)}
                  >
                    <SparklesIcon data-icon="inline-start" />
                    AI(Gemini) 의견 요청
                  </Button>
                ) : gemini ? (
                  <GeminiCard gemini={gemini} onApply={() => applyGemini(gemini)} />
                ) : opinionQuery.isFetching ? (
                  <div className="flex items-center gap-2 rounded-xl border border-primary/40 bg-primary/5 p-3 text-sm text-muted-foreground">
                    <Loader2Icon className="size-4 animate-spin text-primary" />
                    Gemini 의견 분석 중…
                  </div>
                ) : (
                  <div className="flex flex-col gap-2">
                    <p className="flex items-center gap-1.5 rounded-xl border p-3 text-xs text-muted-foreground">
                      <SparklesIcon className="size-3.5 shrink-0" />
                      {opinionQuery.data?.error ??
                        "Gemini 의견이 없습니다."}
                    </p>
                    <Button
                      type="button"
                      size="xs"
                      variant="ghost"
                      onClick={() => opinionQuery.refetch()}
                    >
                      다시 요청
                    </Button>
                  </div>
                )}
                {PROVIDER_ORDER.map((provider) => (
                  <ProviderSection
                    key={provider}
                    label={PROVIDER_LABELS[provider]}
                    hits={result?.[provider] ?? []}
                    error={result?.errors?.[provider]}
                    loading={searchQuery.isFetching}
                    selectedHit={activeSelectedHit?.hit ?? null}
                    onSelect={selectHit}
                  />
                ))}
                {!activeQuery ? (
                  <p className="text-xs text-muted-foreground">
                    후보를 선택하면 자동 검색합니다. 직접 검색어를 입력할 수도 있습니다.
                  </p>
                ) : null}
              </div>
            </>
          ) : (
            <div className="flex flex-col gap-2 text-sm text-muted-foreground">
              <p
                role={
                  candidateLoadError
                    ? "alert"
                    : queueCompleted || candidateAdvancePending
                      ? "status"
                      : undefined
                }
              >
                {candidateLoadError
                  ? candidateLoadError
                  : candidateAdvancePending
                  ? candidateAdvanceError ?? "다음 검수 후보를 불러오는 중…"
                  : queueCompleted
                    ? "현재 표시 조건의 검수 후보를 모두 처리했습니다."
                    : "검수할 후보가 없습니다."}
              </p>
              {candidateLoadError ? (
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  onClick={retryCandidateLoad}
                >
                  검수 후보 다시 불러오기
                </Button>
              ) : candidateAdvanceError ? (
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  onClick={retryCandidateAdvance}
                >
                  다음 후보 다시 불러오기
                </Button>
              ) : null}
            </div>
          )}
        </section>
        <section className="min-h-[28rem] overflow-hidden border-t lg:min-h-0 lg:border-t-0 lg:border-l">
          <VWorldMap
            places={mapPlaces}
            selectedPlaceId={form.latitude ? 9999 : null}
            onSelectPlace={(placeId) => {
              const entry = mapHitEntries.find((item) => item.placeId === placeId);
              if (entry) selectHit(entry.hit);
            }}
          />
        </section>
      </div>

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
              actionsDisabled={candidateActionPending || detailDeletePending}
              onDeleteStarted={(candidateId) => {
                setDetailDeletePending(true);
                detailDeleteSnapshotRef.current = {
                  candidateId,
                  visibleIndex: visibleCandidates.findIndex(
                    (candidate) => candidate.id === candidateId,
                  ),
                  orderedCandidateIds: visibleCandidates.map(
                    (candidate) => candidate.id,
                  ),
                  loadedPageCount: candidatePages.length,
                  queueScope,
                  candidatesKey,
                };
              }}
              onDeleteSettled={() => setDetailDeletePending(false)}
              onDeleted={async (deletedId) => {
                const snapshot = detailDeleteSnapshotRef.current;
                await queryClient.cancelQueries({
                  queryKey: snapshot?.candidatesKey ?? candidatesKey,
                  exact: true,
                });
                queryClient.setQueryData<
                  InfiniteData<ListEnvelope<UnmatchedCandidate>>
                >(snapshot?.candidatesKey ?? candidatesKey, (old) =>
                  removeCandidatesFromQueue(old, [deletedId]),
                );
                clearProcessedCandidateParam(deletedId);
                setDetailId((current) =>
                  current === deletedId ? null : current,
                );
                if (
                  deletedId === selectedCandidateIdRef.current &&
                  snapshot?.candidateId === deletedId &&
                  snapshot.visibleIndex >= 0 &&
                  snapshot.queueScope === queueScopeRef.current
                ) {
                  advanceAfterProcessing(
                    deletedId,
                    [deletedId],
                    snapshot.visibleIndex,
                    snapshot.orderedCandidateIds,
                    snapshot.loadedPageCount,
                  );
                }
                detailDeleteSnapshotRef.current = null;
              }}
            />
          ) : null}
        </DialogContent>
      </Dialog>

      <AlertDialog
        open={nearbyConflict != null}
        onOpenChange={(open) => !open && setNearbyConflict(null)}
      >
        <AlertDialogContent className="max-w-lg">
          <AlertDialogHeader>
            <AlertDialogTitle>가까운 기존 장소를 확인하세요</AlertDialogTitle>
            <AlertDialogDescription>
              좌표가 100m 이내인 장소가 있습니다. 기존 장소에 합칠지 별도 장소로
              만들지 선택하세요.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <div
            className="rounded-lg border bg-muted/40 px-3 py-2"
            aria-label="근접 중복 확인 대상"
          >
            <p className="text-xs text-muted-foreground">확정하려는 장소</p>
            <p className="font-medium">
              {nearbyConflict?.command.form.name || "이름 없음"}
            </p>
          </div>
          <div className="flex max-h-72 flex-col gap-2 overflow-y-auto">
            {(nearbyConflict?.places ?? []).map((place) => (
              <div
                key={place.placeId}
                className="flex items-start justify-between gap-3 rounded-lg border p-3"
              >
                <div className="min-w-0 text-xs">
                  <p className="font-medium">{place.name}</p>
                  <p className="truncate text-muted-foreground">
                    {place.roadAddress ?? place.officialAddress ?? "주소 없음"}
                  </p>
                  <p className="text-muted-foreground">
                    {place.distanceMeters.toFixed(1)}m
                    {place.nameCompatible === true
                      ? " · 이름 일치"
                      : place.nameCompatible === false
                        ? " · 이름 불일치"
                        : " · 이름 비교 불가"}
                    {place.providerIdMatch === true
                      ? " · provider ID 일치"
                      : place.providerIdMatch === false
                        ? " · provider ID 불일치"
                        : " · provider ID 비교 불가"}
                  </p>
                </div>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  aria-label={`${place.name} 기존 장소에 합치기`}
                  disabled={candidateActionPending}
                  onClick={() => {
                    if (!nearbyConflict) return;
                    resolveMutation.mutate({
                      ...nearbyConflict.command,
                      duplicate: {
                        resolution: "merge_existing",
                        placeId: place.placeId,
                      },
                    });
                    setNearbyConflict(null);
                  }}
                >
                  기존 장소에 합치기
                </Button>
              </div>
            ))}
          </div>
          <AlertDialogFooter>
            <AlertDialogClose
              render={
                <Button type="button" variant="outline" size="sm">
                  취소
                </Button>
              }
            />
            <Button
              type="button"
              size="sm"
              disabled={candidateActionPending}
              onClick={() => {
                if (!nearbyConflict) return;
                resolveMutation.mutate({
                  ...nearbyConflict.command,
                  duplicate: { resolution: "create_new" },
                });
                setNearbyConflict(null);
              }}
            >
              새 장소로 만들기
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* 행 삭제 확인 — 페이지 공용 단일 다이얼로그 */}
      <AlertDialog
        open={deleteTarget != null}
        onOpenChange={(open) => !open && setDeleteTarget(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {deleteTarget?.ai_place_name} 후보를 삭제할까요?
            </AlertDialogTitle>
            <AlertDialogDescription>되돌릴 수 없습니다.</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogClose
              render={
                <Button type="button" variant="outline" size="sm">
                  취소
                </Button>
              }
            />
            <Button
              type="button"
              size="sm"
              variant="destructive"
              disabled={candidateActionPending}
              onClick={() => {
                if (deleteTarget) {
                  deleteCandidatesMutation.mutate([deleteTarget.id]);
                }
                setDeleteTarget(null);
              }}
            >
              삭제
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </AppShell>
  );
}

// 검수 대기 행 — 목록 확장 시 행 수가 많아지므로 memo로 고정해 선택/장바구니
// 토글 시 바뀐 행만 다시 그린다(콜백은 부모에서 useCallback으로 안정화).
const CandidateRow = memo(function CandidateRow({
  candidate,
  isCurrent,
  isChecked,
  inCart,
  onToggleSelect,
  onPick,
  onToggleCart,
  onOpenDetail,
  onRequestDelete,
}: {
  candidate: UnmatchedCandidate;
  isCurrent: boolean;
  isChecked: boolean;
  inCart: boolean;
  onToggleSelect: (candidateId: number) => void;
  onPick: (candidate: UnmatchedCandidate) => void;
  onToggleCart: (videoId: string) => void;
  onOpenDetail: (candidateId: number) => void;
  onRequestDelete: (candidate: UnmatchedCandidate) => void;
}) {
  const confidencePercent =
    candidate.confidence_score != null &&
    Number.isFinite(candidate.confidence_score) &&
    candidate.confidence_score >= 0 &&
    candidate.confidence_score <= 1
      ? Math.round(candidate.confidence_score * 100)
      : null;
  const isRowAction = (target: EventTarget | null) =>
    target instanceof Element && target.closest("[data-row-action]") != null;

  const handleRowClick = (event: MouseEvent<HTMLTableRowElement>) => {
    if (isRowAction(event.target)) return;
    onPick(candidate);
  };

  const handleRowKeyDown = (event: KeyboardEvent<HTMLTableRowElement>) => {
    if (isRowAction(event.target)) return;
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    onPick(candidate);
  };

  return (
    <TableRow
      data-state={isCurrent ? "selected" : undefined}
      aria-selected={isCurrent}
      tabIndex={0}
      className="group cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/30"
      onClick={handleRowClick}
      onKeyDown={handleRowKeyDown}
    >
      <TableCell>
        <Checkbox
          checked={isChecked}
          data-row-action="true"
          onCheckedChange={() => onToggleSelect(candidate.id)}
          aria-label={`${candidate.ai_place_name} 후보 선택`}
        />
      </TableCell>
      <TableCell>
        <div className="flex max-w-[16rem] flex-col gap-1 whitespace-normal text-left">
          <span className="font-bold leading-snug">{candidate.ai_place_name}</span>
          <span className="flex flex-wrap gap-1">
            {confidencePercent != null ? (
              <Badge variant="outline">매칭 신뢰도 {confidencePercent}%</Badge>
            ) : null}
            <Badge variant={queueReasonBadgeVariant(candidate.queue_reason)}>
              {queueReasonLabel(candidate.queue_reason)}
            </Badge>
          </span>
          <span className="text-[12px] text-text-secondary">
            {categoryDisplayLabel(candidate.candidate_category)}
          </span>
        </div>
      </TableCell>
      <TableCell>
        <div
          className="flex max-w-[14rem] flex-col gap-1 whitespace-normal text-left text-[12px] text-text-secondary"
          title={`영상 ID: ${candidate.video_id}`}
        >
          <span className="truncate font-medium text-foreground">
            {candidate.video_title}
          </span>
          <span className="truncate">{candidate.channel_title ?? "채널 정보 없음"}</span>
          <span className="text-left group-hover:text-primary">
            {candidate.location_hint ?? "위치 힌트 없음"}
          </span>
          <button
            type="button"
            data-row-action="true"
            className="w-fit rounded border border-surface-muted px-1.5 py-0.5 text-[11px] font-medium text-text-secondary hover:border-primary hover:text-primary"
            onClick={() => onToggleCart(candidate.video_id)}
            title="영상 재처리 선택"
          >
            {inCart ? "재처리 선택됨" : "재처리 선택"}
          </button>
        </div>
      </TableCell>
      <TableCell>
        <div className="flex flex-col gap-1">
          <Badge variant="outline">
            {candidateStatusLabel(candidate.match_status)}
          </Badge>
          {candidate.is_domestic === false ? (
            <Badge variant="outline">해외</Badge>
          ) : null}
          <span className="text-[11px] text-muted-foreground">
            {sourceKindLabel(candidate.source_kind)} · 등록 {formatDateTimeShort(candidate.created_at)}
          </span>
        </div>
      </TableCell>
      <TableCell>
        <div className="flex justify-end gap-1">
          <Button
            type="button"
            size="icon-xs"
            variant="ghost"
            data-row-action="true"
            aria-label={`${candidate.ai_place_name} 상세`}
            onClick={() => onOpenDetail(candidate.id)}
          >
            <InfoIcon className="size-4" />
          </Button>
          <Button
            type="button"
            size="icon-xs"
            variant="destructive"
            data-row-action="true"
            aria-label={`${candidate.ai_place_name} 후보 삭제`}
            onClick={() => onRequestDelete(candidate)}
          >
            <Trash2Icon className="size-4" />
          </Button>
        </div>
      </TableCell>
    </TableRow>
  );
});

function reprocessStageLabel(stage: ReprocessStage) {
  if (stage === "correction") return "교정부터";
  if (stage === "poi") return "POI 추출부터";
  return "자막 수집부터";
}

function groupDimLabel(dim: DestinationGroupDim) {
  if (dim === "channel") return "유튜버별";
  if (dim === "playlist") return "재생목록별";
  if (dim === "keyword") return "검색어별";
  return "전체";
}

function groupOptions(
  dim: DestinationGroupDim,
  facets: DestinationFacets | undefined,
): { value: string; label: string; count: number }[] {
  if (!facets) return [];
  if (dim === "channel")
    return facets.channels.map((c) => ({
      value: c.id,
      label: c.title,
      count: c.place_count,
    }));
  if (dim === "playlist")
    return facets.playlists.map((p) => ({
      value: p.id,
      label: p.title,
      count: p.place_count,
    }));
  if (dim === "keyword")
    return facets.keywords.map((k) => ({
      value: k.value,
      label: k.value,
      count: k.place_count,
    }));
  return [];
}

function groupValueLabel(
  dim: DestinationGroupDim,
  value: string | null,
  facets: DestinationFacets | undefined,
) {
  if (!value) return "";
  const option = groupOptions(dim, facets).find((opt) => opt.value === value);
  return option ? `${option.label} (${option.count})` : value;
}

function GeminiCard({
  gemini,
  onApply,
}: {
  gemini: PlaceOpinion;
  onApply: () => void;
}) {
  return (
    <div className="flex flex-col gap-1.5 rounded-xl border border-primary/40 bg-primary/5 p-3">
      <div className="flex items-center justify-between gap-2">
        <p className="flex items-center gap-1.5 text-sm font-medium">
          <SparklesIcon className="size-4 text-primary" />
          Gemini 의견
        </p>
        {gemini.confidence != null ? (
          <Badge variant="outline">
            신뢰도 {Math.round(gemini.confidence * 100)}%
          </Badge>
        ) : null}
      </div>
      <p className="text-sm font-medium">{gemini.best_name ?? "-"}</p>
      {gemini.reason ? (
        <p className="text-xs text-muted-foreground">{gemini.reason}</p>
      ) : null}
      {gemini.latitude != null && gemini.longitude != null ? (
        <Button type="button" size="xs" variant="outline" onClick={onApply}>
          이 결과 사용
        </Button>
      ) : null}
    </div>
  );
}

function ProviderSection({
  label,
  hits,
  error,
  loading,
  selectedHit,
  onSelect,
}: {
  label: string;
  hits: PlaceSearchHit[];
  error?: string;
  loading: boolean;
  selectedHit: PlaceSearchHit | null;
  onSelect: (hit: PlaceSearchHit) => void;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs font-semibold">{label}</p>
        <Badge variant="outline">{hits.length}</Badge>
      </div>
      {error ? (
        <p className="text-xs text-destructive">{error}</p>
      ) : hits.length === 0 ? (
        <p className="rounded-lg border p-2 text-xs text-muted-foreground">
          {loading ? "검색 중…" : "결과 없음"}
        </p>
      ) : (
        hits.map((hit, index) => {
          const hasCoords = hit.latitude != null && hit.longitude != null;
          const storageBlockReason = placeHitStorageBlockReason(hit);
          const selectable = hasCoords && storageBlockReason == null;
          const isSelected = selectedHit === hit;
          return (
            <button
              key={`${hit.provider}-${hit.native_id ?? index}`}
              type="button"
              disabled={!selectable}
              aria-pressed={isSelected}
              title={storageBlockReason ?? undefined}
              onClick={() => onSelect(hit)}
              className="flex flex-col gap-0.5 rounded-lg border p-2 text-left text-xs transition-colors hover:border-primary hover:bg-muted aria-pressed:border-primary aria-pressed:bg-primary/5 disabled:cursor-not-allowed disabled:opacity-60"
            >
              <span className="flex items-center justify-between gap-2">
                <span className="truncate font-medium">{hit.name}</span>
                {hit.category ? (
                  <span className="shrink-0 text-muted-foreground">
                    {hit.category}
                  </span>
                ) : null}
              </span>
              <span className="truncate text-muted-foreground">
                {hit.road_address ?? hit.address ?? "-"}
              </span>
              <span className="text-muted-foreground">
                {hasCoords
                  ? `${hit.latitude!.toFixed(5)}, ${hit.longitude!.toFixed(5)}`
                  : "좌표 없음(선택 불가)"}
              </span>
              {storageBlockReason ? (
                <span className="text-warning">{storageBlockReason}</span>
              ) : null}
            </button>
          );
        })
      )}
    </div>
  );
}
