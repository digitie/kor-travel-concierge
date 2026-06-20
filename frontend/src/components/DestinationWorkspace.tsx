"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowDownUpIcon,
  DatabaseIcon,
  DownloadIcon,
  FlaskConicalIcon,
  MapPinIcon,
  RepeatIcon,
  RotateCcwIcon,
  SquareIcon,
  Trash2Icon,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import {
  buildDestinationExportUrl,
  deleteSourceTarget,
  getRustfsStatus,
  listAuditLogs,
  listDestinations,
  listRunQueue,
  listRuns,
  listSourceTargets,
  listUnmatchedCandidates,
  resolveCandidate,
  restartRun,
  stopRun,
  triggerDeepResearch,
  type AuditLogSummary,
  type CrawlRunSummary,
  type DestinationExportFormat,
  type DestinationSort,
  type DestinationSummary,
  type PlaceSourceVideo,
  type RustfsStatus,
  type SourceTargetSummary,
  type UnmatchedCandidate,
} from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Field,
  FieldError,
  FieldGroup,
  FieldLabel,
} from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { VWorldMap } from "@/components/VWorldMap";

const reviewQueueSchema = z.object({
  name: z.string().trim().min(1, "장소명을 입력하세요."),
  latitude: z
    .string()
    .trim()
    .min(1, "위도를 입력하세요.")
    .refine((value) => Number.isFinite(Number(value)), "숫자로 입력하세요.")
    .refine((value) => {
      const number = Number(value);
      return number >= -90 && number <= 90;
    }, "위도는 -90부터 90 사이여야 합니다."),
  longitude: z
    .string()
    .trim()
    .min(1, "경도를 입력하세요.")
    .refine((value) => Number.isFinite(Number(value)), "숫자로 입력하세요.")
    .refine((value) => {
      const number = Number(value);
      return number >= -180 && number <= 180;
    }, "경도는 -180부터 180 사이여야 합니다."),
  category: z.string().trim().optional(),
});

type ReviewQueueFormValues = z.infer<typeof reviewQueueSchema>;

