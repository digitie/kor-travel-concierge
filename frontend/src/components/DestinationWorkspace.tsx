"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  DatabaseIcon,
  FlaskConicalIcon,
  MapPinIcon,
} from "lucide-react";
import { useMemo, useState } from "react";

import {
  getRustfsStatus,
  listAuditLogs,
  listDestinations,
  listRuns,
  listUnmatchedCandidates,
  resolveCandidate,
  triggerDeepResearch,
  type DestinationSummary,
  type UnmatchedCandidate,
} from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { VWorldMap } from "@/components/VWorldMap";

export function DestinationWorkspace() {
  const queryClient = useQueryClient();
  const [selectedPlaceId, setSelectedPlaceId] = useState<number | null>(null);
  const [selectedCandidateId, setSelectedCandidateId] = useState<number | null>(null);

  const destinationsQuery = useQuery({
    queryKey: ["destinations"],
    queryFn: listDestinations,
    refetchInterval: 10_000,
  });
  const unmatchedQuery = useQuery({
    queryKey: ["unmatched-candidates"],
    queryFn: listUnmatchedCandidates,
    refetchInterval: 10_000,
  });
  const runsQuery = useQuery({
    queryKey: ["runs"],
    queryFn: listRuns,
    refetchInterval: 5_000,
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

  const places = useMemo(() => destinationsQuery.data ?? [], [destinationsQuery.data]);
  const selectedPlace = useMemo(
    () => places.find((place) => place.place_id === selectedPlaceId) ?? places[0] ?? null,
    [places, selectedPlaceId],
  );
  const selectedCandidate =
    (unmatchedQuery.data ?? []).find((candidate) => candidate.id === selectedCandidateId) ??
    (unmatchedQuery.data ?? [])[0] ??
    null;

  const deepResearchMutation = useMutation({
    mutationFn: triggerDeepResearch,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["runs"] }),
  });

  return (
    <div className="flex h-full min-h-screen flex-col bg-background">
      <div className="min-h-[24rem] flex-1 border-b">
        <VWorldMap
          places={places}
          selectedPlaceId={selectedPlace?.place_id ?? null}
          onSelectPlace={setSelectedPlaceId}
        />
      </div>
      <div className="grid max-h-[46rem] grid-cols-1 overflow-y-auto md:grid-cols-[1.05fr_1fr_1.15fr]">
        <DestinationList
          places={places}
          selectedPlace={selectedPlace}
          isLoading={destinationsQuery.isLoading}
          onSelect={setSelectedPlaceId}
          onDeepResearch={(placeId) => deepResearchMutation.mutate(placeId)}
          isResearching={deepResearchMutation.isPending}
        />
        <ReviewQueue
          candidates={unmatchedQuery.data ?? []}
          selectedCandidate={selectedCandidate}
          onSelect={setSelectedCandidateId}
          onResolved={() => {
            queryClient.invalidateQueries({ queryKey: ["destinations"] });
            queryClient.invalidateQueries({ queryKey: ["unmatched-candidates"] });
            queryClient.invalidateQueries({ queryKey: ["audit-logs"] });
          }}
        />
        <OperationsPanel
          runs={runsQuery.data ?? []}
          audits={auditQuery.data ?? []}
          rustfs={rustfsQuery.data}
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
}: {
  places: DestinationSummary[];
  selectedPlace: DestinationSummary | null;
  isLoading: boolean;
  onSelect: (placeId: number) => void;
  onDeepResearch: (placeId: number) => void;
  isResearching: boolean;
}) {
  return (
    <section
      aria-label="장소 목록"
      className="flex flex-col gap-4 border-b p-4 md:border-b-0 md:border-r"
    >
      <PanelHeader title="장소" count={places.length} />
      <div className="flex max-h-80 flex-col gap-2 overflow-y-auto">
        {isLoading ? <p className="text-sm text-muted-foreground">로딩 중</p> : null}
        {places.map((place) => (
          <button
            key={place.place_id}
            className="flex w-full flex-col gap-1 rounded-lg border p-3 text-left transition-colors hover:bg-muted data-[selected=true]:border-primary"
            data-selected={place.place_id === selectedPlace?.place_id}
            onClick={() => onSelect(place.place_id)}
            type="button"
          >
            <span className="flex items-center justify-between gap-3">
              <span className="truncate text-sm font-medium">{place.name}</span>
              <Badge variant={place.is_geocoded ? "secondary" : "outline"}>
                {place.category ?? "미분류"}
              </Badge>
            </span>
            <span className="truncate text-xs text-muted-foreground">
              {place.official_address ?? place.road_address ?? "-"}
            </span>
          </button>
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
            </div>
          </div>
          <Button
            variant="outline"
            disabled={isResearching}
            onClick={() => onDeepResearch(selectedPlace.place_id)}
          >
            <FlaskConicalIcon data-icon="inline-start" />
            Deep Research
          </Button>
        </div>
      ) : null}
    </section>
  );
}

function ReviewQueue({
  candidates,
  selectedCandidate,
  onSelect,
  onResolved,
}: {
  candidates: UnmatchedCandidate[];
  selectedCandidate: UnmatchedCandidate | null;
  onSelect: (candidateId: number) => void;
  onResolved: () => void;
}) {
  const [name, setName] = useState("");
  const [latitude, setLatitude] = useState("");
  const [longitude, setLongitude] = useState("");
  const [category, setCategory] = useState("");

  const mutation = useMutation({
    mutationFn: () => {
      if (!selectedCandidate) {
        throw new Error("candidate required");
      }
      return resolveCandidate(selectedCandidate.id, {
        action: "create_place",
        correctedName: name || selectedCandidate.ai_place_name,
        latitude: Number(latitude),
        longitude: Number(longitude),
        category: category || selectedCandidate.candidate_category || undefined,
      });
    },
    onSuccess: () => {
      setLatitude("");
      setLongitude("");
      setCategory("");
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
      className="flex flex-col gap-4 border-b p-4 md:border-b-0 md:border-r"
    >
      <PanelHeader title="검수 큐" count={candidates.length} />
      <div className="flex max-h-56 flex-col gap-2 overflow-y-auto">
        {candidates.map((candidate) => (
          <button
            key={candidate.id}
            className="flex w-full flex-col gap-1 rounded-lg border p-3 text-left hover:bg-muted data-[selected=true]:border-primary"
            data-selected={candidate.id === selectedCandidate?.id}
            onClick={() => {
              onSelect(candidate.id);
              setName(candidate.ai_place_name);
              setCategory(candidate.candidate_category ?? "");
            }}
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
        <div className="flex flex-col gap-3 border-t pt-4">
          <Input
            aria-label="보정 장소명"
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
          <div className="grid grid-cols-2 gap-2">
            <Input
              aria-label="보정 위도"
              inputMode="decimal"
              placeholder="위도"
              value={latitude}
              onChange={(event) => setLatitude(event.target.value)}
            />
            <Input
              aria-label="보정 경도"
              inputMode="decimal"
              placeholder="경도"
              value={longitude}
              onChange={(event) => setLongitude(event.target.value)}
            />
          </div>
          <Input
            aria-label="보정 카테고리"
            placeholder="카테고리"
            value={category}
            onChange={(event) => setCategory(event.target.value)}
          />
          <div className="grid grid-cols-2 gap-2">
            <Button
              disabled={!latitude || !longitude || mutation.isPending}
              onClick={() => mutation.mutate()}
            >
              저장
            </Button>
            <Button
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
        </div>
      ) : null}
    </section>
  );
}

function OperationsPanel({
  runs,
  audits,
  rustfs,
}: {
  runs: Awaited<ReturnType<typeof listRuns>>;
  audits: Awaited<ReturnType<typeof listAuditLogs>>;
  rustfs: Awaited<ReturnType<typeof getRustfsStatus>> | undefined;
}) {
  const failedRuns = runs.filter((run) => run.state === "failed").length;
  const totalObjects = rustfs?.assets.reduce((sum, asset) => sum + asset.count, 0) ?? 0;

  return (
    <section aria-label="운영 패널" className="flex flex-col gap-4 p-4">
      <PanelHeader title="운영" count={runs.length} />
      <div className="grid grid-cols-3 gap-2">
        <Metric label="실패" value={failedRuns.toString()} />
        <Metric label="객체" value={totalObjects.toString()} />
        <Metric label="RustFS" value={rustfs?.health.ok ? "OK" : "확인"} />
      </div>
      <div className="flex flex-col gap-2">
        {runs.slice(0, 5).map((run) => (
          <div key={run.job_id} className="flex items-center justify-between gap-3 text-sm">
            <span className="truncate">{run.job_type}</span>
            <Badge variant={run.state === "failed" ? "destructive" : "outline"}>
              {run.state}
            </Badge>
          </div>
        ))}
      </div>
      <div className="flex flex-col gap-2 border-t pt-4">
        <div className="flex items-center gap-2 text-sm font-medium">
          <DatabaseIcon className="size-4 text-muted-foreground" />
          MCP/웹 쓰기 로그
        </div>
        {audits.slice(0, 5).map((audit) => (
          <div key={audit.id} className="flex items-center justify-between gap-3 text-xs">
            <span className="truncate">{audit.action}</span>
            <span className="text-muted-foreground">{audit.actor_type}</span>
          </div>
        ))}
      </div>
    </section>
  );
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
