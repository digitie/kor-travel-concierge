"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Loader2Icon, SaveIcon } from "lucide-react";
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
  FieldError,
  FieldGroup,
  FieldLabel,
} from "@/components/ui/field";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

const settingsSchema = z.object({
  geminiEngineVersion: z.string().min(1, "Gemini 엔진 버전을 선택하세요."),
});

type SettingsFormValues = z.infer<typeof settingsSchema>;

export default function SettingsPage() {
  const [saved, setSaved] = useState(false);
  const form = useForm<SettingsFormValues>({
    resolver: zodResolver(settingsSchema),
    defaultValues: { geminiEngineVersion: "" },
  });
  const selectedEngine = useWatch({
    control: form.control,
    name: "geminiEngineVersion",
  });

  const settingsQuery = useQuery({
    queryKey: ["runtime-settings"],
    queryFn: getRuntimeSettings,
  });

  useEffect(() => {
    const engine =
      settingsQuery.data?.gemini_engine_version ??
      settingsQuery.data?.gemini_engine_default;
    if (engine) {
      form.setValue("geminiEngineVersion", engine);
    }
  }, [
    form,
    settingsQuery.data?.gemini_engine_default,
    settingsQuery.data?.gemini_engine_version,
  ]);

  const engineOptions = useMemo(() => {
    const options = settingsQuery.data?.gemini_engine_options ?? [];
    if (selectedEngine && !options.includes(selectedEngine)) {
      return [selectedEngine, ...options];
    }
    return options;
  }, [selectedEngine, settingsQuery.data?.gemini_engine_options]);

  const mutation = useMutation({
    mutationFn: (values: SettingsFormValues) =>
      updateRuntimeSettings(toRuntimeSettings(values)),
    onSuccess: () => {
      setSaved(true);
    },
  });

  return (
    <main className="mx-auto flex max-w-md flex-col gap-5 p-6">
      <header className="flex flex-col gap-1">
        <h1 className="text-lg font-semibold">설정</h1>
      </header>

      <form
        className="flex flex-col gap-4"
        onSubmit={form.handleSubmit((values) => mutation.mutate(values))}
      >
        <FieldGroup>
          <Field data-invalid={Boolean(form.formState.errors.geminiEngineVersion)}>
            <FieldLabel>Gemini 엔진 버전</FieldLabel>
            <Select
              disabled={settingsQuery.isLoading || engineOptions.length === 0}
              value={selectedEngine}
              onValueChange={(value) => {
                if (value === null) {
                  return;
                }
                form.setValue(
                  "geminiEngineVersion",
                  value,
                  { shouldDirty: true, shouldValidate: true },
                );
              }}
            >
              <SelectTrigger
                id="gemini-engine-select"
                className="w-full"
                aria-invalid={Boolean(form.formState.errors.geminiEngineVersion)}
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
            <FieldError errors={[form.formState.errors.geminiEngineVersion]} />
          </Field>
        </FieldGroup>

        <Button
          id="settings-save-button"
          type="submit"
          disabled={mutation.isPending || !selectedEngine}
        >
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
        <div id="success-toast" role="status" className="text-sm text-green-600">
          설정이 저장되었습니다.
        </div>
      ) : null}
    </main>
  );
}

function toRuntimeSettings(values: SettingsFormValues): RuntimeSettingsUpdate {
  return { gemini_engine_version: values.geminiEngineVersion };
}
