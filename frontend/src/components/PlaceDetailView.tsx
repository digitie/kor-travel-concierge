"use client";

import { useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ExternalLinkIcon,
  FlaskConicalIcon,
  Loader2Icon,
  Trash2Icon,
} from "lucide-react";

import { deletePlace, getPlaceDetail, triggerDeepResearch } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

function dateLabel(value: string | null): string {
  return value ? value.slice(0, 10) : "";
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
                <a
                  href={video.url}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex min-w-0 items-center gap-1 truncate font-medium text-primary hover:underline"
                >
                  {video.title ?? video.video_id}
                  <ExternalLinkIcon className="size-3 shrink-0" />
                </a>
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
