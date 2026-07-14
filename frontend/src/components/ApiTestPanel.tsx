"use client";

import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Loader2Icon, PlayIcon } from "lucide-react";

import {
  listThemes,
  probeApi,
  type ApiProbeResult,
  type ThemeList,
} from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Field, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { CopyButton } from "@/components/CopyButton";
import { HelpTip } from "@/components/HelpTip";
import { EmptyState, Panel } from "@/components/panels";

type ParamKind =
  | "kind"
  | "value"
  | "video_id"
  | "cursor"
  | "limit"
  | "include";

type EndpointDef = {
  id: string;
  label: string;
  method: "GET";
  params: ParamKind[];
  description: string;
  buildPath: (p: Record<string, string>) => string;
};

const ENDPOINTS: EndpointDef[] = [
  {
    id: "themes",
    label: "GET /themes — 테마 목록",
    method: "GET",
    params: [],
    description: "공급 가능한 테마(유튜버/재생목록/보정 검색어)와 각 확정 POI 수.",
    buildPath: () => "/api/v1/themes",
  },
  {
    id: "theme-places",
    label: "GET /themes/places — 테마 POI",
    method: "GET",
    params: ["kind", "value", "limit", "cursor", "include"],
    description:
      "유튜버/재생목록/보정 검색어 하나의 확정 POI 목록. 공통 envelope(items·next_cursor)로 페이지네이션하며 source_videos는 기본 제외, include=sources일 때만 포함.",
    buildPath: (p) => {
      const q = new URLSearchParams();
      q.set("kind", p.kind ?? "channel");
      q.set("value", p.value ?? "");
      if (p.limit) q.set("limit", p.limit);
      if (p.cursor) q.set("cursor", p.cursor);
      if (p.include && p.include !== "none") q.set("include", p.include);
      return `/api/v1/themes/places?${q.toString()}`;
    },
  },
  {
    id: "video-theme",
    label: "GET /themes/video/{id}/places — 동영상 테마 POI",
    method: "GET",
    params: ["video_id", "limit", "cursor", "include"],
    description:
      "특정 동영상 테마 POI. 매치/검수 완료 POI 5개 이상일 때만 공개(items·envelope). source_videos는 include=sources 옵트인.",
    buildPath: (p) => {
      const q = new URLSearchParams();
      if (p.limit) q.set("limit", p.limit);
      if (p.cursor) q.set("cursor", p.cursor);
      if (p.include && p.include !== "none") q.set("include", p.include);
      const qs = q.toString();
      return `/api/v1/themes/video/${encodeURIComponent(p.video_id ?? "")}/places${qs ? `?${qs}` : ""}`;
    },
  },
  {
    id: "features-snapshot",
    label: "GET /features/snapshot — 전체 스냅샷",
    method: "GET",
    params: ["cursor", "limit"],
    description: "활성 feature 후보 full snapshot(opaque cursor 페이지네이션).",
    buildPath: (p) => {
      const q = new URLSearchParams();
      if (p.cursor) q.set("cursor", p.cursor);
      if (p.limit) q.set("limit", p.limit);
      const qs = q.toString();
      return `/api/v1/features/snapshot${qs ? `?${qs}` : ""}`;
    },
  },
  {
    id: "features-changes",
    label: "GET /features/changes — 변경 스트림",
    method: "GET",
    params: ["cursor", "limit"],
    description: "upsert/reject/tombstone 변경 incremental.",
    buildPath: (p) => {
      const q = new URLSearchParams();
      if (p.cursor) q.set("cursor", p.cursor);
      if (p.limit) q.set("limit", p.limit);
      const qs = q.toString();
      return `/api/v1/features/changes${qs ? `?${qs}` : ""}`;
    },
  },
];

const PARAM_LABELS: Record<ParamKind, string> = {
  kind: "테마 종류",
  value: "값(채널 ID·재생목록 ID·검색어)",
  video_id: "영상 ID",
  cursor: "cursor(선택)",
  limit: "limit(선택)",
  include: "출처 포함(include)",
};