export function DestinationWorkspace() {
  const queryClient = useQueryClient();
  const [selectedPlaceId, setSelectedPlaceId] = useState<number | null>(null);
  const [selectedCandidateId, setSelectedCandidateId] = useState<number | null>(null);
  const [destinationSort, setDestinationSort] = useState<DestinationSort>("mention_count");
  const [exportFormat, setExportFormat] = useState<DestinationExportFormat>("xlsx");
  const [selectedExportIds, setSelectedExportIds] = useState<number[]>([]);

  const destinationsQuery = useQuery({
    queryKey: ["destinations", destinationSort],
    queryFn: () => listDestinations(destinationSort),
    refetchInterval: 10_000,
  });
  const unmatchedQuery = useQuery({
    queryKey: ["unmatched-candidates"],
    queryFn: listUnmatchedCandidates,
    refetchInterval: 10_000,
  });
  const runsQuery = useQuery({
    queryKey: ["runs"],
    queryFn: () => listRuns(),
    refetchInterval: 5_000,
  });
  const runQueueQuery = useQuery({
    queryKey: ["run-queue"],
    queryFn: listRunQueue,
    refetchInterval: 2_000,
  });
  const auditQuery = useQuery({
    queryKey: ["audit-logs"],
    queryFn: listAuditLogs,
    refetchInterval: 15_000,
  });
  const rustfsQuery = useQuery({
    queryKey: ["rustfs-status"],
    queryFn: getRustfsStatus,
    refetchInterval: 15_000,
  });
  const sourceTargetsQuery = useQuery({
    queryKey: ["source-targets"],
    queryFn: listSourceTargets,
    refetchInterval: 15_000,
  });

  const stopRunMutation = useMutation({
    mutationFn: stopRun,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["runs"] });
      queryClient.invalidateQueries({ queryKey: ["run-queue"] });
    },
  });
  const restartRunMutation = useMutation({
    mutationFn: restartRun,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["runs"] });
      queryClient.invalidateQueries({ queryKey: ["run-queue"] });
    },
  });
  const deleteTargetMutation = useMutation({
    mutationFn: deleteSourceTarget,
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["source-targets"] }),
  });

  const places = useMemo(() => destinationsQuery.data ?? [], [destinationsQuery.data]);
  const selectedPlace = useMemo(
    () => places.find((place) => place.place_id === selectedPlaceId) ?? places[0] ?? null,
    [places, selectedPlaceId],
  );
  const candidates = useMemo(
    () => unmatchedQuery.data ?? [],
    [unmatchedQuery.data],
  );
  const selectedCandidate = useMemo(
    () =>
      candidates.find((candidate) => candidate.id === selectedCandidateId) ??
      candidates[0] ??
      null,
    [candidates, selectedCandidateId],
  );
  const operationError =
    runsQuery.error?.message ??
    runQueueQuery.error?.message ??
    auditQuery.error?.message ??
    rustfsQuery.error?.message ??
    null;
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
    <div className="flex h-full min-h-screen flex-col bg-background">
      {/* 지도 + 장소(지도 옆) */}
      <div className="grid min-h-[30rem] flex-1 grid-cols-1 lg:grid-cols-[1.6fr_1fr]">
        <div className="min-h-[22rem] border-b lg:border-b-0 lg:border-r">
          <VWorldMap
            places={places}
            selectedPlaceId={selectedPlace?.place_id ?? null}
            onSelectPlace={setSelectedPlaceId}
          />
        </div>
        <div className="flex min-h-[22rem] flex-col overflow-y-auto">
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
          />
        </div>
      </div>
      {/* 검수 큐 · 반복 작업 · 운영 (아래, 작은 목록) */}
      <div className="grid max-h-[26rem] grid-cols-1 overflow-y-auto border-t md:grid-cols-3">
        <ReviewQueue
          candidates={candidates}
          selectedCandidate={selectedCandidate}
          onSelect={setSelectedCandidateId}
          errorMessage={unmatchedQuery.error?.message ?? null}
          onResolved={() => {
            queryClient.invalidateQueries({ queryKey: ["destinations"] });
            queryClient.invalidateQueries({ queryKey: ["unmatched-candidates"] });
            queryClient.invalidateQueries({ queryKey: ["audit-logs"] });
          }}
        />
        <RecurringPanel
          targets={sourceTargetsQuery.data ?? []}
          errorMessage={sourceTargetsQuery.error?.message ?? null}
          onDelete={(id) => deleteTargetMutation.mutate(id)}
          isDeleting={deleteTargetMutation.isPending}
        />
        <OperationsPanel
          runs={runsQuery.data ?? []}
          queueRuns={runQueueQuery.data ?? []}
          audits={auditQuery.data ?? []}
          rustfs={rustfsQuery.data}
          errorMessage={operationError}
          onStop={(jobId) => stopRunMutation.mutate(jobId)}
          onRestart={(jobId) => restartRunMutation.mutate(jobId)}
          isMutating={stopRunMutation.isPending || restartRunMutation.isPending}
        />
      </div>
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
}) {
  return (
    <section
      aria-label="장소 목록"
      className="flex flex-col gap-4 border-b p-4 md:border-b-0 md:border-r"
    >
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
        {places.map((place) => (
          <div
            key={place.place_id}
            className="grid grid-cols-[auto_1fr] items-start gap-2 rounded-lg border p-2 transition-colors data-[selected=true]:border-primary"
            data-selected={place.place_id === selectedPlace?.place_id}
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
                <span className="truncate text-sm font-medium">{place.name}</span>
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
          </div>
        ))}
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

function ReviewQueue({
  candidates,
  selectedCandidate,
  onSelect,
  errorMessage,
  onResolved,
}: {
  candidates: UnmatchedCandidate[];
  selectedCandidate: UnmatchedCandidate | null;
  onSelect: (candidateId: number) => void;
  errorMessage: string | null;
  onResolved: () => void;
}) {
  const form = useForm<ReviewQueueFormValues>({
    resolver: zodResolver(reviewQueueSchema),
    defaultValues: {
      name: selectedCandidate?.ai_place_name ?? "",
      latitude: "",
      longitude: "",
      category: selectedCandidate?.candidate_category ?? "",
    },
  });

  useEffect(() => {
    form.reset({
      name: selectedCandidate?.ai_place_name ?? "",
      latitude: "",
      longitude: "",
      category: selectedCandidate?.candidate_category ?? "",
    });
  }, [
    form,
    selectedCandidate?.id,
    selectedCandidate?.ai_place_name,
    selectedCandidate?.candidate_category,
  ]);

  const mutation = useMutation({
    mutationFn: (values: ReviewQueueFormValues) => {
      if (!selectedCandidate) {
        throw new Error("candidate required");
      }
      return resolveCandidate(selectedCandidate.id, {
        action: "create_place",
        correctedName: values.name,
        latitude: Number(values.latitude),
        longitude: Number(values.longitude),
        category: values.category || selectedCandidate.candidate_category || undefined,
      });
    },
    onSuccess: () => {
      onResolved();
    },
  });

  const ignoreMutation = useMutation({
    mutationFn: (candidateId: number) =>
      resolveCandidate(candidateId, { action: "ignore", reviewNote: "웹 UI 제외" }),
    onSuccess: onResolved,
  });

  return (
    <section
      aria-label="검수 큐"
      className="flex flex-col gap-3 border-b p-3 md:border-b-0 md:border-r"
    >
      <PanelHeader title="검수 큐" count={candidates.length} />
      {errorMessage ? (
        <p role="alert" className="text-xs text-destructive">
          {errorMessage}
        </p>
      ) : null}
      <div className="flex max-h-40 flex-col gap-2 overflow-y-auto">
        {candidates.map((candidate) => (
          <button
            key={candidate.id}
            className="flex w-full flex-col gap-1 rounded-lg border p-3 text-left hover:bg-muted data-[selected=true]:border-primary"
            data-selected={candidate.id === selectedCandidate?.id}
            onClick={() => onSelect(candidate.id)}
            type="button"
          >
            <span className="truncate text-sm font-medium">{candidate.ai_place_name}</span>
            <span className="truncate text-xs text-muted-foreground">
              {candidate.location_hint ?? candidate.video_id}
            </span>
          </button>
        ))}
      </div>
      {selectedCandidate ? (
        <form
          className="flex flex-col gap-3 border-t pt-4"
          onSubmit={form.handleSubmit((values) => mutation.mutate(values))}
        >
          <FieldGroup>
            <Field data-invalid={Boolean(form.formState.errors.name)}>
              <FieldLabel htmlFor="review-place-name">장소명</FieldLabel>
              <Input
                id="review-place-name"
                aria-label="보정 장소명"
                aria-invalid={Boolean(form.formState.errors.name)}
                {...form.register("name")}
              />
              <FieldError errors={[form.formState.errors.name]} />
            </Field>
            <div className="grid grid-cols-2 gap-2">
              <Field data-invalid={Boolean(form.formState.errors.latitude)}>
                <FieldLabel htmlFor="review-latitude">위도</FieldLabel>
                <Input
                  id="review-latitude"
                  aria-label="보정 위도"
                  inputMode="decimal"
                  placeholder="위도"
                  aria-invalid={Boolean(form.formState.errors.latitude)}
                  {...form.register("latitude")}
                />
                <FieldError errors={[form.formState.errors.latitude]} />
              </Field>
              <Field data-invalid={Boolean(form.formState.errors.longitude)}>
                <FieldLabel htmlFor="review-longitude">경도</FieldLabel>
                <Input
                  id="review-longitude"
                  aria-label="보정 경도"
                  inputMode="decimal"
                  placeholder="경도"
                  aria-invalid={Boolean(form.formState.errors.longitude)}
                  {...form.register("longitude")}
                />
                <FieldError errors={[form.formState.errors.longitude]} />
              </Field>
            </div>
            <Field>
              <FieldLabel htmlFor="review-category">카테고리</FieldLabel>
              <Input
                id="review-category"
                aria-label="보정 카테고리"
                placeholder="카테고리"
                {...form.register("category")}
              />
            </Field>
          </FieldGroup>
          <div className="grid grid-cols-2 gap-2">
            <Button
              type="submit"
              disabled={mutation.isPending}
            >
              저장
            </Button>
            <Button
              type="button"
              variant="outline"
              disabled={ignoreMutation.isPending}
              onClick={() => ignoreMutation.mutate(selectedCandidate.id)}
            >
              제외
            </Button>
          </div>
          {mutation.error ? (
            <p className="text-xs text-destructive">{mutation.error.message}</p>
          ) : null}
        </form>
      ) : null}
    </section>
  );
}

function OperationsPanel({
  runs,
  queueRuns,
  audits,
  rustfs,
  errorMessage,
  onStop,
  onRestart,
  isMutating,
}: {
  runs: CrawlRunSummary[];
  queueRuns: CrawlRunSummary[];
  audits: AuditLogSummary[];
  rustfs: RustfsStatus | undefined;
  errorMessage: string | null;
  onStop: (jobId: string) => void;
  onRestart: (jobId: string) => void;
  isMutating: boolean;
}) {
  const failedRuns = runs.filter((run) => run.state === "failed").length;
  const totalObjects = rustfs?.assets.reduce((sum, asset) => sum + asset.count, 0) ?? 0;

  return (
    <section aria-label="운영 패널" className="flex flex-col gap-3 p-3">
      <PanelHeader title="운영" count={runs.length} />
      {errorMessage ? (
        <p role="alert" className="text-xs text-destructive">
          {errorMessage}
        </p>
      ) : null}
      <div className="grid grid-cols-3 gap-2">
        <Metric label="실패" value={failedRuns.toString()} />
        <Metric label="객체" value={totalObjects.toString()} />
        <Metric label="RustFS" value={rustfs?.health.ok ? "OK" : "확인"} />
      </div>
      <div className="flex flex-col gap-1.5 border-t pt-3">
        <div className="flex items-center justify-between gap-2">
          <p className="text-xs font-medium">실행 큐</p>
          <Badge variant="outline">{queueRuns.length}</Badge>
        </div>
        {queueRuns.length > 0 ? (
          queueRuns.map((run) => (
            <RunControlCard
              key={run.job_id}
              run={run}
              onStop={onStop}
              onRestart={onRestart}
              isMutating={isMutating}
            />
          ))
        ) : (
          <p className="rounded-lg border p-2 text-xs text-muted-foreground">
            실행 중이거나 대기 중인 작업이 없습니다.
          </p>
        )}
      </div>
      <div className="flex flex-col gap-1.5 border-t pt-3">
        <p className="text-xs font-medium">최근 작업</p>
        {runs.length > 0 ? (
          runs.slice(0, 6).map((run) => (
            <RunControlCard
              key={run.job_id}
              run={run}
              onStop={onStop}
              onRestart={onRestart}
              isMutating={isMutating}
            />
          ))
        ) : (
          <p className="text-xs text-muted-foreground">작업 없음</p>
        )}
      </div>
      <details className="border-t pt-3">
        <summary className="flex cursor-pointer items-center gap-2 text-xs font-medium">
          <DatabaseIcon className="size-3.5 text-muted-foreground" />
          MCP/웹 쓰기 로그
        </summary>
        <div className="mt-2 flex flex-col gap-1">
          {audits.slice(0, 6).map((audit) => (
            <div
              key={audit.id}
              className="flex items-center justify-between gap-3 text-xs"
            >
              <span className="truncate">{audit.action}</span>
              <span className="text-muted-foreground">{audit.actor_type}</span>
            </div>
          ))}
        </div>
      </details>
    </section>
  );
}

// 최근/큐 작업 카드: 클릭하면 상세 로그를 펼치고 중지/재시작할 수 있다.
function RunControlCard({
  run,
  onStop,
  onRestart,
  isMutating,
}: {
  run: CrawlRunSummary;
  onStop: (jobId: string) => void;
  onRestart: (jobId: string) => void;
  isMutating: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const isActive = run.state === "pending" || run.state === "running";
  const isTerminal =
    run.state === "done" || run.state === "failed" || run.state === "cancelled";

  return (
    <div className="flex flex-col gap-1.5 rounded-lg border p-2 text-xs">
      <button
        type="button"
        className="flex items-center justify-between gap-2 text-left"
        onClick={() => setExpanded((value) => !value)}
        aria-expanded={expanded}
      >
        <span className="truncate font-medium">{runLabel(run)}</span>
        <Badge variant={run.state === "failed" ? "destructive" : "outline"}>
          {run.state}
        </Badge>
      </button>
      <div className="h-1.5 overflow-hidden rounded-full bg-muted">
        <div
          className={progressBarClass(run.state)}
          style={{ width: `${Math.round(run.progress * 100)}%` }}
        />
      </div>
      <p className="line-clamp-1 text-muted-foreground">
        {run.current_message ?? latestRunLog(run) ?? "상세 로그 대기 중"}
      </p>
      {expanded ? (
        <div className="flex flex-col gap-2 border-t pt-2">
          {run.last_error ? (
            <p className="break-words text-destructive">{run.last_error}</p>
          ) : null}
          <ol className="flex max-h-40 flex-col gap-1 overflow-y-auto">
            {run.status_logs.length > 0 ? (
              run.status_logs.slice(-12).map((log, index) => (
                <li
                  key={`${log.timestamp}-${index}`}
                  className="grid grid-cols-[3.5rem_1fr] gap-1"
                >
                  <span className="text-muted-foreground">
                    {formatRunTime(log.timestamp)}
                  </span>
                  <span className="min-w-0 break-words">{log.message}</span>
                </li>
              ))
            ) : (
              <li className="text-muted-foreground">상세 로그 없음</li>
            )}
          </ol>
          <div className="flex gap-2">
            {isActive ? (
              <Button
                type="button"
                size="xs"
                variant="outline"
                disabled={isMutating}
                onClick={() => onStop(run.job_id)}
              >
                <SquareIcon data-icon="inline-start" />
                중지
              </Button>
            ) : null}
            {isTerminal ? (
              <Button
                type="button"
                size="xs"
                variant="outline"
                disabled={isMutating}
                onClick={() => onRestart(run.job_id)}
              >
                <RotateCcwIcon data-icon="inline-start" />
                재시작
              </Button>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  );
}

// 반복 수집(source_target) 패널: 활성 반복 작업 목록 + 상태 + 삭제.
function RecurringPanel({
  targets,
  errorMessage,
  onDelete,
  isDeleting,
}: {
  targets: SourceTargetSummary[];
  errorMessage: string | null;
  onDelete: (id: number) => void;
  isDeleting: boolean;
}) {
  return (
    <section
      aria-label="반복 작업"
      className="flex flex-col gap-3 border-b p-3 md:border-b-0 md:border-r"
    >
      <div className="flex items-center justify-between gap-3">
        <h2 className="flex items-center gap-1.5 text-sm font-semibold">
          <RepeatIcon className="size-4 text-muted-foreground" />
          반복 작업
        </h2>
        <Badge variant="secondary">{targets.length}</Badge>
      </div>
      {errorMessage ? (
        <p role="alert" className="text-xs text-destructive">
          {errorMessage}
        </p>
      ) : null}
      {targets.length > 0 ? (
        <div className="flex flex-col gap-2">
          {targets.map((target) => (
            <div
              key={target.id}
              className="flex flex-col gap-1.5 rounded-lg border p-2 text-xs"
            >
              <div className="flex items-center justify-between gap-2">
                <span className="truncate font-medium">
                  {target.display_name ?? target.source_value}
                </span>
                <Badge variant="outline">{targetTypeLabel(target.target_type)}</Badge>
              </div>
              <p className="truncate text-muted-foreground">{target.source_value}</p>
              <div className="flex items-center justify-between gap-2">
                <span className="text-muted-foreground">
                  {intervalLabel(target.scan_interval_minutes)} · 다음{" "}
                  {formatRunTime(target.next_crawl_at)}
                </span>
                <Button
                  type="button"
                  size="xs"
                  variant="outline"
                  disabled={isDeleting}
                  onClick={() => onDelete(target.id)}
                  aria-label={`${target.display_name ?? target.source_value} 반복 삭제`}
                >
                  <Trash2Icon data-icon="inline-start" />
                  삭제
                </Button>
              </div>
              {target.last_scan_error ? (
                <p className="break-words text-destructive">
                  {target.last_scan_error}
                </p>
              ) : null}
            </div>
          ))}
        </div>
      ) : (
        <p className="rounded-lg border p-2 text-xs text-muted-foreground">
          반복 수집 중인 작업이 없습니다. 수집 시작 시 “반복 검색”을 켜면 등록됩니다.
        </p>
      )}
    </section>
  );
}

function runLabel(run: CrawlRunSummary) {
  return [run.job_type, run.target_id].filter(Boolean).join(" · ");
}

function formatRunTime(value: string | null) {
  if (!value) {
    return "-";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "-";
  }
  return date.toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" });
}

function targetTypeLabel(type: string) {
  if (type === "channel") {
    return "채널";
  }
  if (type === "playlist") {
    return "재생목록";
  }
  if (type === "keyword") {
    return "검색어";
  }
  if (type === "video") {
    return "영상";
  }
  return type;
}

function intervalLabel(minutes: number | null) {
  if (!minutes) {
    return "-";
  }
  if (minutes % 1440 === 0) {
    return `${minutes / 1440}일`;
  }
  if (minutes % 60 === 0) {
    return `${minutes / 60}시간`;
  }
  return `${minutes}분`;
}

function latestRunLog(run: CrawlRunSummary) {
  return run.status_logs.at(-1)?.message ?? null;
}

function progressBarClass(state: string) {
  if (state === "failed") {
    return "h-full rounded-full bg-destructive";
  }
  if (state === "done") {
    return "h-full rounded-full bg-success";
  }
  return "h-full rounded-full bg-primary";
}

function PanelHeader({ title, count }: { title: string; count: number }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <h2 className="text-sm font-semibold">{title}</h2>
      <Badge variant="secondary">{count}</Badge>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-1 rounded-lg border p-3">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="text-lg font-semibold">{value}</span>
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
