"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  getSourceTargetVideos,
  listCategories,
  runSourceTargetNow,
  updateSourceTarget,
  type CategoryOption,
  type SourceTargetSummary,
} from "@/lib/api";
import { categoryDisplayLabel } from "@/lib/display-labels";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Field, FieldDescription, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

const INTERVAL_OPTIONS = [
  { value: 60, label: "1시간" },
  { value: 720, label: "12시간" },
  { value: 1440, label: "1일" },
  { value: 10080, label: "1주일" },
  { value: 20160, label: "2주일" },
  { value: 43200, label: "1달" },
  { value: 129600, label: "3달" },
];

function intervalLabel(value: number): string {
  return (
    INTERVAL_OPTIONS.find((option) => option.value === value)?.label ??
    `${value}분`
  );
}

function targetTypeLabel(type: string | null | undefined): string {
  if (type === "channel") return "유튜버";
  if (type === "playlist") return "재생목록";
  if (type === "keyword") return "검색어";
  if (type === "video") return "영상";
  return type ?? "대상";
}

function targetDisplayName(target: SourceTargetSummary | null): string {
  if (!target) return "작업";
  return target.target_label ?? target.display_name ?? target.source_value;
}

function formatDateTime(value: string | null | undefined): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  return date.toLocaleString("ko-KR", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatDate(value: string | null | undefined): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  return date.toLocaleDateString("ko-KR", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });
}

function categoryLabel(
  categories: CategoryOption[] | undefined,
  code: string | null | undefined,
): string {
  return categoryDisplayLabel(
    categories?.find((category) => category.code === code)?.label ?? code,
  );
}

