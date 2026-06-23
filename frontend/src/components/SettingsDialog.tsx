"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRoundIcon, Loader2Icon, SettingsIcon } from "lucide-react";

import {
  createPublicApiKey,
  getRuntimeSettings,
  listLoginEvents,
  listPublicApiKeys,
  revokePublicApiKey,
  updateRuntimeSettings,
  type ApiKeyName,
  type RuntimeSettingsUpdate,
} from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
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

export function SettingsDialog() {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const settingsQuery = useQuery({
    queryKey: ["runtime-settings"],
    queryFn: getRuntimeSettings,
    enabled: open,
  });
  const publicKeysQuery = useQuery({
    queryKey: ["public-api-keys"],
    queryFn: listPublicApiKeys,
    enabled: open,
  });
  const loginEventsQuery = useQuery({
    queryKey: ["login-events"],
    queryFn: listLoginEvents,
    enabled: open,
  });
  const settings = settingsQuery.data;

  // 가져온 설정 위에 사용자 편집만 덮어쓰는 파생 상태(effect 없이).
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
    setPublicKeyLabel("");
    setCreatedPublicKey(null);
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

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (next) {
          resetEdits();
        }
      }}
    >
      <DialogTrigger
        render={
          <Button type="button" variant="outline" size="sm">
            <SettingsIcon data-icon="inline-start" />
            설정
          </Button>
        }
      />
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>설정</DialogTitle>
          <DialogDescription>
            AI 엔진·사전 프롬프트·각종 API 키를 저장/수정합니다.
          </DialogDescription>
        </DialogHeader>

        {settings ? (
          <div className="flex flex-col gap-4">
            <Field>
              <FieldLabel htmlFor="settings-engine">AI 엔진</FieldLabel>
              <Select
                value={engine}
                onValueChange={(value) => setEngineEdit(value ?? "")}
              >
                <SelectTrigger id="settings-engine" className="w-full">
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
                className="min-h-24 w-full rounded-lg border border-input bg-transparent p-2.5 text-sm outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50"
                value={preprompt}
                onChange={(event) => setPrepromptEdit(event.target.value)}
              />
              <FieldDescription>모든 AI 호출 프롬프트 앞에 붙습니다.</FieldDescription>
            </Field>

            <div className="flex flex-col gap-3 border-t pt-4">
              <div className="flex flex-col gap-0.5">
                <p className="text-sm font-medium">API 키</p>
                <p className="text-xs text-muted-foreground">
                  값은 저장 후 화면에 표시되지 않습니다. 비워 두면 기존 값을 유지합니다.
                </p>
              </div>
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

            <div className="flex flex-col gap-3 border-t pt-4">
              <div className="flex flex-col gap-0.5">
                <p className="text-sm font-medium">외부 공개 API 키</p>
                <p className="text-xs text-muted-foreground">
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
              <div className="max-h-40 overflow-y-auto rounded-lg border">
                {(publicKeysQuery.data ?? []).length > 0 ? (
                  (publicKeysQuery.data ?? []).map((item) => (
                    <div
                      key={item.id}
                      className="flex items-center justify-between gap-2 border-b px-3 py-2 last:border-b-0"
                    >
                      <div className="min-w-0">
                        <p className="truncate text-sm font-medium">
                          {item.label || "무제"}
                        </p>
                        <p className="text-xs text-muted-foreground">
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
                  <p className="px-3 py-2 text-sm text-muted-foreground">
                    생성된 공개 API 키가 없습니다.
                  </p>
                )}
              </div>
              {createKeyMutation.error || revokeKeyMutation.error ? (
                <p className="text-xs text-destructive">
                  {(createKeyMutation.error ?? revokeKeyMutation.error)?.message}
                </p>
              ) : null}
            </div>

            <div className="flex flex-col gap-3 border-t pt-4">
              <p className="text-sm font-medium">로그인 기록</p>
              <div className="max-h-44 overflow-y-auto rounded-lg border">
                {(loginEventsQuery.data ?? []).length > 0 ? (
                  (loginEventsQuery.data ?? []).map((event) => (
                    <div key={event.id} className="border-b px-3 py-2 last:border-b-0">
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-sm font-medium">
                          {event.event_type === "logout" ? "로그아웃" : "로그인"}
                        </span>
                        <Badge
                          variant={
                            event.outcome === "succeeded" ? "secondary" : "outline"
                          }
                        >
                          {event.outcome}
                        </Badge>
                      </div>
                      <p className="mt-1 text-xs text-muted-foreground">
                        {new Date(event.created_at).toLocaleString()} ·{" "}
                        {event.attempted_username || "-"} · {event.reason || "-"}
                      </p>
                      <p className="truncate text-xs text-muted-foreground">
                        {event.client_ip || "unknown ip"}
                      </p>
                    </div>
                  ))
                ) : (
                  <p className="px-3 py-2 text-sm text-muted-foreground">
                    저장된 로그인 기록이 없습니다.
                  </p>
                )}
              </div>
            </div>

            {mutation.error ? (
              <p className="text-xs text-destructive">{mutation.error.message}</p>
            ) : null}
            {mutation.isSuccess ? (
              <p className="text-xs text-success">저장했습니다.</p>
            ) : null}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">
            {settingsQuery.error
              ? settingsQuery.error.message
              : "설정을 불러오는 중…"}
          </p>
        )}

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
            disabled={mutation.isPending || !settings}
          >
            {mutation.isPending ? (
              <Loader2Icon data-icon="inline-start" className="animate-spin" />
            ) : null}
            저장
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
