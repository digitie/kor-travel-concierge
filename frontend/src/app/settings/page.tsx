"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Loader2Icon, RotateCcwIcon, SaveIcon } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useForm, useWatch } from "react-hook-form";
import { z } from "zod";

import {
  getRuntimeSettings,
  updateRuntimeSettings,
  type RuntimeSettingsUpdate,
} from "@/lib/api";
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

const settingsSchema = z.object({
  engineVersion: z.string().min(1, "AI 엔진을 선택하세요."),
  // 빈 값이면 기존 키를 유지(변경 안 함).
  deepseekApiKey: z.string().max(200).optional(),
  aiPreprompt: z.string().max(4000, "사전 프롬프트는 4000자 이하여야 합니다."),
});

type SettingsFormValues = z.infer<typeof settingsSchema>;

function isDeepseekEngine(engine: string): boolean {
  return engine.trim().toLowerCase().startsWith("deepseek");
}

export default function SettingsPage() {
  const [saved, setSaved] = useState(false);
  const form = useForm<SettingsFormValues>({
    resolver: zodResolver(settingsSchema),
    defaultValues: { engineVersion: "", deepseekApiKey: "", aiPreprompt: "" },
  });
  const selectedEngine = useWatch({ control: form.control, name: "engineVersion" });
  const deepseekKeyInput = useWatch({ control: form.control, name: "deepseekApiKey" });

  const settingsQuery = useQuery({
    queryKey: ["runtime-settings"],
    queryFn: getRuntimeSettings,
  });

  useEffect(() => {
    const data = settingsQuery.data;
    if (!data) {
      return;
    }
    const engine = data.gemini_engine_version ?? data.gemini_engine_default;
    if (engine) {
      form.setValue("engineVersion", engine);
    }
    form.setValue("aiPreprompt", data.ai_preprompt ?? "");
  }, [
    form,
    settingsQuery.data,
  ]);

  const engineOptions = useMemo(() => {
    const options = settingsQuery.data?.gemini_engine_options ?? [];
    if (selectedEngine && !options.includes(selectedEngine)) {
      return [selectedEngine, ...options];
    }
    return options;
  }, [selectedEngine, settingsQuery.data?.gemini_engine_options]);

  const deepseekKeySet = settingsQuery.data?.deepseek_api_key_set ?? false;
  const showDeepseekKeyWarning =
    isDeepseekEngine(selectedEngine) &&
    !deepseekKeySet &&
    !(deepseekKeyInput ?? "").trim();

  const mutation = useMutation({
    mutationFn: (values: SettingsFormValues) =>
      updateRuntimeSettings(toRuntimeSettings(values)),
    onSuccess: () => {
      setSaved(true);
      form.setValue("deepseekApiKey", "");
      void settingsQuery.refetch();
    },
  });

  return (
    <main className="mx-auto flex max-w-lg flex-col gap-5 p-6">
      <header className="flex flex-col gap-1">
        <h1 className="text-lg font-semibold text-text-strong">설정</h1>
        <p className="text-sm text-text-secondary">
          AI 엔진과 사전 프롬프트를 설정합니다. 저장한 값은 즉시 적용됩니다.
        </p>
      </header>

      <form
        className="flex flex-col gap-5"
        onSubmit={form.handleSubmit((values) => {
          setSaved(false);
          mutation.mutate(values);
        })}
      >
        <FieldGroup>
          <Field data-invalid={Boolean(form.formState.errors.engineVersion)}>
            <FieldLabel>AI 엔진</FieldLabel>
            <Select
              disabled={settingsQuery.isLoading || engineOptions.length === 0}
              value={selectedEngine}
              onValueChange={(value) => {
                if (value === null) {
                  return;
                }
                form.setValue("engineVersion", value, {
                  shouldDirty: true,
                  shouldValidate: true,
                });
              }}
            >
              <SelectTrigger
                id="ai-engine-select"
                className="w-full"
                aria-invalid={Boolean(form.formState.errors.engineVersion)}
              >
                <SelectValue>{selectedEngine}</SelectValue>
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  {engineOptions.map((engine) => (
                    <SelectItem key={engine} value={engine}>
                      {engine}
                    </SelectItem>
                  ))}
                </SelectGroup>
              </SelectContent>
            </Select>
            <FieldDescription>
              Gemini 또는 DeepSeek(deepseek-v4-flash / deepseek-v4-pro) 모델을 선택합니다.
            </FieldDescription>
            <FieldError errors={[form.formState.errors.engineVersion]} />
          </Field>

          <Field data-invalid={Boolean(form.formState.errors.deepseekApiKey)}>
            <FieldLabel>DeepSeek API 키</FieldLabel>
            <Input
              id="deepseek-api-key"
              type="password"
              autoComplete="off"
              placeholder={deepseekKeySet ? "설정됨 — 새 키 입력 시에만 변경" : "미설정"}
              {...form.register("deepseekApiKey")}
            />
            <FieldDescription>
              {showDeepseekKeyWarning
                ? "DeepSeek 엔진을 쓰려면 키가 필요합니다. 키를 입력해 저장하세요."
                : "비워 두면 기존 키를 유지합니다. 저장한 키가 .env 기본 키보다 우선합니다."}
            </FieldDescription>
            <FieldError errors={[form.formState.errors.deepseekApiKey]} />
          </Field>

          <Field data-invalid={Boolean(form.formState.errors.aiPreprompt)}>
            <FieldLabel>사전 프롬프트</FieldLabel>
            <textarea
              id="ai-preprompt"
              className="min-h-[140px] w-full rounded-lg border border-input bg-transparent px-3 py-2 text-sm transition-colors outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:opacity-50"
              placeholder="AI에게 명령을 주기 전에 항상 앞에 붙일 지침을 입력하세요."
              {...form.register("aiPreprompt")}
            />
            <FieldDescription>
              모든 AI 명령(POI 추출·요약·키워드 정제 등) 앞에 붙습니다. JSON 출력 안정성을 위해
              기본 예제를 권장합니다.
            </FieldDescription>
            <FieldError errors={[form.formState.errors.aiPreprompt]} />
            <div>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => {
                  const example = settingsQuery.data?.ai_preprompt_default ?? "";
                  form.setValue("aiPreprompt", example, {
                    shouldDirty: true,
                    shouldValidate: true,
                  });
                }}
              >
                <RotateCcwIcon data-icon="inline-start" />
                기본 예제로 채우기
              </Button>
            </div>
          </Field>
        </FieldGroup>

        <Button id="settings-save-button" type="submit" disabled={mutation.isPending}>
          {mutation.isPending ? (
            <Loader2Icon data-icon="inline-start" className="animate-spin" />
          ) : (
            <SaveIcon data-icon="inline-start" />
          )}
          저장
        </Button>
      </form>

      {mutation.error ? (
        <p role="alert" className="text-sm text-destructive">
          {mutation.error.message}
        </p>
      ) : null}
      {settingsQuery.error ? (
        <p role="alert" className="text-sm text-destructive">
          {settingsQuery.error.message}
        </p>
      ) : null}
      {saved ? (
        <div id="success-toast" role="status" className="text-sm text-success">
          설정이 저장되었습니다.
        </div>
      ) : null}
    </main>
  );
}

function toRuntimeSettings(values: SettingsFormValues): RuntimeSettingsUpdate {
  const update: RuntimeSettingsUpdate = {
    gemini_engine_version: values.engineVersion,
    ai_preprompt: values.aiPreprompt,
  };
  const key = (values.deepseekApiKey ?? "").trim();
  if (key) {
    update.deepseek_api_key = key;
  }
  return update;
}
