"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  Loader2Icon,
  PlayIcon,
} from "lucide-react";
import { useForm, useWatch } from "react-hook-form";
import { z } from "zod";

import {
  listCategories,
  startHarvest,
  type CategoryOption,
  type HarvestContentFilter,
  type HarvestTargetType,
} from "@/lib/api";
import { categoryDisplayLabel } from "@/lib/display-labels";
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

function categoryLabel(
  categories: CategoryOption[] | undefined,
  code: string,
): string {
  return categoryDisplayLabel(
    categories?.find((category) => category.code === code)?.label ?? code,
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
  defaultCategoryCode: z.string().min(1),
});

type HarvestFormValues = z.infer<typeof harvestFormSchema>;

export function HarvestConsole() {
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
      defaultCategoryCode: "0",
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
  const defaultCategoryCode = useWatch({
    control: form.control,
    name: "defaultCategoryCode",
  });
  const effectiveDefaultCategoryCode = defaultCategoryCode ?? "0";

  const categoriesQuery = useQuery({
    queryKey: ["categories"],
    queryFn: listCategories,
    staleTime: 60 * 60 * 1000,
  });

  const mutation = useMutation({
    mutationFn: startHarvest,
    onSuccess: () => form.reset(form.getValues()),
  });

  return (
    <div className="flex h-full flex-col gap-6 bg-background p-5">
      <header className="flex flex-col gap-1">
        <h1 className="text-base font-semibold tracking-normal">수집 작업</h1>
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

          <div className="grid gap-3 md:grid-cols-2">
            <Field data-invalid={Boolean(form.formState.errors.maxVideos)}>
              <FieldLabel htmlFor="harvest-max-videos">
                최대 영상 수 (최대 300개)
              </FieldLabel>
              <Input
                id="harvest-max-videos"
                type="number"
                min={1}
                max={300}
                aria-invalid={Boolean(form.formState.errors.maxVideos)}
                {...form.register("maxVideos", { valueAsNumber: true })}
              />
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
            </Field>
          </div>

          <Field>
            <FieldLabel htmlFor="harvest-default-category">기본 카테고리</FieldLabel>
            <Select
              value={effectiveDefaultCategoryCode}
              onValueChange={(value) =>
                form.setValue("defaultCategoryCode", value ?? "0", {
                  shouldDirty: true,
                  shouldValidate: true,
                })
              }
            >
              <SelectTrigger id="harvest-default-category" className="w-full">
                <SelectValue>
                  {categoryLabel(categoriesQuery.data, effectiveDefaultCategoryCode)}
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

      {mutation.error ? (
        <p className="text-sm text-destructive" role="alert">
          {mutation.error.message}
        </p>
      ) : null}
    </div>
  );
}
