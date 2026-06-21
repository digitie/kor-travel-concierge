"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowDownUpIcon,
  DownloadIcon,
  FlaskConicalIcon,
  InfoIcon,
  ListChecksIcon,
  MapPinIcon,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import {
  buildDestinationExportUrl,
  listDestinations,
  listRunQueue,
  triggerDeepResearch,
  USER_JOB_TYPES,
  type CrawlRunSummary,
  type DestinationExportFormat,
  type DestinationSort,
  type DestinationSummary,
  type PlaceSourceVideo,
} from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useIsMobile } from "@/lib/use-is-mobile";
import { PlaceDetailView } from "@/components/PlaceDetailView";
import { VWorldMap } from "@/components/VWorldMap";

export function DestinationWorkspace() {
  const queryClient = useQueryClient();
  const [selectedPlaceId, setSelectedPlaceId] = useState<number | null>(null);
  const [destinationSort, setDestinationSort] = useState<DestinationSort>("mention_count");
  const [exportFormat, setExportFormat] = useState<DestinationExportFormat>("xlsx");
  const [selectedExportIds, setSelectedExportIds] = useState<number[]>([]);

  const destinationsQuery = useQuery({
    queryKey: ["destinations", destinationSort],
    queryFn: () => listDestinations(destinationSort),
    refetchInterval: 10_000,
  });
  const runQueueQuery = useQuery({
    queryKey: ["run-queue", "user"],
    queryFn: () => listRunQueue(USER_JOB_TYPES),
    refetchInterval: 3_000,
  });

  const router = useRouter();
  const isMobile = useIsMobile();
  const [detailPlaceId, setDetailPlaceId] = useState<number | null>(null);
  // 장소 상세: 모바일=새 페이지, PC=모달.
  function openPlaceDetail(placeId: number) {
    if (isMobile) {
      router.push(`/place/${placeId}`);
    } else {
      setDetailPlaceId(placeId);
    }
  }

  const places = useMemo(() => destinationsQuery.data ?? [], [destinationsQuery.data]);
  const selectedPlace = useMemo(
    () => places.find((place) => place.place_id === selectedPlaceId) ?? places[0] ?? null,
    [places, selectedPlaceId],
  );
  const visiblePlaceIds = useMemo(
    () => new Set(places.map((place) => place.place_id)),
    [places],
  );
  const selectedVisibleExportIds = useMemo(
    () => selectedExportIds.filter((placeId) => visiblePlaceIds.has(placeId)),
    [selectedExportIds, visiblePlaceIds],
  );
  const selectedExportIdSet = useMemo(
    () => new Set(selectedVisibleExportIds),
    [selectedVisibleExportIds],
  );
  const isAllSelected =
    places.length > 0 && selectedVisibleExportIds.length === places.length;

  const deepResearchMutation = useMutation({
    mutationFn: triggerDeepResearch,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["runs"] }),
  });

  function toggleExportSelection(placeId: number) {
    setSelectedExportIds((current) =>
      current.includes(placeId)
        ? current.filter((id) => id !== placeId)
        : [...current, placeId],
    );
  }

  function toggleAllExportSelection() {
    setSelectedExportIds(isAllSelected ? [] : places.map((place) => place.place_id));
  }

  function exportPlaces() {
    window.location.assign(
      buildDestinationExportUrl({
        format: exportFormat,
        placeIds: selectedVisibleExportIds,
        sort: destinationSort,
      }),
    );
  }

  return (
    <div className="flex h-full min-h-[calc(100vh-3rem)] flex-col bg-background">
      <RunQueueStatus runs={runQueueQuery.data ?? []} />
      {/* 장소(지도 왼쪽, 좁은 칼럼) + 지도 */}
      <div className="grid min-h-[30rem] flex-1 grid-cols-1 lg:grid-cols-[0.7fr_1.6fr]">
        <div className="flex min-h-[22rem] flex-col overflow-y-auto border-b lg:border-b-0 lg:border-r">
          <DestinationList
            places={places}
            selectedPlace={selectedPlace}
            isLoading={destinationsQuery.isLoading}
            onSelect={setSelectedPlaceId}
            onDeepResearch={(placeId) => deepResearchMutation.mutate(placeId)}
            isResearching={deepResearchMutation.isPending}
            researchError={deepResearchMutation.error?.message ?? null}
            sort={destinationSort}
            onSortChange={setDestinationSort}
            exportFormat={exportFormat}
            onExportFormatChange={setExportFormat}
            selectedExportIds={selectedExportIdSet}
            selectedExportCount={selectedVisibleExportIds.length}
            isAllSelected={isAllSelected}
            onToggleExportSelection={toggleExportSelection}
            onToggleAllExportSelection={toggleAllExportSelection}
            onExport={exportPlaces}
            onShowDetail={openPlaceDetail}
          />
        </div>
        <div className="min-h-[22rem]">
          <VWorldMap
            places={places}
            selectedPlaceId={selectedPlace?.place_id ?? null}
            onSelectPlace={setSelectedPlaceId}
          />
        </div>
      </div>

      <Dialog
        open={detailPlaceId != null}
        onOpenChange={(open) => !open && setDetailPlaceId(null)}
      >
        <DialogContent className="max-h-[85vh] max-w-2xl overflow-y-auto">
          <DialogHeader>
            <DialogTitle>장소 상세</DialogTitle>
          </DialogHeader>
          {detailPlaceId != null ? (
            <PlaceDetailView placeId={detailPlaceId} />
          ) : null}
        </DialogContent>
      </Dialog>
    </div>
  );
}