export function RecurringEditDialog({
  target,
  onClose,
}: {
  target: SourceTargetSummary | null;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const open = Boolean(target);
  const [intervalEdit, setIntervalEdit] = useState<number | null>(null);
  const [maxRunsEdit, setMaxRunsEdit] = useState<number | null>(null);
  const [maxVideosEdit, setMaxVideosEdit] = useState<number | null>(null);
  const [activeEdit, setActiveEdit] = useState<boolean | null>(null);
  const [defaultCategoryEdit, setDefaultCategoryEdit] = useState<string | null>(
    null,
  );
  const [forceRunOnce, setForceRunOnce] = useState(false);

  const interval = intervalEdit ?? target?.scan_interval_minutes ?? 1440;
  const maxRuns = maxRunsEdit ?? target?.max_runs ?? 0;
  const maxVideos = maxVideosEdit ?? target?.max_videos ?? 20;
  const active = activeEdit ?? target?.is_active ?? true;
  const defaultCategoryCode =
    defaultCategoryEdit ?? target?.default_category_code ?? "0";
  const title = `${targetDisplayName(target)} 작업 수정`;
  const targetKind =
    target?.target_type_label ?? targetTypeLabel(target?.target_type);

  const videosQuery = useQuery({
    queryKey: ["source-target-videos", target?.id],
    queryFn: () => getSourceTargetVideos(target!.id),
    enabled: open && target != null,
  });
  const categoriesQuery = useQuery({
    queryKey: ["categories"],
    queryFn: listCategories,
    staleTime: 60 * 60 * 1000,
  });
  const videos = videosQuery.data ?? [];
  const lastVideoPublishedAt =
    videos
      .map((video) => video.published_at)
      .filter(Boolean)
      .sort()
      .at(-1) ??
    target?.last_seen_video_published_at ??
    null;

  function close() {
    setIntervalEdit(null);
    setMaxRunsEdit(null);
    setMaxVideosEdit(null);
    setActiveEdit(null);
    setDefaultCategoryEdit(null);
    setForceRunOnce(false);
    onClose();
  }

  const mutation = useMutation({
    mutationFn: async () => {
      const updated = await updateSourceTarget(target!.id, {
        scanIntervalMinutes: interval,
        maxRuns,
        maxVideos,
        isActive: active,
        defaultCategoryCode,
      });
      if (forceRunOnce) {
        await runSourceTargetNow(target!.id, true);
      }
      return updated;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["source-targets"] });
      queryClient.invalidateQueries({ queryKey: ["runs"] });
      queryClient.invalidateQueries({ queryKey: ["run-queue"] });
      close();
    },
  });

  return (
    <Dialog open={open} onOpenChange={(next) => !next && close()}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>
            {targetKind} · {target?.source_value}
          </DialogDescription>
        </DialogHeader>

        <section className="grid gap-2 sm:grid-cols-2">
          <SummaryItem
            label="누적 수집 영상"
            value={videosQuery.isLoading ? "확인 중" : `${videos.length.toLocaleString()}개`}
          />
          <SummaryItem
            label="실행 횟수"
            value={
              target?.max_runs === 0
                ? `${target?.run_count ?? 0}회 / 무한`
                : `${target?.run_count ?? 0}회 / ${target?.max_runs ?? 0}회`
            }
          />
          <SummaryItem
            label="마지막 수집"
            value={formatDateTime(target?.last_crawled_at)}
          />
          <SummaryItem
            label="마지막 영상 날짜"
            value={formatDate(lastVideoPublishedAt)}
          />
          <SummaryItem
            label="마지막 스캔"
            value={formatDateTime(target?.last_scan_at)}
          />
          <SummaryItem
            label="다음 실행"
            value={formatDateTime(target?.next_crawl_at)}
          />
          <SummaryItem
            label="기본 카테고리"
            value={categoryLabel(categoriesQuery.data, defaultCategoryCode)}
          />
        </section>

        {target?.last_scan_error ? (
          <p className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-xs text-destructive">
            최근 오류: {target.last_scan_error}
          </p>
        ) : null}

        <section className="flex flex-col gap-4 border-t pt-4">
          <Field>
            <FieldLabel htmlFor="recurring-edit-interval">반복 간격</FieldLabel>
            <Select
              value={String(interval)}
              onValueChange={(value) => setIntervalEdit(Number(value))}
            >
              <SelectTrigger id="recurring-edit-interval" className="w-full">
                <SelectValue>{intervalLabel(interval)}</SelectValue>
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  {INTERVAL_OPTIONS.map((option) => (
                    <SelectItem key={option.value} value={String(option.value)}>
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectGroup>
              </SelectContent>
            </Select>
          </Field>

          <div className="grid gap-4 sm:grid-cols-2">
            <Field>
              <FieldLabel htmlFor="recurring-edit-count">반복 횟수</FieldLabel>
              <Input
                id="recurring-edit-count"
                type="number"
                min={0}
                value={String(maxRuns)}
                onChange={(event) =>
                  setMaxRunsEdit(Math.max(0, Number(event.target.value) || 0))
                }
              />
              <FieldDescription>0이면 무한 반복합니다.</FieldDescription>
            </Field>

            <Field>
              <FieldLabel htmlFor="recurring-edit-max-videos">수집개수(영상 수)</FieldLabel>
              <Input
                id="recurring-edit-max-videos"
                type="number"
                min={1}
                max={300}
                value={String(maxVideos)}
                onChange={(event) =>
                  setMaxVideosEdit(
                    Math.max(1, Math.min(300, Number(event.target.value) || 1)),
                  )
                }
              />
              <FieldDescription>반복 1회당 받을 영상 수 (1-300).</FieldDescription>
            </Field>
          </div>

          <Field>
            <FieldLabel htmlFor="recurring-edit-category">기본 카테고리</FieldLabel>
            <Select
              value={defaultCategoryCode}
              onValueChange={(value) => setDefaultCategoryEdit(value)}
            >
              <SelectTrigger id="recurring-edit-category" className="w-full">
                <SelectValue>
                  {categoryLabel(categoriesQuery.data, defaultCategoryCode)}
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
            <FieldDescription>
              카테고리 매칭 실패 시 이 값으로 저장합니다.
            </FieldDescription>
          </Field>

          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              className="size-4 rounded border"
              checked={active}
              onChange={(event) => setActiveEdit(event.target.checked)}
            />
            반복 수집 사용
          </label>

          <label className="flex items-start gap-2 rounded-lg border border-warning/30 bg-warning/10 p-3 text-sm">
            <input
              type="checkbox"
              className="mt-0.5 size-4 rounded border"
              checked={forceRunOnce}
              onChange={(event) => setForceRunOnce(event.target.checked)}
            />
            <span className="flex flex-col gap-0.5">
              <span className="font-medium">강제 다운로드 (전체 재수집)</span>
              <span className="text-xs text-muted-foreground">
                저장 직후 한 번만 전체 재수집 작업을 실행합니다. 이 체크 상태는 저장되지 않습니다.
              </span>
            </span>
          </label>
        </section>

        {mutation.error ? (
          <p className="text-xs text-destructive">{mutation.error.message}</p>
        ) : null}

        <DialogFooter>
          <DialogClose
            render={
              <Button type="button" variant="outline">
                닫기
              </Button>
            }
          />
          <Button
            type="button"
            onClick={() => mutation.mutate()}
            disabled={mutation.isPending}
          >
            저장
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function SummaryItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-1 rounded-lg border border-surface-muted bg-surface-subtle p-3">
      <span className="text-[12px] font-bold tracking-[0.05em] text-text-secondary uppercase">
        {label}
      </span>
      <span className="text-[14px] font-bold text-text-primary">{value}</span>
    </div>
  );
}
