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
  type PublicApiKeySummary,
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
import { Textarea } from "@/components/ui/textarea";
import { ConfirmActionButton } from "@/components/ConfirmActionButton";
import { CopyButton } from "@/components/CopyButton";
import { HelpTip } from "@/components/HelpTip";

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

// backend `settings_service.AI_PREPROMPT_MAX_LEN`과 동일 상한.
const PREPROMPT_MAX_LEN = 4000;

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
  const [publicKeyScope, setPublicKeyScope] =
    useState<PublicApiKeySummary["scope"]>("read");
  const [createdPublicKey, setCreatedPublicKey] = useState<string | null>(null);
  const engine = engineEdit ?? settings?.gemini_engine_version ?? "";
  const preprompt = prepromptEdit ?? settings?.ai_preprompt ?? "";
  const prepromptTooLong = preprompt.length > PREPROMPT_MAX_LEN;

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
    mutationFn: () => createPublicApiKey(publicKeyLabel, publicKeyScope),
    onSuccess: (result) => {
      setCreatedPublicKey(result.key);
      setPublicKeyLabel("");
      setPublicKeyScope("read");
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
              저장 즉시 다음 작업부터 적용됩니다.
            </p>
          </div>
          <Button
            id="settings-save-button"
            type="button"
            disabled={mutation.isPending || prepromptTooLong}
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

        <Field data-invalid={prepromptTooLong}>
          <div className="flex items-center gap-1">
            <FieldLabel htmlFor="settings-preprompt">AI 사전 프롬프트</FieldLabel>
            <HelpTip>
              모든 AI 호출 프롬프트 앞에 붙는 지시문입니다. 말투·판단 기준·출력
              형식 같은 공통 규칙을 적어 두면 검색어 보정, POI 추출, 카테고리
              제안에 함께 적용됩니다.
            </HelpTip>
          </div>
          <Textarea
            id="settings-preprompt"
            className="min-h-44"
            aria-invalid={prepromptTooLong}
            value={preprompt}
            onChange={(event) => setPrepromptEdit(event.target.value)}
          />
          <p
            className={
              prepromptTooLong
                ? "text-right text-[12px] text-destructive"
                : "text-right text-[12px] text-text-tertiary"
            }
          >
            {preprompt.length.toLocaleString()} / {PREPROMPT_MAX_LEN.toLocaleString()}자
          </p>
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
          <div className="flex items-center gap-1">
            <h2 className="text-[16px] font-bold">외부 공개 API 키</h2>
            <HelpTip>
              외부 소비자의 read 키와 운영 자동화의 admin 키를 발급합니다. 기본 read
              키는 X-API-Key header로 전달하고, 호환용 key query도 DB read 키에만
              허용됩니다. admin 키는 반드시 header로만 전달합니다.
            </HelpTip>
          </div>
          <p className="text-[13px] text-text-secondary">
            원문 키는 생성 직후에만 표시됩니다.
          </p>
        </div>
        <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_10rem_auto]">
          <Input
            aria-label="공개 API 키 라벨"
            placeholder="라벨"
            value={publicKeyLabel}
            onChange={(event) => setPublicKeyLabel(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !createKeyMutation.isPending) {
                createKeyMutation.mutate();
              }
            }}
          />
          <Select
            value={publicKeyScope}
            onValueChange={(value) =>
              setPublicKeyScope((value as PublicApiKeySummary["scope"]) ?? "read")
            }
          >
            <SelectTrigger aria-label="공개 API 키 권한" className="w-full">
              <SelectValue>
                {publicKeyScope === "read" ? "읽기 전용" : "관리자"}
              </SelectValue>
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                <SelectItem value="read">읽기 전용</SelectItem>
                <SelectItem value="admin">관리자</SelectItem>
              </SelectGroup>
            </SelectContent>
          </Select>
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
        <div className="flex items-start gap-1 text-[12px] text-text-secondary">
          <span>
            {publicKeyScope === "read"
              ? "외부 소비자에는 공급 API만 허용하는 읽기 전용 키를 사용하세요."
              : "관리자 키는 X-API-Key header로 전달하면 내부 API와 쓰기 작업까지 허용합니다."}
          </span>
          <HelpTip>
            관리자 키가 유출되면 수집·설정·삭제를 포함한 모든 비관리자-proxy API가 노출됩니다.
            운영자 자동화처럼 꼭 필요한 경우에만 발급하고, 외부 데이터 소비자에는 읽기 전용 키만
            전달하세요. 관리자 키는 key 쿼리 파라미터로 전달할 수 없습니다.
          </HelpTip>
        </div>
        {createdPublicKey ? (
          <div className="flex items-center gap-2">
            <Input
              readOnly
              aria-label="생성된 공개 API 키"
              value={createdPublicKey}
              onFocus={(event) => event.currentTarget.select()}
            />
            <CopyButton text={createdPublicKey} />
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
                    끝자리 {item.key_hint} · {item.scope === "read" ? "읽기 전용" : "관리자"} ·{" "}
                    {item.state === "active" ? "활성" : "폐기"}
                  </p>
                </div>
                {item.state === "active" ? (
                  <ConfirmActionButton
                    title={`${item.label || "무제"} 키를 폐기할까요?`}
                    description="이 키를 쓰는 외부 호출이 즉시 거부됩니다. 되돌릴 수 없습니다."
                    confirmLabel="폐기"
                    onConfirm={() => revokeKeyMutation.mutate(item.id)}
                    trigger={
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        disabled={revokeKeyMutation.isPending}
                      >
                        폐기
                      </Button>
                    }
                  />
                ) : null}
              </div>
            ))
          ) : (
            <p className="px-3 py-2 text-[13px] text-text-secondary">
              생성된 공개 API 키가 없습니다.
            </p>
          )}
        </div>
        {createKeyMutation.error || revokeKeyMutation.error ? (
          <p className="text-xs text-destructive">
            {(createKeyMutation.error ?? revokeKeyMutation.error)?.message}
          </p>
        ) : null}
      </section>
    </div>
  );
}
