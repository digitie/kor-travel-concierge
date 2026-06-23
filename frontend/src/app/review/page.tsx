"use client";

import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ExternalLinkIcon,
  InfoIcon,
  Loader2Icon,
  MapPinIcon,
  SearchIcon,
  SparklesIcon,
  SquareIcon,
} from "lucide-react";

import {
  getPlaceOpinion,
  listUnmatchedCandidates,
  resolveCandidate,
  searchPlaces,
  type DestinationSummary,
  type PlaceOpinion,
  type PlaceSearchHit,
  type UnmatchedCandidate,
} from "@/lib/api";
import { useIsMobile } from "@/lib/use-is-mobile";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { AppNav } from "@/components/AppNav";
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
  const candidatesQuery = useQuery({
    queryKey: ["unmatched-candidates"],
    queryFn: listUnmatchedCandidates,
    refetchInterval: 15_000,
  });
  const candidates = useMemo(
    () => candidatesQuery.data ?? [],
    [candidatesQuery.data],
  );
  const [selectedId, setSelectedId] = useState<number | null>(null);
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
    setForm({ name: "", latitude: "", longitude: "", category: "" });
  }
  function selectHit(hit: PlaceSearchHit) {
    setForm({
      name: hit.name,
      latitude: String(hit.latitude),
      longitude: String(hit.longitude),
      category: hit.category ?? "",
    });
  }
  function applyGemini(gemini: PlaceOpinion) {
    setForm((prev) => ({
      name: gemini.best_name ?? prev.name,
      latitude: gemini.latitude != null ? String(gemini.latitude) : prev.latitude,
      longitude:
        gemini.longitude != null ? String(gemini.longitude) : prev.longitude,
      category: gemini.category ?? prev.category,
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
      });
    },
    onMutate: async () => {
      // 저장/제외 즉시 검수 대기 목록에서 제거(낙관적) — 응답 round-trip을 기다리지
      // 않고 사라진다. 진행 중 자동 refetch(15s)가 덮어쓰지 않도록 먼저 취소하고,
      // 실패 시 onError에서 원래 목록을 복구한다.
      const removedId = selected?.id ?? null;
      await queryClient.cancelQueries({ queryKey: ["unmatched-candidates"] });
      const previous = queryClient.getQueryData<UnmatchedCandidate[]>([
        "unmatched-candidates",
      ]);
      if (removedId != null) {
        queryClient.setQueryData<UnmatchedCandidate[]>(
          ["unmatched-candidates"],
          (old) => (old ?? []).filter((c) => c.id !== removedId),
        );
      }
      return { previous };
    },
    onError: (_error, _action, context) => {
      if (context?.previous) {
        queryClient.setQueryData(["unmatched-candidates"], context.previous);
      }
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["destinations"] });
      setForm({ name: "", latitude: "", longitude: "", category: "" });
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
    <main className="flex min-h-screen flex-col bg-background">
      <AppNav />
      <header className="flex items-center justify-between gap-3 border-b px-5 py-2.5">
        <div className="flex items-center gap-3">
          <h1 className="text-base font-semibold">검수 큐</h1>
          <Badge variant="secondary">{candidates.length}</Badge>
        </div>
        <p className="hidden text-xs text-muted-foreground sm:block">
          Google·Kakao·Naver 검색과 Gemini 의견을 비교해 위치를 확정합니다.
        </p>
      </header>

      <div className="grid flex-1 grid-cols-1 lg:grid-cols-[18rem_1fr]">
        <aside className="flex max-h-[40vh] flex-col gap-1 overflow-y-auto border-b p-3 lg:max-h-none lg:border-b-0 lg:border-r">
          <p className="px-1 pb-1 text-xs font-medium text-muted-foreground">
            검수 대기 후보
          </p>
          {candidates.length === 0 ? (
            <p className="rounded-lg border p-3 text-xs text-muted-foreground">
              검수할 후보가 없습니다.
            </p>
          ) : (
            candidates.map((candidate) => (
              <div
                key={candidate.id}
                data-selected={candidate.id === selected?.id}
                className="flex items-center gap-1 rounded-lg border p-1 transition-colors hover:bg-muted data-[selected=true]:border-primary data-[selected=true]:bg-primary/5"
              >
                <button
                  type="button"
                  onClick={() => pickCandidate(candidate)}
                  className="flex min-w-0 flex-1 flex-col gap-0.5 px-1.5 py-1 text-left text-sm"
                >
                  <span className="truncate font-medium">
                    {candidate.ai_place_name}
                  </span>
                  <span className="truncate text-xs text-muted-foreground">
                    {candidate.location_hint ?? candidate.video_id}
                  </span>
                </button>
                <Button
                  type="button"
                  size="icon"
                  variant="ghost"
                  aria-label={`${candidate.ai_place_name} 상세`}
                  onClick={() => openDetail(candidate.id)}
                >
                  <InfoIcon className="size-4" />
                </Button>
              </div>
            ))
          )}
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

              <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_1fr]">
                <div className="flex flex-col gap-3">
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

                <div className="flex flex-col gap-3">
                  <div className="h-72 overflow-hidden rounded-xl border">
                    <VWorldMap
                      places={mapPlaces}
                      selectedPlaceId={form.latitude ? 9999 : null}
                      onSelectPlace={(placeId) => {
                        const place = mapPlaces.find(
                          (p) => p.place_id === placeId,
                        );
                        if (place && place.place_id !== 9999) {
                          setForm({
                            name: place.name,
                            latitude: String(place.latitude),
                            longitude: String(place.longitude),
                            category: place.category ?? "",
                          });
                        }
                      }}
                    />
                  </div>

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
                    <Input
                      aria-label="카테고리"
                      placeholder="카테고리"
                      value={form.category}
                      onChange={(event) =>
                        setForm((prev) => ({
                          ...prev,
                          category: event.target.value,
                        }))
                      }
                    />
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
                </div>
              </div>
            </>
          ) : (
            <p className="text-sm text-muted-foreground">
              검수할 후보가 없습니다.
            </p>
          )}
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
              onDeleted={() => setDetailId(null)}
            />
          ) : null}
        </DialogContent>
      </Dialog>
    </main>
  );
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
