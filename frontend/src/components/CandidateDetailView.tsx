"use client";

import { useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ExternalLinkIcon, Loader2Icon, Trash2Icon } from "lucide-react";

import { deleteCandidate, getCandidateDetail } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

function durationLabel(seconds: number | null): string {
  if (seconds == null) return "";
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return m > 0 ? `${m}분 ${s}초` : `${s}초`;
}
function dateLabel(value: string | null): string {
  return value ? value.slice(0, 10) : "";
}

export function CandidateDetailView({
  candidateId,
  onDeleted,
}: {
  candidateId: number;
  onDeleted?: () => void;
}) {
  const queryClient = useQueryClient();
  const detailQuery = useQuery({
    queryKey: ["candidate-detail", candidateId],
    queryFn: () => getCandidateDetail(candidateId),
  });
  const detail = detailQuery.data;
  const [confirmDelete, setConfirmDelete] = useState(false);
  const deleteMutation = useMutation({
    mutationFn: () => deleteCandidate(candidateId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["unmatched-candidates"] });
      onDeleted?.();
    },
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

  const c = detail.candidate;

  return (
    <div className="flex flex-col gap-4">
      <div>
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="text-base font-semibold">{c.ai_place_name}</h3>
          {c.candidate_category ? (
            <Badge variant="outline">{c.candidate_category}</Badge>
          ) : null}
          <Badge variant="secondary">{c.match_status}</Badge>
          {c.confidence_score != null ? (
            <Badge variant="outline">
              신뢰도 {Math.round(c.confidence_score * 100)}%
            </Badge>
          ) : null}
        </div>
        {c.location_hint ? (
          <p className="mt-1 text-sm text-muted-foreground">
            위치 힌트: {c.location_hint}
          </p>
        ) : null}
      </div>

      {detail.source_run ? (
        <DetailSection title="추출 작업(어느 큐)">
          <DetailRow
            label="작업 유형"
            value={
              detail.source_run.run_type_label ??
              detail.source_run.run_type ??
              "-"
            }
          />
          <DetailRow label="상태" value={detail.source_run.state ?? "-"} />
          {detail.source_run.model ? (
            <DetailRow label="모델" value={detail.source_run.model} />
          ) : null}
        </DetailSection>
      ) : null}

      {detail.video ? (
        <DetailSection title="동영상">
          <a
            href={detail.video.url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 font-medium text-primary hover:underline"
          >
            {detail.video.title ?? detail.video.video_id}
            <ExternalLinkIcon className="size-3" />
          </a>
          <p className="text-xs text-muted-foreground">
            {[
              detail.video.channel_title,
              durationLabel(detail.video.duration_seconds),
              dateLabel(detail.video.published_at),
            ]
              .filter(Boolean)
              .join(" · ")}
          </p>
          {detail.video.description ? (
            <p className="line-clamp-4 text-xs text-muted-foreground">
              {detail.video.description}
            </p>
          ) : null}
        </DetailSection>
      ) : null}

      <DetailSection title="동영상 내 근거(어디에 나왔는지)">
        <DetailRow
          label="구간"
          value={
            [c.timestamp_start, c.timestamp_end].filter(Boolean).join(" ~ ") ||
            "-"
          }
        />
        <DetailRow label="출처" value={c.source_kind ?? "-"} />
        {c.source_text ? (
          <p className="rounded-lg border bg-muted/30 p-2 text-xs whitespace-pre-wrap">
            {c.source_text}
          </p>
        ) : null}
        {c.speaker_note ? (
          <p className="text-xs text-muted-foreground">메모: {c.speaker_note}</p>
        ) : null}
      </DetailSection>

      {detail.sibling_candidates.length > 0 ? (
        <DetailSection
          title={`같은 동영상의 다른 장소 (${detail.sibling_candidates.length})`}
        >
          <div className="flex flex-col gap-1">
            {detail.sibling_candidates.map((sibling) => (
              <div
                key={sibling.id}
                className="flex items-center justify-between gap-2 text-xs"
              >
                <span className="truncate">{sibling.ai_place_name}</span>
                <Badge variant="outline">{sibling.match_status}</Badge>
              </div>
            ))}
          </div>
        </DetailSection>
      ) : null}

      <div className="border-t pt-3">
        {confirmDelete ? (
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-medium text-destructive">
              정말 삭제할까요? 되돌릴 수 없습니다.
            </span>
            <Button
              type="button"
              size="sm"
              variant="destructive"
              disabled={deleteMutation.isPending}
              onClick={() => deleteMutation.mutate()}
            >
              {deleteMutation.isPending ? (
                <Loader2Icon data-icon="inline-start" className="animate-spin" />
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
        ) : (
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => setConfirmDelete(true)}
          >
            <Trash2Icon data-icon="inline-start" />
            후보 삭제
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
    <section className="flex flex-col gap-1.5">
      <h4 className="text-xs font-semibold text-muted-foreground">{title}</h4>
      {children}
    </section>
  );
}

function DetailRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3 text-sm">
      <span className="shrink-0 text-muted-foreground">{label}</span>
      <span className="truncate text-right font-medium">{value}</span>
    </div>
  );
}
