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
import { categoryDisplayLabel, targetTypeDisplayLabel } from "@/lib/display-labels";
import { formatDate, formatDateTime } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Field, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { HelpTip } from "@/components/HelpTip";
import { Metric } from "@/components/panels";

const INTERVAL_OPTIONS = [
  { value: 60, label: "1시간" },
  { value: 720, label: "12시간" },
  { value: 1440, label: "1일" },
  { value: 10080, label: "1주일" },
  { value: 20160, label: "2주일" },
  { value: 43200, label: "1달" },
  { value: 129600, label: "3달" },
];

function intervalOptionLabel(value: number): string {
  return (
    INTERVAL_OPTIONS.find((option) => option.value === value)?.label ??
    `${value}분`
  );
}

function targetDisplayName(target: SourceTargetSummary | null): string {
  if (!target) return "작업";
  return target.target_label ?? target.display_name ?? target.source_value;
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
    target?.target_type_label ?? targetTypeDisplayLabel(target?.target_type);

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
          <Metric
            label="누적 수집 영상"
            value={
              videosQuery.isLoading ? "확인 중" : `${videos.length.toLocaleString()}개`
            }
          />
          <Metric
            label="실행 횟수"
            value={
              target?.max_runs === 0
                ? `${target?.run_count ?? 0}회 / 무한`
                : `${target?.run_count ?? 0}회 / ${target?.max_runs ?? 0}회`
            }
          />
          <Metric label="마지막 수집" value={formatDateTime(target?.last_crawled_at)} />
          <Metric label="마지막 영상 날짜" value={formatDate(lastVideoPublishedAt)} />
          <Metric label="마지막 스캔" value={formatDateTime(target?.last_scan_at)} />
          <Metric label="다음 실행" value={formatDateTime(target?.next_crawl_at)} />
          <Metric
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
                <SelectValue>{intervalOptionLabel(interval)}</SelectValue>
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
              <div className="flex items-center gap-1">
                <FieldLabel htmlFor="recurring-edit-count">반복 횟수</FieldLabel>
                <HelpTip>0이면 중지할 때까지 무한 반복합니다.</HelpTip>
              </div>
              <Input
                id="recurring-edit-count"
                type="number"
                min={0}
                value={String(maxRuns)}
                onChange={(event) =>
                  setMaxRunsEdit(Math.max(0, Number(event.target.value) || 0))
                }
              />
            </Field>

            <Field>
              <div className="flex items-center gap-1">
                <FieldLabel htmlFor="recurring-edit-max-videos">
                  수집개수(영상 수)
                </FieldLabel>
                <HelpTip>반복 1회당 받을 영상 수(1~300)입니다.</HelpTip>
              </div>
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
            </Field>
          </div>

          <Field>
            <div className="flex items-center gap-1">
              <FieldLabel htmlFor="recurring-edit-category">기본 카테고리</FieldLabel>
              <HelpTip>카테고리 매칭에 실패한 장소는 이 값으로 저장합니다.</HelpTip>
            </div>
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
          </Field>

          {/* 저장 버튼으로 반영되는 폼 값이므로 Switch(즉시 적용 암시)가 아니라 Checkbox. */}
          <label className="flex items-center gap-2 text-sm font-medium">
            <Checkbox
              checked={active}
              onCheckedChange={(checked) => setActiveEdit(Boolean(checked))}
            />
            반복 수집 사용
          </label>

          <label className="flex items-start gap-2 rounded-lg border border-warning/30 bg-warning/10 p-3 text-sm">
            <Checkbox
              className="mt-0.5"
              checked={forceRunOnce}
              onCheckedChange={(checked) => setForceRunOnce(Boolean(checked))}
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
