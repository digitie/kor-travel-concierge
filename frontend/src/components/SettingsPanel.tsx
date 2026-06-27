"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRoundIcon, Loader2Icon, SaveIcon } from "lucide-react";

import {
  createPublicApiKey,
  getRuntimeSettings,
  listPublicApiKeys,
  revokePublicApiKey,
  updateRuntimeSettings,
  type ApiKeyName,
  type RuntimeSettingsUpdate,
} from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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

const API_KEY_LABELS: { name: ApiKeyName; label: string }[] = [
  { name: "youtube_api_key", label: "YouTube Data API" },
  { name: "gemini_api_key", label: "Gemini API" },
  { name: "deepseek_api_key", label: "DeepSeek API" },
  { name: "google_places_api_key", label: "Google Places API" },
  { name: "kakao_rest_api_key", label: "Kakao REST API" },
  { name: "naver_search_client_id", label: "Naver 검색 Client ID" },
  { name: "naver_search_client_secret", label: "Naver 검색 Client Secret" },
  { name: "vworld_service_key", label: "VWorld 서비스 키" },
  { name: "kor_travel_geo_v2_api_key", label: "kor travel geo v2 API" },
];

export function SettingsPanel() {
  const queryClient = useQueryClient();
  const settingsQuery = useQuery({
    queryKey: ["runtime-settings"],
    queryFn: getRuntimeSettings,
  });
  const publicKeysQuery = useQuery({
    queryKey: ["public-api-keys"],
    queryFn: listPublicApiKeys,
  });
  const settings = settingsQuery.data;

  const [engineEdit, setEngineEdit] = useState<string | null>(null);
  const [prepromptEdit, setPrepromptEdit] = useState<string | null>(null);
  const [keyEdits, setKeyEdits] = useState<Record<string, string>>({});
  const [publicKeyLabel, setPublicKeyLabel] = useState("");
  const [createdPublicKey, setCreatedPublicKey] = useState<string | null>(null);
  const engine = engineEdit ?? settings?.gemini_engine_version ?? "";
  const preprompt = prepromptEdit ?? settings?.ai_preprompt ?? "";

  function resetEdits() {
    setEngineEdit(null);
    setPrepromptEdit(null);
    setKeyEdits({});
  }

  const mutation = useMutation({
    mutationFn: () => {
      const payload: RuntimeSettingsUpdate = {
        gemini_engine_version: engine,
        ai_preprompt: preprompt,
      };
      for (const [name, value] of Object.entries(keyEdits)) {
        if (value.trim()) {
          payload[name as ApiKeyName] = value.trim();
        }
      }
      return updateRuntimeSettings(payload);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["runtime-settings"] });
      resetEdits();
    },
  });
  const createKeyMutation = useMutation({
    mutationFn: () => createPublicApiKey(publicKeyLabel),
    onSuccess: (result) => {
      setCreatedPublicKey(result.key);
      setPublicKeyLabel("");
      queryClient.invalidateQueries({ queryKey: ["public-api-keys"] });
    },
  });
  const revokeKeyMutation = useMutation({
    mutationFn: (id: number) => revokePublicApiKey(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["public-api-keys"] });
    },
  });

  if (settingsQuery.isLoading) {
    return (
      <p className="rounded-lg border border-surface-muted bg-card p-4 text-sm text-text-secondary">
        설정을 불러오는 중입니다.
      </p>
    );
  }

  if (!settings) {
    return (
      <p role="alert" className="rounded-lg border border-destructive/30 bg-card p-4 text-sm text-destructive">
        {settingsQuery.error?.message ?? "설정을 불러오지 못했습니다."}
      </p>
    );
  }

  return (
    <div className="grid gap-4 xl:grid-cols-[1.1fr_0.9fr]">
      <section className="flex flex-col gap-4 rounded-lg border border-surface-muted bg-card p-4 shadow-[var(--shadow-card)]">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h2 className="text-[16px] font-bold">AI 엔진</h2>
            <p className="text-[13px] text-text-secondary">
              모델과 사전 프롬프트는 저장 즉시 다음 작업부터 적용됩니다.
            </p>
          </div>
          <Button
            id="settings-save-button"
            type="button"
            disabled={mutation.isPending}
            onClick={() => mutation.mutate()}
          >
            {mutation.isPending ? (
              <Loader2Icon data-icon="inline-start" className="animate-spin" />
            ) : (
              <SaveIcon data-icon="inline-start" />
            )}
            저장
          </Button>
        </div>

        <Field>
          <FieldLabel htmlFor="ai-engine-select">AI 엔진</FieldLabel>
          <Select value={engine} onValueChange={(value) => setEngineEdit(value ?? "")}>
            <SelectTrigger id="ai-engine-select" className="w-full">
              <SelectValue>{engine || "선택"}</SelectValue>
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                {settings.gemini_engine_options.map((option) => (
                  <SelectItem key={option} value={option}>
                    {option}
                  </SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>
          <FieldDescription>기본값: {settings.gemini_engine_default}</FieldDescription>
        </Field>

        <Field>
          <FieldLabel htmlFor="settings-preprompt">AI 사전 프롬프트</FieldLabel>
          <textarea
            id="settings-preprompt"
            className="min-h-44 w-full rounded-lg border border-input bg-card p-3 text-[14px] outline-none focus-visible:border-brand focus-visible:ring-3 focus-visible:ring-brand/20"
            value={preprompt}
            onChange={(event) => setPrepromptEdit(event.target.value)}
          />
          <FieldDescription>모든 AI 호출 프롬프트 앞에 붙습니다.</FieldDescription>
        </Field>

        {mutation.error ? (
          <p className="text-[13px] text-destructive">{mutation.error.message}</p>
        ) : null}
        {mutation.isSuccess ? (
          <p id="success-toast" className="text-[13px] text-success">
            저장했습니다.
          </p>
        ) : null}
      </section>

      <section className="flex flex-col gap-4 rounded-lg border border-surface-muted bg-card p-4 shadow-[var(--shadow-card)]">
        <div>
          <h2 className="text-[16px] font-bold">API 키</h2>
          <p className="text-[13px] text-text-secondary">
            값은 저장 후 화면에 표시되지 않습니다. 비워 두면 기존 값을 유지합니다.
          </p>
        </div>
        <div className="grid gap-3">
          {API_KEY_LABELS.map(({ name, label }) => {
            const isSet = settings.api_keys?.[name]?.set ?? false;
            return (
              <Field key={name}>
                <div className="flex items-center justify-between gap-2">
                  <FieldLabel htmlFor={`settings-${name}`}>{label}</FieldLabel>
                  <Badge variant={isSet ? "secondary" : "outline"}>
                    {isSet ? "설정됨" : "미설정"}
                  </Badge>
                </div>
                <Input
                  id={`settings-${name}`}
                  type="password"
                  autoComplete="off"
                  placeholder={isSet ? "변경하려면 새 값 입력" : "미설정"}
                  value={keyEdits[name] ?? ""}
                  onChange={(event) =>
                    setKeyEdits((prev) => ({
                      ...prev,
                      [name]: event.target.value,
                    }))
                  }
                />
              </Field>
            );
          })}
        </div>
      </section>

      <section className="flex flex-col gap-4 rounded-lg border border-surface-muted bg-card p-4 shadow-[var(--shadow-card)]">
        <div>
          <h2 className="text-[16px] font-bold">외부 공개 API 키</h2>
          <p className="text-[13px] text-text-secondary">
            VWorld와 같은 `key` 파라미터 형태로 사용합니다. 원문 키는 생성 직후에만 표시됩니다.
          </p>
        </div>
        <div className="flex gap-2">
          <Input
            aria-label="공개 API 키 라벨"
            placeholder="라벨"
            value={publicKeyLabel}
            onChange={(event) => setPublicKeyLabel(event.target.value)}
          />
          <Button
            type="button"
            variant="secondary"
            onClick={() => createKeyMutation.mutate()}
            disabled={createKeyMutation.isPending}
          >
            {createKeyMutation.isPending ? (
              <Loader2Icon data-icon="inline-start" className="animate-spin" />
            ) : (
              <KeyRoundIcon data-icon="inline-start" />
            )}
            생성
          </Button>
        </div>
        {createdPublicKey ? (
          <div className="flex gap-2">
            <Input
              readOnly
              aria-label="생성된 공개 API 키"
              value={createdPublicKey}
              onFocus={(event) => event.currentTarget.select()}
            />
            <Button
              type="button"
              variant="outline"
              onClick={() => setCreatedPublicKey(null)}
            >
              지우기
            </Button>
          </div>
        ) : null}
        <div className="max-h-72 overflow-y-auto rounded-lg border border-surface-muted">
          {(publicKeysQuery.data ?? []).length > 0 ? (
            (publicKeysQuery.data ?? []).map((item) => (
              <div
                key={item.id}
                className="flex items-center justify-between gap-2 border-b border-surface-muted px-3 py-2 last:border-b-0"
              >
                <div className="min-w-0">
                  <p className="truncate text-[14px] font-medium">
                    {item.label || "무제"}
                  </p>
                  <p className="text-[12px] text-text-secondary">
                    끝자리 {item.key_hint} · {item.state === "active" ? "활성" : "폐기"}
                  </p>
                </div>
                {item.state === "active" ? (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => revokeKeyMutation.mutate(item.id)}
                    disabled={revokeKeyMutation.isPending}
                  >
                    폐기
                  </Button>
                ) : null}
              </div>
            ))
          ) : (
            <p className="px-3 py-2 text-[13px] text-text-secondary">
              생성된 공개 API 키가 없습니다.
            </p>
          )}
        </div>
      </section>
    </div>
  );
}
