"use client";

import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowDownUpIcon,
  DownloadIcon,
  InfoIcon,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import {
  buildDestinationExportUrl,
  listDestinationFacets,
  listDestinations,
  type DestinationExportFormat,
  type DestinationFacets,
  type DestinationGroupDim,
  type DestinationSort,
  type DestinationSummary,
  type PlaceSourceVideo,
} from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
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
import { Input } from "@/components/ui/input";
import { useIsMobile } from "@/lib/use-is-mobile";
import { usePersistedState } from "@/lib/use-persisted-state";
import { PanelHeader } from "@/components/panels";
import { PlaceDetailView } from "@/components/PlaceDetailView";
import { VWorldMap } from "@/components/VWorldMap";

export function DestinationWorkspace() {
  const [selectedPlaceId, setSelectedPlaceId] = useState<number | null>(null);
  const [mapFocusKey, setMapFocusKey] = useState(0);
  // 정렬·그룹 필터는 상세 페이지를 다녀와도 유지되도록 sessionStorage에 보존한다.
  const [destinationSort, setDestinationSort] = usePersistedState<DestinationSort>(
    "ktc.destinations.sort",
    "mention_count",
  );
  const [exportFormat, setExportFormat] = useState<DestinationExportFormat>("xlsx");
  // 내보내기 장바구니: 필터를 바꿔도, 상세 페이지를 다녀와도 선택이 유지된다(쇼핑몰 장바구니).
  const [selectedExportIds, setSelectedExportIds] = usePersistedState<number[]>(
    "ktc.destinations.exportCart",
    [],
  );
  // 결과 보기 그룹화: 출처 기준(유튜버/재생목록/검색어) + 선택 값.
  const [groupDim, setGroupDim] = usePersistedState<DestinationGroupDim>(
    "ktc.destinations.groupDim",
    "none",
  );
  const [groupValue, setGroupValue] = usePersistedState<string | null>(
    "ktc.destinations.groupValue",
    null,
  );
  const [categoryFilter, setCategoryFilter] = usePersistedState<string | null>(
    "ktc.destinations.category",
    null,
  );
  const [districtFilter, setDistrictFilter] = usePersistedState<string | null>(
    "ktc.destinations.district",
    null,
  );
  const [textFilter, setTextFilter] = usePersistedState<string>(
    "ktc.destinations.query",
    "",
  );

  // 작업 상세에서 확정 POI를 누르면 `?place=<id>`로 들어온다. 그 장소가 필터에 가려지지
  // 않도록 그룹 필터를 해제하고 해당 장소를 선택한다(딥링크, 최초 1회).
  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    const placeParam = new URLSearchParams(window.location.search).get("place");
    if (!placeParam) return;
    const placeId = Number(placeParam);
    if (!Number.isFinite(placeId)) return;
    setGroupDim("none");
    setGroupValue(null);
    setCategoryFilter(null);
    setDistrictFilter(null);
    setTextFilter("");
    setSelectedPlaceId(placeId);
  }, [setCategoryFilter, setDistrictFilter, setGroupDim, setGroupValue, setTextFilter]);
  /* eslint-enable react-hooks/set-state-in-effect */

  // 작업 상세에서 영상별 POI를 누르면 `?video=<id>`로 들어온다 — 그 영상이 언급한
  // 장소만 필터로 보여준다(최초 1회, 그룹 필터는 해제).
  const [videoFilter, setVideoFilter] = useState<string | null>(null);
  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    const v = new URLSearchParams(window.location.search).get("video");
    if (!v) return;
    setGroupDim("none");
    setGroupValue(null);
    setCategoryFilter(null);
    setDistrictFilter(null);
    setTextFilter("");
    setVideoFilter(v);
  }, [setCategoryFilter, setDistrictFilter, setGroupDim, setGroupValue, setTextFilter]);
  /* eslint-enable react-hooks/set-state-in-effect */

  const facetsQuery = useQuery({
    queryKey: ["destination-facets"],
    queryFn: listDestinationFacets,
    refetchInterval: 30_000,
  });
  const filter = useMemo(() => {
    const common = {
      category: categoryFilter,
      district: districtFilter,
      query: textFilter.trim() || null,
    };
    if (videoFilter) {
      return { ...common, videoId: videoFilter };
    }
    if (!groupValue || groupDim === "none") {
      return common.category || common.district || common.query
        ? common
        : undefined;
    }
    if (groupDim === "channel") {
      return { ...common, channelId: groupValue };
    }
    if (groupDim === "playlist") {
      return { ...common, playlistId: groupValue };
    }
    return { ...common, keyword: groupValue };
  }, [categoryFilter, districtFilter, groupDim, groupValue, textFilter, videoFilter]);

  const destinationsQuery = useQuery({
    queryKey: [
      "destinations",
      destinationSort,
      groupDim,
      groupValue,
      videoFilter,
      categoryFilter,
      districtFilter,
      textFilter,
    ],
    queryFn: () => listDestinations(destinationSort, filter),
    refetchInterval: 10_000,
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
  // 체크 표시는 전체 장바구니 기준(보이는 행만 렌더되므로 결과는 visible와 동일).
  const selectedExportIdSet = useMemo(
    () => new Set(selectedExportIds),
    [selectedExportIds],
  );
  const isAllSelected =
    places.length > 0 && selectedVisibleExportIds.length === places.length;

  function toggleExportSelection(placeId: number) {
    setSelectedExportIds((current) =>
      current.includes(placeId)
        ? current.filter((id) => id !== placeId)
        : [...current, placeId],
    );
  }

  function toggleAllExportSelection() {
    // "전체 선택"은 현재 보이는 항목만 장바구니에 더하거나 뺀다(다른 필터의 선택은 보존).
    const visibleIds = places.map((place) => place.place_id);
    setSelectedExportIds((current) =>
      isAllSelected
        ? current.filter((id) => !visiblePlaceIds.has(id))
        : Array.from(new Set([...current, ...visibleIds])),
    );
  }

  function exportPlaces() {
    window.location.assign(
      buildDestinationExportUrl({
        format: exportFormat,
        // 현재 필터에 보이는 것만이 아니라 장바구니 전체를 내보낸다(필터로 선택이 날아가지 않음).
        placeIds: selectedExportIds,
        sort: destinationSort,
      }),
    );
  }

  function focusPlace(placeId: number) {
    setSelectedPlaceId(placeId);
    setMapFocusKey((current) => current + 1);
  }

  return (
    <div className="flex h-full min-h-[36rem] flex-col overflow-hidden bg-background lg:min-h-0">
      {videoFilter ? (
        <div className="flex items-center justify-between gap-2 border-b bg-primary/5 px-4 py-1.5 text-xs">
          <span className="truncate text-muted-foreground">
            영상 필터: 이 영상이 언급한 장소만 표시 중
          </span>
          <Button
            type="button"
            size="xs"
            variant="ghost"
            onClick={() => setVideoFilter(null)}
          >
            필터 해제
          </Button>
        </div>
      ) : null}
      {/* 장소(지도 왼쪽, 좁은 칼럼) + 지도 */}
      <div className="grid h-full min-h-[30rem] flex-1 grid-cols-1 lg:min-h-0 lg:grid-cols-[0.7fr_1.6fr] lg:overflow-hidden">
        {/* 좁은 화면(스택): 지도가 위, 리스트가 아래(order). 데스크톱(lg): 좌 리스트 / 우 지도 유지. */}
        <div className="order-2 flex min-h-[22rem] flex-col overflow-y-auto lg:order-none lg:min-h-0 lg:overflow-hidden lg:border-r">
          <DestinationList
            places={places}
            selectedPlace={selectedPlace}
            isLoading={destinationsQuery.isLoading}
            onSelect={focusPlace}
            sort={destinationSort}
            onSortChange={setDestinationSort}
            exportFormat={exportFormat}
            onExportFormatChange={setExportFormat}
            selectedExportIds={selectedExportIdSet}
            selectedExportCount={selectedExportIds.length}
            isAllSelected={isAllSelected}
            onToggleExportSelection={toggleExportSelection}
            onToggleAllExportSelection={toggleAllExportSelection}
            onExport={exportPlaces}
            onShowDetail={openPlaceDetail}
            groupDim={groupDim}
            groupValue={groupValue}
            facets={facetsQuery.data}
            categoryFilter={categoryFilter}
            districtFilter={districtFilter}
            textFilter={textFilter}
            onGroupChange={(dim, value) => {
              setGroupDim(dim);
              setGroupValue(value);
            }}
            onCategoryFilterChange={setCategoryFilter}
            onDistrictFilterChange={setDistrictFilter}
            onTextFilterChange={setTextFilter}
          />
        </div>
        <div className="order-1 min-h-[22rem] overflow-hidden border-b lg:order-none lg:h-full lg:min-h-0 lg:border-b-0">
          <VWorldMap
            places={places}
            selectedPlaceId={selectedPlace?.place_id ?? null}
            onSelectPlace={focusPlace}
            focusKey={mapFocusKey}
          />
        </div>
      </div>

      <Dialog
        open={detailPlaceId != null}
        onOpenChange={(open) => !open && setDetailPlaceId(null)}
      >
        <DialogContent className="max-h-[85vh] max-w-4xl overflow-y-auto">
          <DialogHeader>
            <DialogTitle>장소 상세</DialogTitle>
          </DialogHeader>
          {detailPlaceId != null ? (
            <PlaceDetailView
              placeId={detailPlaceId}
              onDeleted={() => setDetailPlaceId(null)}
            />
          ) : null}
        </DialogContent>
      </Dialog>
    </div>
  );
}

function DestinationList({
  places,
  selectedPlace,
  isLoading,
  onSelect,
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
  groupDim,
  groupValue,
  facets,
  categoryFilter,
  districtFilter,
  textFilter,
  onGroupChange,
  onCategoryFilterChange,
  onDistrictFilterChange,
  onTextFilterChange,
}: {
  places: DestinationSummary[];
  selectedPlace: DestinationSummary | null;
  isLoading: boolean;
  onSelect: (placeId: number) => void;
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
  groupDim: DestinationGroupDim;
  groupValue: string | null;
  facets: DestinationFacets | undefined;
  categoryFilter: string | null;
  districtFilter: string | null;
  textFilter: string;
  onGroupChange: (dim: DestinationGroupDim, value: string | null) => void;
  onCategoryFilterChange: (value: string | null) => void;
  onDistrictFilterChange: (value: string | null) => void;
  onTextFilterChange: (value: string) => void;
}) {
  // 선택된 장소의 행 DOM을 참조해 마커 클릭 시 목록에서 보이도록 스크롤한다.
  const rowRefs = useRef<Map<number, HTMLDivElement | null>>(new Map());
  const selectedPlaceId = selectedPlace?.place_id ?? null;
  const districtFilterLabel =
    (facets?.districts ?? []).find((district) => district.value === districtFilter)
      ?.label ?? districtFilter;

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
    <section aria-label="장소 목록" className="flex flex-col gap-4 p-4 lg:min-h-0 lg:flex-1">
      <PanelHeader title="장소" count={places.length} />
      <Input
        aria-label="장소 글자 검색"
        placeholder="장소명, 주소, 설명 검색"
        value={textFilter}
        onChange={(event) => onTextFilterChange(event.target.value)}
      />
      <div className="grid grid-cols-2 gap-2">
        <Select
          value={categoryFilter ?? "all"}
          onValueChange={(value) =>
            onCategoryFilterChange(value === "all" ? null : value)
          }
        >
          <SelectTrigger className="w-full" aria-label="카테고리 필터">
            <SelectValue>
              {categoryFilter ? categoryFilter : "카테고리 전체"}
            </SelectValue>
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              <SelectItem value="all">카테고리 전체</SelectItem>
              {(facets?.categories ?? []).map((category) => (
                <SelectItem key={category.value} value={category.value}>
                  {category.value} ({category.place_count})
                </SelectItem>
              ))}
            </SelectGroup>
          </SelectContent>
        </Select>
        <Select
          value={districtFilter ?? "all"}
          onValueChange={(value) =>
            onDistrictFilterChange(value === "all" ? null : value)
          }
        >
          <SelectTrigger className="w-full" aria-label="시군구 필터">
            <SelectValue>
              {districtFilter ? districtFilterLabel : "시군구 전체"}
            </SelectValue>
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              <SelectItem value="all">시군구 전체</SelectItem>
              {(facets?.districts ?? []).map((district) => (
                <SelectItem key={district.value} value={district.value}>
                  {district.label} ({district.place_count})
                </SelectItem>
              ))}
            </SelectGroup>
          </SelectContent>
        </Select>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <Select
          value={groupDim}
          onValueChange={(value) =>
            onGroupChange(value as DestinationGroupDim, null)
          }
        >
          <SelectTrigger className="w-full" aria-label="결과 그룹 기준">
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
            onValueChange={(value) => onGroupChange(groupDim, value || null)}
          >
            <SelectTrigger className="w-full" aria-label="그룹 값 선택">
              <SelectValue placeholder={`${groupDimLabel(groupDim)} 선택`}>
                {groupValueLabel(groupDim, groupValue, facets)}
              </SelectValue>
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                {groupOptions(groupDim, facets).map((opt) => (
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
      <div className="flex max-h-80 flex-col gap-2 overflow-y-auto lg:max-h-none lg:min-h-0 lg:flex-1">
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
            <Checkbox
              aria-label={`${place.name} 내보내기 선택`}
              checked={selectedExportIds.has(place.place_id)}
              className="mt-3"
              onCheckedChange={() => onToggleExportSelection(place.place_id)}
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
    </section>
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

function groupDimLabel(dim: DestinationGroupDim) {
  if (dim === "channel") {
    return "유튜버별";
  }
  if (dim === "playlist") {
    return "재생목록별";
  }
  if (dim === "keyword") {
    return "검색어별";
  }
  return "전체";
}

function groupOptions(
  dim: DestinationGroupDim,
  facets: DestinationFacets | undefined,
): { value: string; label: string; count: number }[] {
  if (!facets) {
    return [];
  }
  if (dim === "channel") {
    return facets.channels.map((c) => ({
      value: c.id,
      label: c.title,
      count: c.place_count,
    }));
  }
  if (dim === "playlist") {
    return facets.playlists.map((p) => ({
      value: p.id,
      label: p.title,
      count: p.place_count,
    }));
  }
  if (dim === "keyword") {
    return facets.keywords.map((k) => ({
      value: k.value,
      label: k.value,
      count: k.place_count,
    }));
  }
  return [];
}

function groupValueLabel(
  dim: DestinationGroupDim,
  value: string | null,
  facets: DestinationFacets | undefined,
) {
  if (!value) {
    return "";
  }
  const option = groupOptions(dim, facets).find((opt) => opt.value === value);
  return option ? `${option.label} (${option.count})` : value;
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
