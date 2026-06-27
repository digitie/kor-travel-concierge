"use client";

import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
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
  listUnmatchedCandidates,
  reprocessVideos,
  resolveCandidate,
  searchPlaces,
  type DestinationFacets,
  type DestinationFilter,
  type DestinationGroupDim,
  type DestinationSummary,
  type PlaceOpinion,
  type PlaceSearchHit,
  type ReprocessStage,
  type UnmatchedCandidate,
} from "@/lib/api";
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
import { AppShell } from "@/components/AppShell";
import { CandidateDetailView } from "@/components/CandidateDetailView";
import { VWorldMap } from "@/components/VWorldMap";

const PROVIDER_LABELS: Record<string, string> = {
  google: "Google Places",
  kakao: "Kakao",
  naver: "Naver",
};
const PROVIDER_ORDER = ["google", "kakao", "naver"] as const;

function hitPlace(hit: PlaceSearchHit, placeId: number): DestinationSummary {
  return {
    place_id: placeId,
    name: hit.name,
    description: null,
    gemini_enriched_description: null,
    latitude: hit.latitude ?? 0,
    longitude: hit.longitude ?? 0,
    category: hit.category,
    official_address: hit.road_address ?? hit.address,
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
    () => ["unmatched-candidates", groupDim, groupValue] as const,
    [groupDim, groupValue],
  );
  const candidatesQuery = useQuery({
    queryKey: candidatesKey,
    queryFn: () => listUnmatchedCandidates(filter),
    refetchInterval: 15_000,
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
  function toggleCart(videoId: string) {
    setCart((prev) =>
      prev.includes(videoId)
        ? prev.filter((v) => v !== videoId)
        : [...prev, videoId],
    );
  }
  const reprocessMutation = useMutation({
    mutationFn: () => reprocessVideos(cart, reprocessStage),
    onSuccess: () => {
      setCart([]);
    },
  });
  const candidates = useMemo(
    () => candidatesQuery.data ?? [],
    [candidatesQuery.data],
  );
  // 해외 후보 숨기기 토글 적용(장바구니/그룹 필터는 그대로 — 순수 표시 필터).
  const visibleCandidates = useMemo(
    () =>
      hideForeign
        ? candidates.filter((c) => c.is_domestic !== false)
        : candidates,
    [candidates, hideForeign],
  );
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
  function toggleCandidateSelection(candidateId: number) {
    setSelectedCandidateIds((current) =>
      current.includes(candidateId)
        ? current.filter((id) => id !== candidateId)
        : [...current, candidateId],
    );
  }
  function toggleAllVisibleCandidates() {
    setSelectedCandidateIds((current) =>
      allVisibleCandidatesSelected
        ? current.filter((id) => !visibleCandidateIds.has(id))
        : Array.from(new Set([...current, ...visibleCandidates.map((c) => c.id)])),
    );
  }
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const deleteCandidatesMutation = useMutation({
    mutationFn: async (ids: number[]) => {
      await Promise.all(ids.map((id) => deleteCandidate(id)));
      return ids;
    },
    onMutate: async (ids) => {
      await queryClient.cancelQueries({ queryKey: ["unmatched-candidates"] });
      const previous =
        queryClient.getQueryData<UnmatchedCandidate[]>(candidatesKey);
      queryClient.setQueryData<UnmatchedCandidate[]>(
        candidatesKey,
        (old) => (old ?? []).filter((candidate) => !ids.includes(candidate.id)),
      );
      setSelectedCandidateIds((current) =>
        current.filter((id) => !ids.includes(id)),
      );
      if (selectedId != null && ids.includes(selectedId)) {
        setSelectedId(null);
      }
      return { previous };
    },
    onError: (_error, _ids, context) => {
      if (context?.previous) {
        queryClient.setQueryData(candidatesKey, context.previous);
      }
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["unmatched-candidates"] });
    },
  });

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
    setGroupDim("none");
    setGroupValue(null);
    setSelectedId(candidateId);
  }, [setGroupDim, setGroupValue]);
  /* eslint-enable react-hooks/set-state-in-effect */

  const selected = useMemo(
    () => candidates.find((c) => c.id === selectedId) ?? candidates[0] ?? null,
    [candidates, selectedId],
  );

  const [queryEdit, setQueryEdit] = useState<string | null>(null);
  const [activeQuery, setActiveQuery] = useState("");
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
    ],
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

  const [form, setForm] = useState({
    name: "",
    latitude: "",
    longitude: "",
    category: "",
    // 강제 카테고리 코드(드롭다운). category(label)는 코드 선택 시 함께 채운다.
    categoryCode: "",
  });

  function runSearch() {
    if (query.trim()) {
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
    setOpinionRequested(false);
    setActiveQuery("");
  }
  // 검수 상세: 모바일=새 페이지, PC=모달.
  function openDetail(candidateId: number) {
    if (isMobile) {
      router.push(`/review/${candidateId}`);
    } else {
      setDetailId(candidateId);
    }
  }
  function pickCandidate(candidate: UnmatchedCandidate) {
    // 검색 진행 중 다른 후보로 전환하면 진행 중 요청을 취소하고(이전 검색 결과가
    // 새 후보에 매달리지 않도록) nonce를 올려 새 후보 검색을 깨끗하게 시작한다.
    void queryClient.cancelQueries({ queryKey: ["place-search"] });
    void queryClient.cancelQueries({ queryKey: ["place-opinion"] });
    setSelectedId(candidate.id);
    setQueryEdit(null);
    setOpinionRequested(false);
    setSearchNonce((n) => n + 1);
    setActiveQuery(buildHintedQuery(candidate));
    setForm({ name: "", latitude: "", longitude: "", category: "", categoryCode: "" });
  }
  function selectHit(hit: PlaceSearchHit) {
    setForm((prev) => ({
      ...prev,
      name: hit.name,
      latitude: String(hit.latitude),
      longitude: String(hit.longitude),
    }));
    // #5: 검색결과 카테고리를 카탈로그 8자리 코드로 근사 매핑해 드롭다운을 미리 채운다.
    // 사용자가 이미 카테고리를 고른 경우(categoryCode 존재)는 덮어쓰지 않는다(드롭다운으로 변경 가능).
    if (hit.category) {
      void matchCategory(hit.category)
        .then((match) => {
          if (!match) return;
          setForm((prev) =>
            prev.categoryCode
              ? prev
              : { ...prev, categoryCode: match.code, category: match.label },
          );
        })
        .catch(() => {});
    }
  }
  function applyGemini(gemini: PlaceOpinion) {
    // Gemini 의견도 카테고리는 덮어쓰지 않는다(드롭다운이 단일 출처).
    setForm((prev) => ({
      ...prev,
      name: gemini.best_name ?? prev.name,
      latitude: gemini.latitude != null ? String(gemini.latitude) : prev.latitude,
      longitude:
        gemini.longitude != null ? String(gemini.longitude) : prev.longitude,
    }));
  }

  const mapPlaces = useMemo<DestinationSummary[]>(() => {
    const hits = [
      ...(result?.google ?? []),
      ...(result?.kakao ?? []),
      ...(result?.naver ?? []),
    ]
      .filter((h) => h.latitude != null && h.longitude != null)
      .map((h, i) => hitPlace(h, i + 1));
    const lat = Number(form.latitude);
    const lng = Number(form.longitude);
    if (Number.isFinite(lat) && Number.isFinite(lng) && form.latitude) {
      hits.unshift(
        hitPlace(
          {
            provider: "선택",
            name: form.name || "선택 위치",
            address: null,
            road_address: null,
            latitude: lat,
            longitude: lng,
            category: form.category || null,
          },
          9999,
        ),
      );
    }
    return hits;
  }, [result, form]);

  const resolveMutation = useMutation({
    mutationFn: (action: "create_place" | "ignore") => {
      if (!selected) {
        throw new Error("검수할 후보가 없습니다.");
      }
      if (action === "ignore") {
        return resolveCandidate(selected.id, {
          action: "ignore",
          reviewNote: "검수 페이지 제외",
        });
      }
      return resolveCandidate(selected.id, {
        action: "create_place",
        correctedName: form.name,
        latitude: Number(form.latitude),
        longitude: Number(form.longitude),
        category: form.category || undefined,
        categoryCode: form.categoryCode || undefined,
      });
    },
    onMutate: async () => {
      // 저장/제외 즉시 검수 대기 목록에서 제거(낙관적) — 응답 round-trip을 기다리지
      // 않고 사라진다. 진행 중 자동 refetch(15s)가 덮어쓰지 않도록 먼저 취소하고,
      // 실패 시 onError에서 원래 목록을 복구한다.
      const removedId = selected?.id ?? null;
      await queryClient.cancelQueries({ queryKey: ["unmatched-candidates"] });
      const previous =
        queryClient.getQueryData<UnmatchedCandidate[]>(candidatesKey);
      if (removedId != null) {
        queryClient.setQueryData<UnmatchedCandidate[]>(
          candidatesKey,
          (old) => (old ?? []).filter((c) => c.id !== removedId),
        );
      }
      return { previous };
    },
    onError: (_error, _action, context) => {
      if (context?.previous) {
        queryClient.setQueryData(candidatesKey, context.previous);
      }
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["destinations"] });
      setForm({ name: "", latitude: "", longitude: "", category: "", categoryCode: "" });
      setQueryEdit(null);
      setActiveQuery("");
      setSelectedId(null);
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["unmatched-candidates"] });
    },
  });

  const canSave =
    Boolean(form.name.trim()) &&
    Number.isFinite(Number(form.latitude)) &&
    Number.isFinite(Number(form.longitude)) &&
    Boolean(form.latitude) &&
    Boolean(form.longitude);

  return (
    <AppShell
      title="검수 큐"
      description="Google, Kakao, Naver 검색과 Gemini 의견을 비교해 후보 위치를 확정합니다."
      section="검수"
      actions={<Badge variant="secondary">{candidates.length}개 대기</Badge>}
      contentClassName="flex min-h-0 flex-1 flex-col p-0"
    >
      <div className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-3">
        <aside className="flex min-h-0 max-h-[48vh] flex-col gap-2 border-b p-3 lg:max-h-none lg:border-r lg:border-b-0">
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
                onValueChange={(value) => setGroupValue(value || null)}
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
              <Button
                type="button"
                size="xs"
                variant="destructive"
                disabled={deleteCandidatesMutation.isPending}
                onClick={() => {
                  if (
                    window.confirm(
                      `선택한 후보 ${selectedCandidateIds.length}개를 삭제할까요?`,
                    )
                  ) {
                    deleteCandidatesMutation.mutate(selectedCandidateIds);
                  }
                }}
              >
                <Trash2Icon data-icon="inline-start" />
                선택 삭제
              </Button>
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
            <input
              type="checkbox"
              className="size-3.5 rounded border"
              checked={hideForeign}
              onChange={(event) => setHideForeign(event.target.checked)}
            />
            해외(국내 아님) 후보 숨기기
          </label>
          <div className="min-h-0 flex-1 overflow-y-auto">
            {visibleCandidates.length === 0 ? (
              <p className="rounded-lg border p-3 text-xs text-muted-foreground">
                검수할 후보가 없습니다.
              </p>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-10">
                      <input
                        type="checkbox"
                        className="size-4 rounded border"
                        checked={allVisibleCandidatesSelected}
                        onChange={toggleAllVisibleCandidates}
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
                    <TableRow
                      key={candidate.id}
                      data-state={candidate.id === selected?.id ? "selected" : undefined}
                    >
                      <TableCell>
                        <input
                          type="checkbox"
                          className="size-4 rounded border"
                          checked={selectedCandidateSet.has(candidate.id)}
                          onChange={() => toggleCandidateSelection(candidate.id)}
                          aria-label={`${candidate.ai_place_name} 후보 선택`}
                        />
                      </TableCell>
                      <TableCell>
                        <button
                          type="button"
                          onClick={() => pickCandidate(candidate)}
                          className="flex max-w-[16rem] flex-col gap-1 whitespace-normal text-left"
                        >
                          <span className="font-bold leading-snug">
                            {candidate.ai_place_name}
                          </span>
                          <span className="text-[12px] text-text-secondary">
                            {candidate.candidate_category ?? "카테고리 없음"}
                          </span>
                        </button>
                      </TableCell>
                      <TableCell>
                        <button
                          type="button"
                          className="flex max-w-[14rem] flex-col gap-1 whitespace-normal text-left text-[12px] text-text-secondary"
                          onClick={() => toggleCart(candidate.video_id)}
                          title="영상 재처리 선택"
                        >
                          <span>{candidate.location_hint ?? "위치 힌트 없음"}</span>
                          <span className="font-mono">
                            {cartSet.has(candidate.video_id) ? "재처리 선택됨" : candidate.video_id}
                          </span>
                        </button>
                      </TableCell>
                      <TableCell>
                        <div className="flex flex-col gap-1">
                          <Badge variant="outline">{candidate.match_status}</Badge>
                          {candidate.is_domestic === false ? (
                            <Badge variant="outline">해외</Badge>
                          ) : null}
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className="flex justify-end gap-1">
                          <Button
                            type="button"
                            size="icon-xs"
                            variant="ghost"
                            aria-label={`${candidate.ai_place_name} 상세`}
                            onClick={() => openDetail(candidate.id)}
                          >
                            <InfoIcon className="size-4" />
                          </Button>
                          <Button
                            type="button"
                            size="icon-xs"
                            variant="destructive"
                            aria-label={`${candidate.ai_place_name} 후보 삭제`}
                            disabled={deleteCandidatesMutation.isPending}
                            onClick={() => {
                              if (window.confirm("이 검수 후보를 삭제할까요?")) {
                                deleteCandidatesMutation.mutate([candidate.id]);
                              }
                            }}
                          >
                            <Trash2Icon className="size-4" />
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </div>
        </aside>

        <section className="flex flex-col gap-4 overflow-y-auto p-5">
          {selected ? (
            <>
              <div className="flex flex-col gap-2 rounded-xl border p-4">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-semibold">
                    {selected.ai_place_name}
                  </span>
                  {selected.candidate_category ? (
                    <Badge variant="outline">{selected.candidate_category}</Badge>
                  ) : null}
                  <Badge variant="secondary">{selected.match_status}</Badge>
                </div>
                {selected.location_hint ? (
                  <p className="text-xs text-muted-foreground">
                    위치 힌트: {selected.location_hint}
                  </p>
                ) : null}
                <div className="flex flex-wrap items-center gap-3">
                  <a
                    href={`https://www.youtube.com/watch?v=${selected.video_id}`}
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
                    value={form.longitude}
                    onChange={(event) =>
                      setForm((prev) => ({
                        ...prev,
                        longitude: event.target.value,
                      }))
                    }
                  />
                </div>
                {/* 카테고리 드롭다운으로 강제(검색결과 카테고리는 #5에서 매핑해 미리 채움). */}
                <Select
                  value={form.categoryCode}
                  onValueChange={(value) => {
                    const code = value ?? "";
                    const option = (categoriesQuery.data ?? []).find(
                      (c) => c.code === code,
                    );
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
                    disabled={!canSave || resolveMutation.isPending}
                    onClick={() => resolveMutation.mutate("create_place")}
                  >
                    저장
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    disabled={resolveMutation.isPending}
                    onClick={() => resolveMutation.mutate("ignore")}
                  >
                    제외
                  </Button>
                </div>
                {resolveMutation.error ? (
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
            <p className="text-sm text-muted-foreground">
              검수할 후보가 없습니다.
            </p>
          )}
        </section>
        <section className="min-h-[28rem] border-t lg:min-h-0 lg:border-t-0 lg:border-l">
          <VWorldMap
            places={mapPlaces}
            selectedPlaceId={form.latitude ? 9999 : null}
            onSelectPlace={(placeId) => {
              const place = mapPlaces.find((p) => p.place_id === placeId);
              if (place && place.place_id !== 9999) {
                setForm((prev) => ({
                  ...prev,
                  name: place.name,
                  latitude: String(place.latitude),
                  longitude: String(place.longitude),
                }));
              }
            }}
          />
        </section>
      </div>

      <Dialog
        open={detailId != null}
        onOpenChange={(open) => !open && setDetailId(null)}
      >
        <DialogContent className="max-h-[85vh] max-w-2xl overflow-y-auto">
          <DialogHeader>
            <DialogTitle>검수 후보 상세</DialogTitle>
          </DialogHeader>
          {detailId != null ? (
            <CandidateDetailView
              candidateId={detailId}
              onDeleted={() => {
                setDetailId(null);
                if (detailId === selectedId) {
                  setSelectedId(null);
                }
              }}
            />
          ) : null}
        </DialogContent>
      </Dialog>
    </AppShell>
  );
}

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
  onSelect,
}: {
  label: string;
  hits: PlaceSearchHit[];
  error?: string;
  loading: boolean;
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
          return (
            <button
              key={`${label}-${index}`}
              type="button"
              disabled={!hasCoords}
              onClick={() => onSelect(hit)}
              className="flex flex-col gap-0.5 rounded-lg border p-2 text-left text-xs transition-colors hover:border-primary hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50"
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
            </button>
          );
        })
      )}
    </div>
  );
}
