"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Loader2Icon, SaveIcon } from "lucide-react";
import { useEffect, useState } from "react";
import { useForm, useWatch } from "react-hook-form";
import { z } from "zod";

import {
  getRuntimeSettings,
  updateRuntimeSettings,
  type RuntimeSettings,
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
  geminiEngineVersion: z.enum([
    "gemini-flash-latest",
    "gemini-2.0-flash",
    "gemini-1.5-flash",
    "gemini-1.5-pro",
  ]),
});

type SettingsFormValues = z.infer<typeof settingsSchema>;

export default function SettingsPage() {
  const [saved, setSaved] = useState(false);
  const form = useForm<SettingsFormValues>({
    resolver: zodResolver(settingsSchema),
    defaultValues: { geminiEngineVersion: "gemini-2.0-flash" },
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
    const engine = settingsQuery.data?.gemini_engine_version;
    if (engine && settingsSchema.shape.geminiEngineVersion.safeParse(engine).success) {
      form.setValue("geminiEngineVersion", engine as SettingsFormValues["geminiEngineVersion"]);
    }
  }, [form, settingsQuery.data?.gemini_engine_version]);

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
              value={selectedEngine}
              onValueChange={(value) =>
                form.setValue(
                  "geminiEngineVersion",
                  value as SettingsFormValues["geminiEngineVersion"],
                  { shouldDirty: true, shouldValidate: true },
                )
              }
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
                  <SelectItem value="gemini-flash-latest">gemini-flash-latest</SelectItem>
                  <SelectItem value="gemini-2.0-flash">gemini-2.0-flash</SelectItem>
                  <SelectItem value="gemini-1.5-flash">gemini-1.5-flash</SelectItem>
                  <SelectItem value="gemini-1.5-pro">gemini-1.5-pro</SelectItem>
                </SelectGroup>
              </SelectContent>
            </Select>
            <FieldError errors={[form.formState.errors.geminiEngineVersion]} />
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
        <div id="success-toast" role="status" className="text-sm text-green-600">
          설정이 저장되었습니다.
        </div>
      ) : null}
    </main>
  );
}

function toRuntimeSettings(values: SettingsFormValues): RuntimeSettings {
  return { gemini_engine_version: values.geminiEngineVersion };
}