export function ApiTestPanel() {
  const [endpointId, setEndpointId] = useState(ENDPOINTS[0].id);
  const [params, setParams] = useState<Record<string, string>>({
    kind: "channel",
    limit: "50",
  });
  const endpoint = ENDPOINTS.find((e) => e.id === endpointId) ?? ENDPOINTS[0];
  const path = endpoint.buildPath(params);

  // 테마 값 자동완성용 목록(선택 편의). 실패해도 페이지는 동작한다.
  const themesQuery = useQuery({ queryKey: ["themes"], queryFn: listThemes });

  const probe = useMutation({
    mutationFn: () => probeApi(path),
  });

  const externalCurl = `curl -H "X-API-Key: <발급받은_read_키>" "https://<REST-API-도메인>${path}"`;

  return (
    <div className="grid gap-4 xl:grid-cols-[0.9fr_1.1fr]">
      <section className="flex flex-col gap-4 rounded-lg border border-surface-muted bg-card p-4 shadow-[var(--shadow-card)]">
        <div>
          <div className="flex items-center gap-1">
            <h2 className="text-[16px] font-bold">요청</h2>
            <HelpTip>
              브라우저는 same-origin BFF를 거쳐 호출하므로 서버 전용 백엔드 키가
              자동 주입됩니다. 외부(비-브라우저)에서는 아래 curl처럼 읽기 전용으로
              발급받은 공개 API 키를 X-API-Key로 직접 보냅니다. 예시의 REST API
              도메인은 Web/BFF 도메인이 아니라 공개 backend API 도메인으로 바꾸세요.
            </HelpTip>
          </div>
          <p className="text-[13px] text-text-secondary">
            외부 공급 API(features·themes)를 호출해 응답을 확인합니다.
          </p>
        </div>

        <Field>
          <FieldLabel htmlFor="api-test-endpoint">엔드포인트</FieldLabel>
          <Select
            value={endpointId}
            onValueChange={(value) => setEndpointId(value ?? ENDPOINTS[0].id)}
          >
            <SelectTrigger id="api-test-endpoint" className="w-full">
              <SelectValue>{endpoint.label}</SelectValue>
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                {ENDPOINTS.map((option) => (
                  <SelectItem key={option.id} value={option.id}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>
          <p className="text-[12px] text-text-secondary">{endpoint.description}</p>
        </Field>

        {endpoint.params.includes("kind") ? (
          <Field>
            <FieldLabel htmlFor="api-test-kind">{PARAM_LABELS.kind}</FieldLabel>
            <Select
              value={params.kind ?? "channel"}
              onValueChange={(value) =>
                setParams((prev) => ({ ...prev, kind: value ?? "channel" }))
              }
            >
              <SelectTrigger id="api-test-kind" className="w-full">
                <SelectValue>{params.kind ?? "channel"}</SelectValue>
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  <SelectItem value="channel">channel (유튜버)</SelectItem>
                  <SelectItem value="playlist">playlist (재생목록)</SelectItem>
                  <SelectItem value="keyword">keyword (보정 검색어)</SelectItem>
                </SelectGroup>
              </SelectContent>
            </Select>
          </Field>
        ) : null}

        {endpoint.params.includes("include") ? (
          <Field>
            <FieldLabel htmlFor="api-test-include">
              {PARAM_LABELS.include}
            </FieldLabel>
            <Select
              value={params.include ?? "none"}
              onValueChange={(value) =>
                setParams((prev) => ({ ...prev, include: value ?? "none" }))
              }
            >
              <SelectTrigger id="api-test-include" className="w-full">
                <SelectValue>
                  {params.include === "sources"
                    ? "sources (출처 포함)"
                    : "기본 (출처 제외)"}
                </SelectValue>
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  <SelectItem value="none">기본 (출처 제외)</SelectItem>
                  <SelectItem value="sources">sources (출처 포함)</SelectItem>
                </SelectGroup>
              </SelectContent>
            </Select>
          </Field>
        ) : null}

        {endpoint.params
          .filter((p) => p !== "kind" && p !== "include")
          .map((paramKind) => (
            <Field key={paramKind}>
              <FieldLabel htmlFor={`api-test-${paramKind}`}>
                {PARAM_LABELS[paramKind]}
              </FieldLabel>
              <Input
                id={`api-test-${paramKind}`}
                value={params[paramKind] ?? ""}
                inputMode={paramKind === "limit" ? "numeric" : "text"}
                placeholder={paramKind === "value" ? "예: UC... / PL... / 부산 여행" : ""}
                onChange={(event) =>
                  setParams((prev) => ({
                    ...prev,
                    [paramKind]: event.target.value,
                  }))
                }
              />
              {paramKind === "value" ? (
                <ThemeHints
                  kind={params.kind ?? "channel"}
                  themes={themesQuery.data}
                  onPick={(value) =>
                    setParams((prev) => ({ ...prev, value }))
                  }
                />
              ) : null}
            </Field>
          ))}

        <div className="flex flex-col gap-1.5">
          <FieldLabel>요청 경로</FieldLabel>
          <code className="block break-all rounded-md border border-surface-muted bg-surface-subtle px-2.5 py-2 font-mono text-[12px]">
            {endpoint.method} {path}
          </code>
        </div>

        <Button
          type="button"
          onClick={() => probe.mutate()}
          disabled={probe.isPending}
        >
          {probe.isPending ? (
            <Loader2Icon data-icon="inline-start" className="animate-spin" />
          ) : (
            <PlayIcon data-icon="inline-start" />
          )}
          실행
        </Button>

        <div className="flex flex-col gap-1.5">
          <div className="flex items-center justify-between gap-2">
            <FieldLabel>외부 호출 예시(curl)</FieldLabel>
            <CopyButton size="xs" text={externalCurl} />
          </div>
          <code className="block break-all rounded-md border border-surface-muted bg-surface-subtle px-2.5 py-2 font-mono text-[12px] text-text-secondary">
            {externalCurl}
          </code>
        </div>
      </section>

      <section className="flex min-w-0 flex-col gap-3">
        <Panel title="응답">
          {probe.isPending ? (
            <EmptyState>호출 중…</EmptyState>
          ) : probe.data ? (
            <ResponseView result={probe.data} />
          ) : probe.error ? (
            <p className="text-[13px] text-destructive">{probe.error.message}</p>
          ) : (
            <EmptyState>실행을 누르면 상태·지연·응답 본문이 표시됩니다.</EmptyState>
          )}
        </Panel>
      </section>
    </div>
  );
}

function ThemeHints({
  kind,
  themes,
  onPick,
}: {
  kind: string;
  themes: ThemeList | undefined;
  onPick: (value: string) => void;
}) {
  const items =
    kind === "playlist"
      ? themes?.playlists
      : kind === "keyword"
        ? themes?.keywords
        : themes?.channels;
  const top = (items ?? []).slice(0, 6);
  if (top.length === 0) return null;
  return (
    <div className="flex flex-wrap gap-1.5 pt-1">
      {top.map((item) => (
        <button
          key={item.value}
          type="button"
          onClick={() => onPick(item.value)}
          className="inline-flex items-center gap-1 rounded-md border border-surface-muted bg-surface-subtle px-2 py-0.5 text-[11px] text-text-secondary transition-colors hover:border-brand/40 hover:text-text-primary"
          title={item.value}
        >
          <span className="max-w-[10rem] truncate">{item.title}</span>
          <span className="text-brand">{item.poi_count}</span>
        </button>
      ))}
    </div>
  );
}

function prettyBody(result: ApiProbeResult): string {
  if (typeof result.body === "string") return result.body;
  try {
    return JSON.stringify(result.body, null, 2);
  } catch {
    return result.rawText;
  }
}

function ResponseView({ result }: { result: ApiProbeResult }) {
  const pretty = prettyBody(result);
  // features·themes 모두 공통 envelope의 `items` 배열을 반환한다.
  const count = Array.isArray((result.body as { items?: unknown[] })?.items)
    ? (result.body as { items: unknown[] }).items.length
    : null;

  return (
    <div className="flex min-w-0 flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant={result.ok ? "secondary" : "destructive"}>
          HTTP {result.status}
        </Badge>
        <Badge variant="outline">{result.ms}ms</Badge>
        <Badge variant="outline">{result.rawText.length.toLocaleString()}B</Badge>
        {count != null ? <Badge variant="outline">{count}건</Badge> : null}
        <span className="ml-auto">
          <CopyButton size="xs" text={pretty} label="본문 복사" />
        </span>
      </div>
      <pre className="max-h-[28rem] overflow-auto rounded-lg border border-surface-muted bg-surface-subtle p-3 text-[12px] whitespace-pre-wrap">
        {pretty}
      </pre>
    </div>
  );
}
