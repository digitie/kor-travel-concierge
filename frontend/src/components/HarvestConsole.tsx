"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  AlertCircleIcon,
  CheckCircle2Icon,
  Loader2Icon,
  PlayIcon,
} from "lucide-react";
import { useMemo, useState } from "react";
import { useForm, useWatch } from "react-hook-form";
import { z } from "zod";

import {
  getHarvestStatus,
  listRunQueue,
  startHarvest,
  type CrawlRunSummary,
  type HarvestStatus,
  type HarvestTargetType,
} from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Field,
  FieldDescription,
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

const targetLabels: Record<HarvestTargetType, string> = {
  keyword: "검색어",
  channel: "채널 ID",
  playlist: "재생목록 ID",
};

const targetPlaceholders: Record<HarvestTargetType, string> = {
  keyword: "예: 부산 맛집",
  channel: "예: UCxxxxxxxx",
  playlist: "예: PLxxxxxxxx",
};

const harvestFormSchema = z.object({
  targetType: z.enum(["keyword", "channel", "playlist"]),
  targetValue: z.string().trim().min(1, "수집 대상을 입력하세요."),
  maxVideos: z.coerce
    .number()
    .int("정수로 입력하세요.")
    .min(1, "최소 1개 이상 입력하세요.")
    .max(50, "한 번에 최대 50개까지 요청할 수 있습니다."),
});

type HarvestFormValues = z.infer<typeof harvestFormSchema>;

export function HarvestConsole() {
  const [jobId, setJobId] = useState<string | null>(null);
  const form = useForm<HarvestFormValues>({
    resolver: zodResolver(harvestFormSchema),
    defaultValues: {
      targetType: "keyword",
      targetValue: "부산 맛집",
      maxVideos: 10,
    },
  });
  const targetType = useWatch({
    control: form.control,
    name: "targetType",
  });

  const mutation = useMutation({
    mutationFn: startHarvest,
    onSuccess: (job) => {
      setJobId(job.job_id);
    },
  });

  const statusQuery = useQuery({
    queryKey: ["harvest-status", jobId],
    queryFn: () => getHarvestStatus(jobId as string),
    enabled: Boolean(jobId),
    refetchInterval: (query) => {
      const data = query.state.data as HarvestStatus | undefined;
      return data?.state === "pending" || data?.state === "running" ? 1_500 : false;
    },
  });
  const runQueueQuery = useQuery({
    queryKey: ["harvest-console-run-queue"],
    queryFn: listRunQueue,
    refetchInterval: 2_000,
  });

  const status = statusQuery.data;
  const statusTone = useMemo(() => statusBadgeVariant(status?.state), [status?.state]);
  const statusLogs = status?.status_logs ?? [];
  const queueRuns = runQueueQuery.data ?? [];

  return (
    <div className="flex h-full flex-col gap-6 bg-background p-5">
      <header className="flex flex-col gap-1">
        <h1 className="text-xl font-semibold tracking-normal">KRTour AI Agent</h1>
        <p className="text-sm text-muted-foreground">
          YouTube 여행 수집 작업
        </p>
      </header>

      <form
        className="flex flex-col gap-5"
        onSubmit={form.handleSubmit((values) => mutation.mutate(values))}
      >
        <FieldGroup>
          <Field data-invalid={Boolean(form.formState.errors.targetType)}>
            <FieldLabel>대상 유형</FieldLabel>
            <Select
              value={targetType}
              onValueChange={(value) =>
                form.setValue("targetType", value as HarvestTargetType, {
                  shouldDirty: true,
                  shouldValidate: true,
                })
              }
            >
              <SelectTrigger
                className="w-full"
                aria-invalid={Boolean(form.formState.errors.targetType)}
              >
                <SelectValue>{targetLabels[targetType]}</SelectValue>
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  <SelectItem value="keyword">검색어</SelectItem>
                  <SelectItem value="channel">채널</SelectItem>
                  <SelectItem value="playlist">재생목록</SelectItem>
                </SelectGroup>
              </SelectContent>
            </Select>
            <FieldError errors={[form.formState.errors.targetType]} />
          </Field>

          <Field data-invalid={Boolean(form.formState.errors.targetValue)}>
            <FieldLabel htmlFor="harvest-target">
              {targetLabels[targetType]}
            </FieldLabel>
            <Input
              id="harvest-target"
              placeholder={targetPlaceholders[targetType]}
              aria-invalid={Boolean(form.formState.errors.targetValue)}
              {...form.register("targetValue")}
            />
            <FieldError errors={[form.formState.errors.targetValue]} />
          </Field>

          <Field data-invalid={Boolean(form.formState.errors.maxVideos)}>
            <FieldLabel htmlFor="harvest-max-videos">최대 영상 수</FieldLabel>
            <Input
              id="harvest-max-videos"
              type="number"
              min={1}
              max={50}
              aria-invalid={Boolean(form.formState.errors.maxVideos)}
              {...form.register("maxVideos", { valueAsNumber: true })}
            />
            <FieldDescription>1-50</FieldDescription>
            <FieldError errors={[form.formState.errors.maxVideos]} />
          </Field>
        </FieldGroup>

        <Button type="submit" disabled={mutation.isPending}>
          {mutation.isPending ? (
            <Loader2Icon data-icon="inline-start" className="animate-spin" />
          ) : (
            <PlayIcon data-icon="inline-start" />
          )}
          수집 시작
        </Button>
      </form>

      <section className="flex flex-col gap-3 border-t pt-5">
        <div className="flex items-center justify-between gap-3">
          <h2 className="text-sm font-medium">실행 큐</h2>
          <Badge variant="outline">{queueRuns.length}</Badge>
        </div>
        {queueRuns.length > 0 ? (
          <div className="flex max-h-52 flex-col gap-2 overflow-y-auto">
            {queueRuns.map((run) => (
              <QueueRunItem key={run.job_id} run={run} />
            ))}
          </div>
        ) : (
          <p className="rounded-md border bg-muted/30 p-3 text-xs text-muted-foreground">
            실행 중이거나 대기 중인 작업이 없습니다.
          </p>
        )}
        {runQueueQuery.error ? (
          <p className="text-sm text-destructive">{runQueueQuery.error.message}</p>
        ) : null}
      </section>

      <section className="flex flex-col gap-3 border-t pt-5" aria-live="polite">
        <div className="flex items-center justify-between gap-3">
          <h2 className="text-sm font-medium">작업 상태</h2>
          {status ? (
            <Badge variant={statusTone.variant}>
              {statusTone.icon}
              {status.state}
            </Badge>
          ) : (
            <Badge variant="outline">대기</Badge>
          )}
        </div>

        <div className="flex flex-col gap-2 text-sm">
          <StatusRow label="job_id" value={jobId ?? "-"} />
          <StatusRow
            label="progress"
            value={status ? `${Math.round(status.progress * 100)}%` : "-"}
          />
          <StatusRow
            label="현재"
            value={status?.current_message ?? "작업이 아직 시작되지 않았습니다."}
            wrap
          />
          <StatusRow label="error" value={status?.last_error ?? "-"} />
        </div>

        <div className="flex flex-col gap-2 rounded-md border bg-muted/30 p-3">
          <div className="flex items-center justify-between gap-3">
            <p className="text-xs font-medium">상세 로그</p>
            <span className="text-xs text-muted-foreground">{statusLogs.length}건</span>
          </div>
          {statusLogs.length > 0 ? (
            <ol className="flex max-h-56 flex-col gap-2 overflow-y-auto">
              {statusLogs.map((log, index) => (
                <li
                  key={`${log.timestamp}-${index}`}
                  className="grid grid-cols-[4.5rem_1fr_auto] gap-2 text-xs"
                >
                  <span className="text-muted-foreground">
                    {formatLogTime(log.timestamp)}
                  </span>
                  <span className={`${logToneClass(log.level)} min-w-0 break-words`}>
                    {log.message}
                  </span>
                  <span className="text-muted-foreground">
                    {log.progress === null ? "" : `${Math.round(log.progress * 100)}%`}
                  </span>
                </li>
              ))}
            </ol>
          ) : (
            <p className="text-xs text-muted-foreground">아직 상세 로그가 없습니다.</p>
          )}
        </div>

        {mutation.error ? (
          <p className="text-sm text-destructive">{mutation.error.message}</p>
        ) : null}
        {statusQuery.error ? (
          <p className="text-sm text-destructive">{statusQuery.error.message}</p>
        ) : null}
      </section>
    </div>
  );
}

