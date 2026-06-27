"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ExternalLinkIcon,
  FlaskConicalIcon,
  Loader2Icon,
  Trash2Icon,
} from "lucide-react";

import {
  deletePlace,
  getPlaceDetail,
  getVideoTranscript,
  triggerDeepResearch,
} from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

function dateLabel(value: string | null): string {
  return value ? value.slice(0, 10) : "";
}

function cleanTranscript(text: string): string {
  return text
    .split(/\r?\n/)
    .map((line) =>
      line
        .replace(/^\s*(?:\[\d{1,2}:\d{2}(?::\d{2})?\]|\d{1,2}:\d{2}(?::\d{2})?)\s*/g, "")
        .replace(/\[(?:음악|Music|music|박수|웃음)\]/g, "")
        .trim(),
    )
    .filter(Boolean)
    .join("\n");
}

function timestampNeedle(value: string | null): string | null {
  if (!value) return null;
  const parts = value.split(":").map((part) => part.padStart(2, "0"));
  return parts.join(":");
}

export function PlaceDetailView({
  placeId,
  onDeleted,
}: {
  placeId: number;
  onDeleted?: () => void;
}) {
  const queryClient = useQueryClient();
  const detailQuery = useQuery({
    queryKey: ["place-detail", placeId],
    queryFn: () => getPlaceDetail(placeId),
  });
  const detail = detailQuery.data;
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [expandedVideoId, setExpandedVideoId] = useState<string | null>(null);
  const [transcriptTab, setTranscriptTab] = useState("raw");
  const expandedVideo = useMemo(
    () =>
      detail?.source_videos.find((video) => video.video_id === expandedVideoId) ??
      null,
    [detail?.source_videos, expandedVideoId],
  );
  const transcriptQuery = useQuery({
    queryKey: ["video-transcript", expandedVideoId],
    queryFn: () => getVideoTranscript(expandedVideoId ?? ""),
    enabled: expandedVideoId != null,
  });
  const transcriptText = transcriptQuery.data?.text ?? "";
  const transcriptRef = useRef<HTMLPreElement>(null);
  const evidenceStart = expandedVideo?.mentions.find(
    (mention) => mention.timestamp_start,
  )?.timestamp_start ?? null;
  const scrollTranscriptToEvidence = useCallback(() => {
    const element = transcriptRef.current;
    if (!element || !transcriptText) return;
    const needle = timestampNeedle(evidenceStart);
    const index = needle ? transcriptText.indexOf(needle) : -1;
    if (index < 0) {
      element.scrollTop = 0;
      return;
    }
    const ratio = index / Math.max(transcriptText.length, 1);
    element.scrollTop = Math.max(0, element.scrollHeight * ratio - 40);
  }, [evidenceStart, transcriptText]);
  const deleteMutation = useMutation({
    mutationFn: () => deletePlace(placeId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["destinations"] });
      queryClient.invalidateQueries({ queryKey: ["unmatched-candidates"] });
      queryClient.removeQueries({ queryKey: ["place-detail", placeId] });
      onDeleted?.();
    },
  });
  const deepResearchMutation = useMutation({
    mutationFn: () => triggerDeepResearch(placeId),
  });

  useEffect(() => {
    if (transcriptText) {
      requestAnimationFrame(scrollTranscriptToEvidence);
    }
  }, [expandedVideoId, scrollTranscriptToEvidence, transcriptText]);

  if (detailQuery.isLoading) {
    return <p className="p-2 text-sm text-muted-foreground">불러오는 중…</p>;
  }
  if (!detail) {
    return (
      <p className="p-2 text-sm text-destructive">
        {detailQuery.error?.message ?? "불러오지 못했습니다."}
      </p>
    );
  }

  const p = detail.place;
  const address = p.road_address ?? p.official_address;

  return (
    <div className="flex flex-col gap-4">
      <div>
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="text-base font-semibold">{p.name}</h3>
          {p.category ? <Badge variant="outline">{p.category}</Badge> : null}
          {p.category_code_suggestion ? (
            <Badge variant="outline">{p.category_code_suggestion}</Badge>
          ) : null}
          {p.is_geocoded ? (
            <Badge variant="secondary">지오코딩</Badge>
          ) : (
            <Badge variant="outline">좌표 없음</Badge>
          )}
        </div>
        {address ? (
          <p className="mt-1 text-sm text-muted-foreground">{address}</p>
        ) : null}
        {p.sigungu_code || p.legal_dong_code ? (
          <div className="mt-2 flex flex-wrap gap-1.5">
            {p.sigungu_code ? (
              <Badge variant="outline">
                {p.sigungu_name ?? "시군구"} {p.sigungu_code}
              </Badge>
            ) : null}
            {p.legal_dong_code ? (
              <Badge variant="outline">
                {p.legal_dong_name ?? "법정동"} {p.legal_dong_code}
              </Badge>
            ) : null}
          </div>
        ) : null}
        {p.latitude != null && p.longitude != null ? (
          <p className="text-xs text-muted-foreground">
            {p.latitude.toFixed(5)}, {p.longitude.toFixed(5)}
          </p>
        ) : null}
      </div>

      <div className="grid grid-cols-3 gap-2">
        <Stat label="언급 횟수" value={detail.stats.mention_count} />
        <Stat label="동영상 수" value={detail.stats.video_count} />
        <Stat label="유튜버 수" value={detail.stats.channel_count} />
      </div>

      {p.description ? (
        <DetailSection title="영상 설명">
          <p className="text-xs whitespace-pre-wrap text-muted-foreground">
            {p.description}
          </p>
        </DetailSection>
      ) : null}
      {p.gemini_enriched_description ? (
        <DetailSection title="AI 보강 설명">
          <p className="text-xs whitespace-pre-wrap text-muted-foreground">
            {p.gemini_enriched_description}
          </p>
        </DetailSection>
      ) : null}
      {p.detailed_research_content ? (
        <DetailSection title="심층 조사">
          <p className="line-clamp-6 text-xs whitespace-pre-wrap text-muted-foreground">
            {p.detailed_research_content}
          </p>
        </DetailSection>
      ) : null}

      <DetailSection
        title={`출처 동영상 · 어디에 나왔는지 (${detail.source_videos.length})`}
      >
        <div className="flex flex-col gap-2">
          {detail.source_videos.map((video) => (
            <div
              key={video.video_id}
              className="flex flex-col gap-1 rounded-lg border p-2 text-xs"
            >
              <div className="flex items-center justify-between gap-2">
                <button
                  type="button"
                  onClick={() => setExpandedVideoId(video.video_id)}
                  aria-label={`${video.title ?? video.video_id} 출처 동영상 상세`}
                  className="flex min-w-0 items-start gap-1 text-left font-medium text-primary hover:underline"
                >
                  <span className="min-w-0 break-words">
                    {video.title ?? video.video_id}
                  </span>
                </button>
                <Badge variant="secondary">{video.mention_count}회</Badge>
              </div>
              <p className="text-muted-foreground">
                {[video.channel_title, dateLabel(video.published_at)]
                  .filter(Boolean)
                  .join(" · ")}
              </p>
              {video.mentions.map((mention, index) => (
                <div
                  key={index}
                  className="border-l-2 border-muted pl-2 text-muted-foreground"
                >
                  {mention.timestamp_start ? (
                    <span className="mr-1 font-medium text-foreground">
                      {mention.timestamp_start}
                    </span>
                  ) : null}
                  {mention.source_text ?? mention.source_kind ?? ""}
                </div>
              ))}
            </div>
          ))}
          {detail.source_videos.length === 0 ? (
            <p className="rounded-lg border p-2 text-muted-foreground">
              출처 동영상이 없습니다.
            </p>
          ) : null}
        </div>
      </DetailSection>

      {expandedVideo ? (
        <DetailSection title="출처 동영상 상세">
          <div className="grid gap-3 lg:grid-cols-[0.85fr_1.15fr]">
            <div className="flex flex-col gap-2 rounded-lg border p-3 text-xs">
              <div className="flex items-start justify-between gap-2">
                <h5 className="min-w-0 break-words text-sm font-semibold">
                  {expandedVideo.title ?? expandedVideo.video_id}
                </h5>
                <a
                  href={expandedVideo.url}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex shrink-0 items-center gap-1 text-primary hover:underline"
                >
                  YouTube
                  <ExternalLinkIcon className="size-3" />
                </a>
              </div>
              <p className="text-muted-foreground">
                {[expandedVideo.channel_title, dateLabel(expandedVideo.published_at)]
                  .filter(Boolean)
                  .join(" · ")}
              </p>
              <div className="flex flex-col gap-1">
                {expandedVideo.mentions.map((mention, index) => (
                  <div
                    key={index}
                    className="border-l-2 border-muted pl-2 text-muted-foreground"
                  >
                    <div className="font-medium text-foreground">
                      {[mention.timestamp_start, mention.timestamp_end]
                        .filter(Boolean)
                        .join(" ~ ") || "시간 정보 없음"}
                    </div>
                    <p className="whitespace-pre-wrap">
                      {mention.source_text ?? mention.source_kind ?? ""}
                    </p>
                    {mention.speaker_note ? (
                      <p>메모: {mention.speaker_note}</p>
                    ) : null}
                  </div>
                ))}
              </div>
            </div>
            <div className="flex min-w-0 flex-col gap-2">
              <div className="flex items-center justify-between gap-2">
                <h5 className="text-xs font-semibold text-muted-foreground">
                  {transcriptQuery.data?.kind === "raw"
                    ? "자막 (원본 — 보정본 없음)"
                    : "보정 자막"}
                </h5>
                <Button
                  type="button"
                  size="xs"
                  variant="outline"
                  disabled={!transcriptText}
                  onClick={scrollTranscriptToEvidence}
                >
                  근거 위치로 이동
                </Button>
              </div>
              {transcriptQuery.isLoading ? (
                <p className="rounded-lg border p-2 text-xs text-muted-foreground">
                  불러오는 중…
                </p>
              ) : transcriptText ? (
                <Tabs
                  value={transcriptTab}
                  onValueChange={(value) => setTranscriptTab(value ?? "raw")}
                >
                  <TabsList className="w-full">
                    <TabsTrigger value="raw">타임스탬프 포함</TabsTrigger>
                    <TabsTrigger value="clean">정리본</TabsTrigger>
                  </TabsList>
                  <TabsContent value="raw" className="mt-2">
                    <pre
                      ref={transcriptRef}
                      className="max-h-72 overflow-y-auto rounded-lg border bg-muted/30 p-2 text-xs whitespace-pre-wrap"
                    >
                      {transcriptText}
                    </pre>
                  </TabsContent>
                  <TabsContent value="clean" className="mt-2">
                    <pre className="max-h-72 overflow-y-auto rounded-lg border bg-muted/30 p-2 text-xs whitespace-pre-wrap">
                      {cleanTranscript(transcriptText)}
                    </pre>
                  </TabsContent>
                </Tabs>
              ) : (
                <p className="rounded-lg border p-2 text-xs text-muted-foreground">
                  보정 자막 없음
                </p>
              )}
            </div>
          </div>
        </DetailSection>
      ) : null}

      <div className="flex flex-col gap-2 border-t pt-3">
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={deepResearchMutation.isPending}
          onClick={() => deepResearchMutation.mutate()}
        >
          {deepResearchMutation.isPending ? (
            <Loader2Icon data-icon="inline-start" className="animate-spin" />
          ) : (
            <FlaskConicalIcon data-icon="inline-start" />
          )}
          Deep Research
        </Button>
        {deepResearchMutation.error ? (
          <p className="text-xs text-destructive">
            {deepResearchMutation.error.message}
          </p>
        ) : deepResearchMutation.isSuccess ? (
          <p className="text-xs text-muted-foreground">
            Deep Research 작업을 시작했습니다. 완료되면 심층 조사에 반영됩니다.
          </p>
        ) : null}
        {confirmDelete ? (
          <div className="flex flex-col gap-2">
            <span className="text-sm font-medium text-destructive">
              정말 삭제할까요? 이 장소를 만든 검수 후보는 검수 큐로 되돌아갑니다.
            </span>
            <div className="flex flex-wrap items-center gap-2">
              <Button
                type="button"
                size="sm"
                variant="destructive"
                disabled={deleteMutation.isPending}
                onClick={() => deleteMutation.mutate()}
              >
                {deleteMutation.isPending ? (
                  <Loader2Icon
                    data-icon="inline-start"
                    className="animate-spin"
                  />
                ) : null}
                삭제
              </Button>
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={() => setConfirmDelete(false)}
              >
                취소
              </Button>
            </div>
          </div>
        ) : (
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => setConfirmDelete(true)}
          >
            <Trash2Icon data-icon="inline-start" />
            장소 삭제
          </Button>
        )}
        {deleteMutation.error ? (
          <p className="mt-1 text-xs text-destructive">
            {deleteMutation.error.message}
          </p>
        ) : null}
      </div>
    </div>
  );
}

function DetailSection({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <section className="flex flex-col gap-1.5 border-t pt-3">
      <h4 className="text-xs font-semibold text-muted-foreground">{title}</h4>
      {children}
    </section>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="flex flex-col gap-1 rounded-lg border p-2.5">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="text-lg font-semibold">{value.toLocaleString()}</span>
    </div>
  );
}
