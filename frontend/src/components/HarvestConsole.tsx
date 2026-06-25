"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  AlertCircleIcon,
  CheckCircle2Icon,
  FileTextIcon,
  Loader2Icon,
  PlayIcon,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useForm, useWatch } from "react-hook-form";
import { z } from "zod";

import {
  getHarvestStatus,
  startHarvest,
  startTranscript,
  type HarvestContentFilter,
  type HarvestStatus,
  type HarvestTargetType,
} from "@/lib/api";
import { JobLogDialog } from "@/components/JobLogDialog";
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
  auto: "링크 또는 검색어",
  keyword: "검색어",
  channel: "채널명 또는 URL",
  playlist: "재생목록 URL",
  video: "영상 URL 또는 ID",
};

const targetPlaceholders: Record<HarvestTargetType, string> = {
  auto: "링크(재생목록·채널·영상)나 검색어를 붙여넣으면 자동 판별합니다",
  keyword: "예: 부산 맛집",
  channel: "예: @빵이네tv · youtube.com/@... · 채널 URL · UC...",
  playlist: "예: youtube.com/playlist?list=... · PL...",
  video: "예: youtube.com/watch?v=... · youtu.be/... · 11자 ID",
};

// 반복 검색 간격 선택지(분).
const repeatIntervalOptions: { value: number; label: string }[] = [
  { value: 60, label: "1시간" },
  { value: 720, label: "12시간" },
  { value: 1440, label: "1일" },
  { value: 10080, label: "1주일" },
  { value: 20160, label: "2주일" },
  { value: 43200, label: "1달" },
  { value: 129600, label: "3달" },
];

function repeatIntervalLabel(value: number): string {
  return (
    repeatIntervalOptions.find((option) => option.value === value)?.label ??
    `${value}분`
  );
}

// 콘텐츠 유형 필터 선택지.
const contentFilterOptions: { value: HarvestContentFilter; label: string }[] = [
  { value: "both", label: "숏츠+동영상" },
  { value: "shorts", label: "숏츠만" },
  { value: "videos", label: "동영상만" },
];

function contentFilterLabel(value: HarvestContentFilter): string {
  return (
    contentFilterOptions.find((option) => option.value === value)?.label ??
    "숏츠+동영상"
  );
}

const harvestFormSchema = z.object({
  targetType: z.enum(["auto", "keyword", "channel", "playlist", "video"]),
  targetValue: z.string().trim().min(1, "수집 대상을 입력하세요."),
  maxVideos: z.coerce
    .number()
    .int("정수로 입력하세요.")
    .min(1, "최소 1개 이상 입력하세요.")
    .max(300, "한 번에 최대 300개까지 요청할 수 있습니다."),
  repeat: z.boolean(),
  repeatIntervalMinutes: z.coerce.number().int().min(1),
  repeatMaxRuns: z.coerce.number().int().min(0),
  contentFilter: z.enum(["both", "shorts", "videos"]),
  // 강제 다운로드: 증분 워터마크 무시하고 처음부터 재수집(기본은 증분 추가).
  force: z.boolean(),
});

type HarvestFormValues = z.infer<typeof harvestFormSchema>;

const JOB_ID_STORAGE_KEY = "ktc.harvest.jobId";
const TRANSCRIPT_JOB_ID_STORAGE_KEY = "ktc.harvest.transcriptJobId";