function QueueRunItem({ run }: { run: CrawlRunSummary }) {
  return (
    <div className="flex flex-col gap-2 rounded-md border p-3 text-xs">
      <div className="flex items-center justify-between gap-2">
        <span className="min-w-0 truncate font-medium">{runLabel(run)}</span>
        <Badge variant={run.state === "running" ? "default" : "outline"}>
          {run.state}
        </Badge>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-muted">
        <div
          className="h-full rounded-full bg-primary"
          style={{ width: `${Math.round(run.progress * 100)}%` }}
        />
      </div>
      <div className="flex items-start justify-between gap-2">
        <span className="min-w-0 break-words text-muted-foreground">
          {run.current_message ?? latestRunLog(run) ?? "상세 로그 대기 중"}
        </span>
        <span className="shrink-0 text-muted-foreground">
          {Math.round(run.progress * 100)}%
        </span>
      </div>
    </div>
  );
}

function runLabel(run: CrawlRunSummary) {
  return [run.job_type, run.target_id].filter(Boolean).join(" · ");
}

function latestRunLog(run: CrawlRunSummary) {
  return run.status_logs.at(-1)?.message ?? null;
}

function StatusRow({
  label,
  value,
  wrap = false,
}: {
  label: string;
  value: string;
  wrap?: boolean;
}) {
  return (
    <div className="flex items-start justify-between gap-3">
      <span className="text-muted-foreground">{label}</span>
      <span
        className={
          wrap
            ? "max-w-[13rem] text-right font-medium leading-5"
            : "max-w-[12rem] truncate text-right font-medium"
        }
      >
        {value}
      </span>
    </div>
  );
}

function formatLogTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("ko-KR", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(date);
}

function logToneClass(level: string) {
  if (level === "success") {
    return "text-emerald-700";
  }
  if (level === "warning") {
    return "text-amber-700";
  }
  if (level === "error") {
    return "text-destructive";
  }
  return "text-foreground";
}

function statusBadgeVariant(state: string | undefined): {
  variant: "default" | "secondary" | "destructive" | "outline";
  icon: React.ReactNode;
} {
  if (state === "done") {
    return {
      variant: "secondary",
      icon: <CheckCircle2Icon data-icon="inline-start" />,
    };
  }
  if (state === "failed") {
    return {
      variant: "destructive",
      icon: <AlertCircleIcon data-icon="inline-start" />,
    };
  }
  if (state === "pending" || state === "running") {
    return {
      variant: "default",
      icon: <Loader2Icon data-icon="inline-start" className="animate-spin" />,
    };
  }
  return { variant: "outline", icon: null };
}
