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
  startHarvest,
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

  const status = statusQuery.data;
  const statusTone = useMemo(() => statusBadgeVariant(status?.state), [status?.state]);

  return (
    <div className="flex h-full flex-col gap-6 bg-background p-5">
      <header className="flex flex-col gap-1">
        <h1 className="text-xl font-semibold tracking-normal">TripMate Agent</h1>
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
          <StatusRow label="error" value={status?.last_error ?? "-"} />
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

function StatusRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="text-muted-foreground">{label}</span>
      <span className="max-w-[12rem] truncate text-right font-medium">{value}</span>
    </div>
  );
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
