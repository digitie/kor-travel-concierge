"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2Icon, SettingsIcon } from "lucide-react";

import {
  getRuntimeSettings,
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
];

export function SettingsDialog() {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const settingsQuery = useQuery({
    queryKey: ["runtime-settings"],
    queryFn: getRuntimeSettings,
    enabled: open,
  });
  const settings = settingsQuery.data;

  // 가져온 설정 위에 사용자 편집만 덮어쓰는 파생 상태(effect 없이).
  const [engineEdit, setEngineEdit] = useState<string | null>(null);
  const [prepromptEdit, setPrepromptEdit] = useState<string | null>(null);
  const [keyEdits, setKeyEdits] = useState<Record<string, string>>({});
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
      <DialogContent className="max-w-md">
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