export function HarvestConsole() {
  const [jobId, setJobId] = useState<string | null>(null);
  const [transcriptJobId, setTranscriptJobId] = useState<string | null>(null);
  const [logDialogStatus, setLogDialogStatus] = useState<HarvestStatus | null>(
    null,
  );

  // 다른 페이지에 다녀와도 진행 중인 수집 작업의 상태·로그가 사라지지 않도록 작업 id를
  // localStorage에 보존한다. 마운트 시 복원하면 statusQuery가 백엔드에서 상태·로그를 재조회.
  // hydration 안전(서버=null, 클라=저장값)을 위해 마운트 후 1회 setState가 필요하므로
  // set-state-in-effect를 이 복원 effect에 한해 허용한다.
  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    const savedJob = window.localStorage.getItem(JOB_ID_STORAGE_KEY);
    if (savedJob) setJobId(savedJob);
    const savedTranscript = window.localStorage.getItem(TRANSCRIPT_JOB_ID_STORAGE_KEY);
    if (savedTranscript) setTranscriptJobId(savedTranscript);
  }, []);
  /* eslint-enable react-hooks/set-state-in-effect */
  useEffect(() => {
    if (jobId) window.localStorage.setItem(JOB_ID_STORAGE_KEY, jobId);
  }, [jobId]);
  useEffect(() => {
    if (transcriptJobId)
      window.localStorage.setItem(TRANSCRIPT_JOB_ID_STORAGE_KEY, transcriptJobId);
  }, [transcriptJobId]);

  const form = useForm<HarvestFormValues>({
    resolver: zodResolver(harvestFormSchema),
    defaultValues: {
      targetType: "auto",
      targetValue: "",
      maxVideos: 10,
      repeat: false,
      repeatIntervalMinutes: 1440,
      repeatMaxRuns: 0,
      contentFilter: "both",
      force: false,
    },
  });
  const targetType = useWatch({
    control: form.control,
    name: "targetType",
  });
  const repeat = useWatch({ control: form.control, name: "repeat" });
  const repeatIntervalMinutes = useWatch({
    control: form.control,
    name: "repeatIntervalMinutes",
  });
  const repeatMaxRuns = useWatch({ control: form.control, name: "repeatMaxRuns" });
  const contentFilter = useWatch({
    control: form.control,
    name: "contentFilter",
  });
  const force = useWatch({ control: form.control, name: "force" });

  const mutation = useMutation({
    mutationFn: startHarvest,
    onSuccess: (job) => {
      setJobId(job.job_id);
      setTranscriptJobId(null);
      // 새 수집 시작 시 직전 자막 작업 id는 정리한다(persist effect는 null을 지우지 않음).
      window.localStorage.removeItem(TRANSCRIPT_JOB_ID_STORAGE_KEY);
    },
  });

  const transcriptMutation = useMutation({
    mutationFn: startTranscript,
    onSuccess: (job) => {
      setTranscriptJobId(job.job_id);
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
  const transcriptStatusQuery = useQuery({
    queryKey: ["transcript-status", transcriptJobId],
    queryFn: () => getHarvestStatus(transcriptJobId as string),
    enabled: Boolean(transcriptJobId),
    refetchInterval: (query) => {
      const data = query.state.data as HarvestStatus | undefined;
      return data?.state === "pending" || data?.state === "running" ? 1_500 : false;
    },
  });

  const status = statusQuery.data;
  const statusTone = useMemo(() => statusBadgeVariant(status?.state), [status?.state]);
  const statusLogs = status?.status_logs ?? [];

  const harvestResult = (status?.result ?? null) as
    | { transcript_skipped?: boolean; video_ids?: string[] }
    | null;
  const collectedVideoIds = harvestResult?.video_ids ?? [];
  const transcriptReady =
    status?.state === "done" &&
    harvestResult?.transcript_skipped === true &&
    collectedVideoIds.length > 0;
  const transcriptStatus = transcriptStatusQuery.data;
  const transcriptTone = useMemo(
    () => statusBadgeVariant(transcriptStatus?.state),
    [transcriptStatus?.state],
  );
  const transcriptLogs = transcriptStatus?.status_logs ?? [];

  return (
    <div className="flex h-full flex-col gap-6 bg-background p-5">
      <header className="flex flex-col gap-1">
        <h1 className="text-base font-semibold tracking-normal">수집 작업</h1>
        <p className="text-sm text-muted-foreground">
          키워드·유튜버·재생목록으로 YouTube를 수집합니다.
        </p>
      </header>

      <form
        className="flex flex-col gap-5"
        onSubmit={form.handleSubmit((values) =>
          mutation.mutate({
            ...values,
            // 자막 추출→POI→지오코딩→DB 저장까지 자동 완료(별도 확인 단계 없음).
            skipTranscript: false,
            repeatIntervalMinutes: values.repeat
              ? values.repeatIntervalMinutes
              : null,
            repeatMaxRuns: values.repeat ? values.repeatMaxRuns : null,
          }),
        )}
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
                  <SelectItem value="auto">자동 (링크·검색어 판별)</SelectItem>
                  <SelectItem value="keyword">검색어</SelectItem>
                  <SelectItem value="channel">채널(유튜버)</SelectItem>
                  <SelectItem value="playlist">재생목록</SelectItem>
                  <SelectItem value="video">영상</SelectItem>
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
              max={300}
              aria-invalid={Boolean(form.formState.errors.maxVideos)}
              {...form.register("maxVideos", { valueAsNumber: true })}
            />
            <FieldDescription>1-300</FieldDescription>
            <FieldError errors={[form.formState.errors.maxVideos]} />
          </Field>

          <Field>
            <FieldLabel htmlFor="harvest-content-filter">콘텐츠 유형</FieldLabel>
            <Select
              value={contentFilter}
              onValueChange={(value) =>
                form.setValue("contentFilter", value as HarvestContentFilter, {
                  shouldDirty: true,
                  shouldValidate: true,
                })
              }
            >
              <SelectTrigger id="harvest-content-filter" className="w-full">
                <SelectValue>{contentFilterLabel(contentFilter)}</SelectValue>
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  {contentFilterOptions.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectGroup>
              </SelectContent>
            </Select>
            <FieldDescription>
              숏츠는 길이 {`≤`}60초 기준으로 구분합니다.
            </FieldDescription>
          </Field>

          <Field>
            <label
              htmlFor="harvest-force"
              className="flex items-center gap-2 text-sm font-medium"
            >
              <input
                id="harvest-force"
                type="checkbox"
                className="size-4 rounded border"
                checked={force}
                onChange={(event) =>
                  form.setValue("force", event.target.checked, {
                    shouldDirty: true,
                  })
                }
              />
              강제 다운로드(전체 재수집)
            </label>
            <FieldDescription>
              체크하면 이미 수집한 영상 이후만 받는 증분 수집 대신, 처음부터 다시 받습니다.
            </FieldDescription>
          </Field>

          <Field>
            <label
              htmlFor="harvest-repeat"
              className="flex items-center gap-2 text-sm font-medium"
            >
              <input
                id="harvest-repeat"
                type="checkbox"
                className="size-4 rounded border"
                checked={repeat}
                onChange={(event) =>
                  form.setValue("repeat", event.target.checked, {
                    shouldDirty: true,
                  })
                }
              />
              반복 검색
            </label>
            {repeat ? (
              <div className="mt-2 flex flex-col gap-1.5">
                <FieldLabel htmlFor="harvest-repeat-interval">반복 간격</FieldLabel>
                <Select
                  value={String(repeatIntervalMinutes)}
                  onValueChange={(value) =>
                    form.setValue("repeatIntervalMinutes", Number(value), {
                      shouldDirty: true,
                      shouldValidate: true,
                    })
                  }
                >
                  <SelectTrigger id="harvest-repeat-interval" className="w-full">
                    <SelectValue>
                      {repeatIntervalLabel(Number(repeatIntervalMinutes))}
                    </SelectValue>
                  </SelectTrigger>
                  <SelectContent>
                    <SelectGroup>
                      {repeatIntervalOptions.map((option) => (
                        <SelectItem key={option.value} value={String(option.value)}>
                          {option.label}
                        </SelectItem>
                      ))}
                    </SelectGroup>
                  </SelectContent>
                </Select>
                <FieldDescription>
                  체크 시 선택한 간격으로 자동 반복 수집합니다.
                </FieldDescription>
                <FieldLabel htmlFor="harvest-repeat-count" className="mt-2">
                  반복 횟수
                </FieldLabel>
                <Input
                  id="harvest-repeat-count"
                  type="number"
                  min={0}
                  value={String(repeatMaxRuns)}
                  onChange={(event) =>
                    form.setValue(
                      "repeatMaxRuns",
                      Math.max(0, Number(event.target.value) || 0),
                      { shouldDirty: true },
                    )
                  }
                />
                <FieldDescription>0이면 무한 반복.</FieldDescription>
              </div>
            ) : null}
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

      <section className="flex flex-col gap-3 border-t pt-5" aria-live="polite">
        <div className="flex items-center justify-between gap-3">
          <h2 className="text-sm font-medium">작업 상태</h2>
          <div className="flex items-center gap-2">
            {status ? (
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={() => setLogDialogStatus(status)}
              >
                <FileTextIcon data-icon="inline-start" />
                오류·로그 상세
              </Button>
            ) : null}
            {status ? (
              <Badge variant={statusTone.variant}>
                {statusTone.icon}
                {status.state}
              </Badge>
            ) : (
              <Badge variant="outline">대기</Badge>
            )}
          </div>
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
          <StatusRow label="error" value={status?.last_error ?? "-"} wrap />
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

      <JobLogDialog
        status={logDialogStatus}
        title="수집 작업 로그·오류"
        onClose={() => setLogDialogStatus(null)}
      />

      {transcriptReady || transcriptJobId ? (
        <section className="flex flex-col gap-3 border-t pt-5" aria-live="polite">
          <div className="flex items-center justify-between gap-3">
            <h2 className="text-sm font-medium">자막 생성</h2>
            {transcriptJobId && transcriptStatus ? (
              <Badge variant={transcriptTone.variant}>
                {transcriptTone.icon}
                {transcriptStatus.state}
              </Badge>
            ) : null}
          </div>

          {transcriptReady && !transcriptJobId ? (
            <div className="flex flex-col gap-3 rounded-md border bg-muted/30 p-3 text-sm">
              <p>
                영상 <span className="font-medium">{collectedVideoIds.length}</span>개
                수집을 완료했습니다. 자막 생성을 진행할까요?
              </p>
              <p className="text-xs text-muted-foreground">
                자막 생성은 시간이 걸릴 수 있으며, 진행하면 자막·장소 추출·지오코딩이 실행됩니다.
              </p>
              <Button
                type="button"
                onClick={() => transcriptMutation.mutate(jobId as string)}
                disabled={transcriptMutation.isPending}
              >
                {transcriptMutation.isPending ? (
                  <Loader2Icon data-icon="inline-start" className="animate-spin" />
                ) : (
                  <FileTextIcon data-icon="inline-start" />
                )}
                자막 생성 시작
              </Button>
            </div>
          ) : null}

          {transcriptJobId ? (
            <div className="flex flex-col gap-3">
              <div className="flex flex-col gap-2 text-sm">
                <StatusRow label="자막 job_id" value={transcriptJobId} />
                <StatusRow
                  label="progress"
                  value={
                    transcriptStatus
                      ? `${Math.round(transcriptStatus.progress * 100)}%`
                      : "-"
                  }
                />
              </div>
              <div className="h-2 overflow-hidden rounded-full bg-muted">
                <div
                  className="h-full rounded-full bg-primary transition-all"
                  style={{
                    width: `${Math.round((transcriptStatus?.progress ?? 0) * 100)}%`,
                  }}
                />
              </div>
              <StatusRow
                label="현재"
                value={
                  transcriptStatus?.current_message ?? "자막 작업을 준비 중입니다."
                }
                wrap
              />
              <div className="flex flex-col gap-2 rounded-md border bg-muted/30 p-3">
                <div className="flex items-center justify-between gap-3">
                  <p className="text-xs font-medium">자막 상세 로그</p>
                  <span className="text-xs text-muted-foreground">
                    {transcriptLogs.length}건
                  </span>
                </div>
                {transcriptLogs.length > 0 ? (
                  <ol className="flex max-h-56 flex-col gap-2 overflow-y-auto">
                    {transcriptLogs.map((log, index) => (
                      <li
                        key={`${log.timestamp}-${index}`}
                        className="grid grid-cols-[4.5rem_1fr_auto] gap-2 text-xs"
                      >
                        <span className="text-muted-foreground">
                          {formatLogTime(log.timestamp)}
                        </span>
                        <span
                          className={`${logToneClass(log.level)} min-w-0 break-words`}
                        >
                          {log.message}
                        </span>
                        <span className="text-muted-foreground">
                          {log.progress === null
                            ? ""
                            : `${Math.round(log.progress * 100)}%`}
                        </span>
                      </li>
                    ))}
                  </ol>
                ) : (
                  <p className="text-xs text-muted-foreground">
                    아직 자막 로그가 없습니다.
                  </p>
                )}
              </div>
            </div>
          ) : null}

          {transcriptMutation.error ? (
            <p className="text-sm text-destructive">
              {transcriptMutation.error.message}
            </p>
          ) : null}
          {transcriptStatusQuery.error ? (
            <p className="text-sm text-destructive">
              {transcriptStatusQuery.error.message}
            </p>
          ) : null}
        </section>
      ) : null}
    </div>
  );
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
    return "text-success";
  }
  if (level === "warning") {
    return "text-warn";
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