// 결과 페이지 상단의 간단한 실행 큐 상태 바(상세 관리는 /collect).
function RunQueueStatus({ runs }: { runs: CrawlRunSummary[] }) {
  const running = runs.filter((run) => run.state === "running");
  const pending = runs.filter((run) => run.state === "pending");
  const current = running[0] ?? pending[0] ?? null;
  return (
    <div className="flex flex-wrap items-center gap-2 border-b bg-muted/30 px-4 py-2 text-xs">
      <ListChecksIcon className="size-4 text-muted-foreground" />
      <span className="font-semibold">실행 큐</span>
      <Badge variant="secondary">실행 {running.length}</Badge>
      <Badge variant="outline">대기 {pending.length}</Badge>
      {current ? (
        <span className="flex min-w-0 items-center gap-1.5">
          <span className="font-medium">
            {current.target_label ?? current.target_id ?? "진행 중"}
          </span>
          <span className="truncate text-muted-foreground">
            {current.current_message ?? ""}
          </span>
        </span>
      ) : (
        <span className="text-muted-foreground">유휴 상태</span>
      )}
      <Link
        href="/collect"
        className="ml-auto whitespace-nowrap font-medium text-primary hover:underline"
      >
        수집 관리 →
      </Link>
    </div>
  );
}

function DestinationList({
  places,
  selectedPlace,
  isLoading,
  onSelect,
  onDeepResearch,
  isResearching,
  researchError,
  sort,
  onSortChange,
  exportFormat,
  onExportFormatChange,
  selectedExportIds,
  selectedExportCount,
  isAllSelected,
  onToggleExportSelection,
  onToggleAllExportSelection,
  onExport,
  onShowDetail,
}: {
  places: DestinationSummary[];
  selectedPlace: DestinationSummary | null;
  isLoading: boolean;
  onSelect: (placeId: number) => void;
  onDeepResearch: (placeId: number) => void;
  isResearching: boolean;
  researchError: string | null;
  sort: DestinationSort;
  onSortChange: (sort: DestinationSort) => void;
  exportFormat: DestinationExportFormat;
  onExportFormatChange: (format: DestinationExportFormat) => void;
  selectedExportIds: Set<number>;
  selectedExportCount: number;
  isAllSelected: boolean;
  onToggleExportSelection: (placeId: number) => void;
  onToggleAllExportSelection: () => void;
  onExport: () => void;
  onShowDetail: (placeId: number) => void;
}) {
  // 선택된 장소의 행 DOM을 참조해 마커 클릭 시 목록에서 보이도록 스크롤한다.
  const rowRefs = useRef<Map<number, HTMLDivElement | null>>(new Map());
  const selectedPlaceId = selectedPlace?.place_id ?? null;

  useEffect(() => {
    if (selectedPlaceId == null) {
      return;
    }
    rowRefs.current.get(selectedPlaceId)?.scrollIntoView({
      behavior: "smooth",
      block: "nearest",
    });
  }, [selectedPlaceId]);

  return (
    <section aria-label="장소 목록" className="flex flex-col gap-4 p-4">
      <PanelHeader title="장소" count={places.length} />
      <div className="grid grid-cols-2 gap-2">
        <Select value={sort} onValueChange={(value) => onSortChange(value as DestinationSort)}>
          <SelectTrigger id="destination-sort-select" className="w-full" aria-label="장소 정렬">
            <ArrowDownUpIcon className="size-4 text-muted-foreground" />
            <SelectValue>{sortLabel(sort)}</SelectValue>
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              <SelectItem value="mention_count">언급 많은 순</SelectItem>
              <SelectItem value="latest">최신 등록 순</SelectItem>
              <SelectItem value="name">이름 순</SelectItem>
              <SelectItem value="category">카테고리 순</SelectItem>
            </SelectGroup>
          </SelectContent>
        </Select>
        <Select
          value={exportFormat}
          onValueChange={(value) =>
            onExportFormatChange(value as DestinationExportFormat)
          }
        >
          <SelectTrigger id="destination-export-format" className="w-full" aria-label="내보내기 형식">
            <SelectValue>{exportFormat.toUpperCase()}</SelectValue>
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              <SelectItem value="xlsx">XLSX</SelectItem>
              <SelectItem value="gpx">GPX</SelectItem>
              <SelectItem value="kml">KML</SelectItem>
            </SelectGroup>
          </SelectContent>
        </Select>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <Button type="button" variant="outline" onClick={onToggleAllExportSelection}>
          {isAllSelected ? "선택 해제" : "전체 선택"}
        </Button>
        <Button type="button" onClick={onExport}>
          <DownloadIcon data-icon="inline-start" />
          {selectedExportCount > 0 ? `선택 ${selectedExportCount}` : "전체"} 내보내기
        </Button>
      </div>
      <div className="flex max-h-80 flex-col gap-2 overflow-y-auto">
        {isLoading ? <p className="text-sm text-muted-foreground">로딩 중</p> : null}
        {places.map((place, index) => {
          const isSelected = place.place_id === selectedPlaceId;
          // 마커 번호와 동일한 1-based 목록 행 번호(index + 1).
          const number = index + 1;
          return (
          <div
            key={place.place_id}
            ref={(node) => {
              if (node) {
                rowRefs.current.set(place.place_id, node);
              } else {
                rowRefs.current.delete(place.place_id);
              }
            }}
            className="grid grid-cols-[auto_1fr_auto] items-start gap-2 rounded-lg border p-2 transition-colors data-[selected=true]:border-primary data-[selected=true]:bg-primary/5"
            data-selected={isSelected}
          >
            <input
              aria-label={`${place.name} 내보내기 선택`}
              checked={selectedExportIds.has(place.place_id)}
              className="mt-3 size-4 rounded border"
              onChange={() => onToggleExportSelection(place.place_id)}
              type="checkbox"
            />
            <button
              className="flex min-w-0 flex-col gap-1 rounded-md p-1 text-left hover:bg-muted"
              onClick={() => onSelect(place.place_id)}
              type="button"
            >
              <span className="flex min-w-0 items-center justify-between gap-3">
                <span className="flex min-w-0 items-center gap-2">
                  <span
                    aria-hidden="true"
                    data-marker-number={number}
                    className={`flex size-5 shrink-0 items-center justify-center rounded-full text-[11px] font-bold tabular-nums ${
                      isSelected
                        ? "bg-primary text-primary-foreground"
                        : "bg-muted text-muted-foreground"
                    }`}
                  >
                    {number}
                  </span>
                  <span className="truncate text-sm font-medium">{place.name}</span>
                </span>
                <span className="flex shrink-0 items-center gap-1">
                  <Badge variant={place.is_geocoded ? "secondary" : "outline"}>
                    {place.category ?? "미분류"}
                  </Badge>
                  <Badge variant="outline">{place.mention_count}회</Badge>
                </span>
              </span>
              <span className="truncate text-xs text-muted-foreground">
                {place.official_address ?? place.road_address ?? "-"}
              </span>
              <span className="truncate text-xs text-muted-foreground">
                {sourceLine(place.source_videos[0])}
              </span>
            </button>
            <Button
              type="button"
              size="icon"
              variant="ghost"
              aria-label={`${place.name} 상세`}
              onClick={() => onShowDetail(place.place_id)}
            >
              <InfoIcon className="size-4" />
            </Button>
          </div>
          );
        })}
      </div>
      {selectedPlace ? (
        <div className="flex flex-col gap-3 border-t pt-4">
          <div className="flex items-start gap-2">
            <MapPinIcon className="mt-0.5 size-4 text-muted-foreground" />
            <div className="min-w-0">
              <p className="truncate text-sm font-medium">{selectedPlace.name}</p>
              <p className="text-xs text-muted-foreground">
                {selectedPlace.latitude.toFixed(5)}, {selectedPlace.longitude.toFixed(5)}
              </p>
              <p className="text-xs text-muted-foreground">
                언급 {selectedPlace.mention_count}회 · 유튜버 {selectedPlace.source_channel_count}명
              </p>
            </div>
          </div>
          <div className="flex max-h-36 flex-col gap-2 overflow-y-auto border-t pt-3">
            <p className="text-xs font-medium">언급 소스</p>
            {selectedPlace.source_videos.length > 0 ? (
              selectedPlace.source_videos.slice(0, 5).map((source) => (
                <a
                  key={source.mapping_id}
                  className="flex flex-col gap-0.5 rounded-md border p-2 text-xs hover:bg-muted"
                  href={source.video_url}
                  rel="noreferrer"
                  target="_blank"
                >
                  <span className="truncate font-medium">{source.video_title}</span>
                  <span className="truncate text-muted-foreground">
                    {sourceLine(source)}
                  </span>
                </a>
              ))
            ) : (
              <p className="text-xs text-muted-foreground">언급 소스 없음</p>
            )}
          </div>
          <Button
            variant="outline"
            disabled={isResearching}
            onClick={() => onDeepResearch(selectedPlace.place_id)}
          >
            <FlaskConicalIcon data-icon="inline-start" />
            Deep Research
          </Button>
          {researchError ? (
            <p role="alert" className="text-xs text-destructive">
              {researchError}
            </p>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

// 실행 큐 패널: running/pending 작업 + 중지/재시작 + 상세 모달.
function PanelHeader({ title, count }: { title: string; count: number }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <h2 className="text-sm font-semibold">{title}</h2>
      <Badge variant="secondary">{count}</Badge>
    </div>
  );
}

function sortLabel(sort: DestinationSort) {
  if (sort === "mention_count") {
    return "언급 많은 순";
  }
  if (sort === "name") {
    return "이름 순";
  }
  if (sort === "category") {
    return "카테고리 순";
  }
  return "최신 등록 순";
}

function sourceLine(source: PlaceSourceVideo | undefined) {
  if (!source) {
    return "언급 영상 없음";
  }
  return [source.channel_name ?? source.channel_id, source.video_title, timestampLabel(source)]
    .filter(Boolean)
    .join(" · ");
}

function timestampLabel(source: PlaceSourceVideo) {
  if (source.timestamp_start && source.timestamp_end) {
    return `${source.timestamp_start}-${source.timestamp_end}`;
  }
  return source.timestamp_start ?? source.timestamp_end ?? "";
}
