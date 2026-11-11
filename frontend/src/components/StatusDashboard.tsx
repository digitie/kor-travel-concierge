"use client";

import type {
  AuditLogSummary,
  LoginEventSummary,
  MetricsSummary,
  RunQueueSnapshot,
  RustfsStatus,
} from "@/lib/api";
import type { UseQueryResult } from "@tanstack/react-query";

import { useQuery } from "@tanstack/react-query";
import { RefreshCwIcon } from "lucide-react";
import { useSyncExternalStore } from "react";

import { DataLoadError } from "@/components/JobDetailView";
import {
  CountList,
  EmptyState,
  Metric,
  Panel,
  Section,
} from "@/components/panels";
import { StatStrip } from "@/components/StatStrip";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  getMetrics,
  getRustfsStatus,
  listAuditLogs,
  listLoginEvents,
  listRunQueue,
  RUN_QUEUE_OBSERVER_OPTIONS,
  RUN_QUEUE_QUERY_KEY,
} from "@/lib/api";
import {
  assetTypeLabel,
  candidateStatusLabel,
  loginEventLabel,
  loginOutcomeLabel,
} from "@/lib/display-labels";
import {
  asNum,
  asRecord,
  formatBytes,
  formatDateTimeShort,
} from "@/lib/format";

function auditActionLabel(value: string): string {
  if (value.includes("settings")) return "설정";
  if (value.includes("api_key")) return "API 키";
  if (value.includes("login")) return "로그인";
  return value.replaceAll("_", " ").replaceAll(".", " ");
}

function auditTargetLabel(value: string): string {
  if (value === "admin") return "관리자";
  if (value === "api_key") return "API 키";
  if (value === "setting") return "설정";
  return value.replaceAll("_", " ");
}

function subscribeClientState() {
  return () => undefined;
}

function getClientSnapshot() {
  return true;
}

function getServerSnapshot() {
  return false;
}

export function StatusDashboard() {
  const mounted = useSyncExternalStore(
    subscribeClientState,
    getClientSnapshot,
    getServerSnapshot,
  );
  const queueQuery = useQuery({
    queryKey: RUN_QUEUE_QUERY_KEY,
    queryFn: listRunQueue,
    ...RUN_QUEUE_OBSERVER_OPTIONS,
  });
  const metricsQuery = useQuery({
    queryKey: ["metrics"],
    queryFn: getMetrics,
    refetchInterval: 10_000,
  });
  const rustfsQuery = useQuery({
    queryKey: ["rustfs-status"],
    queryFn: getRustfsStatus,
    refetchInterval: 15_000,
  });
  const auditQuery = useQuery({
    queryKey: ["audit-logs"],
    queryFn: listAuditLogs,
    refetchInterval: 15_000,
  });
  const loginEventsQuery = useQuery({
    queryKey: ["login-events", "status"],
    queryFn: listLoginEvents,
    refetchInterval: 15_000,
  });

  const {
    openAttentionCount,
    runningCount,
    candidatesByStatus,
    storage,
    rustfs,
    queueSummary,
    databaseSummary,
    storageSummary,
  } = buildOperationalSummary(queueQuery, metricsQuery, rustfsQuery);

  function refresh() {
    void queueQuery.refetch();
    void metricsQuery.refetch();
    void rustfsQuery.refetch();
    void auditQuery.refetch();
    void loginEventsQuery.refetch();
  }

  if (!mounted) {
    return (
      <p role="status" className="text-sm text-text-secondary">
        상태 정보를 불러오는 중입니다.
      </p>
    );
  }

  return (
    <div className="ktc-workspace flex flex-col gap-8">
      <div className="flex flex-wrap items-end justify-between gap-x-4 gap-y-3">
        <div>
          <p className="ktc-eyebrow mb-1">실시간 관측</p>
          <h2 className="text-[22px] leading-tight font-extrabold tracking-[-0.035em]">
            운영 요약
          </h2>
          <p className="mt-1 text-[13px] text-text-secondary">
            수집 큐, 저장소, 검수 병목을 한눈에 확인합니다.
          </p>
        </div>
        <Button type="button" variant="outline" size="sm" onClick={refresh}>
          <RefreshCwIcon data-icon="inline-start" />
          새로고침
        </Button>
      </div>

      {queueQuery.error || metricsQuery.error || rustfsQuery.error ? (
        <StatusLoadErrors
          queueQuery={queueQuery}
          metricsQuery={metricsQuery}
          rustfsQuery={rustfsQuery}
        />
      ) : null}

      <OperationalMetrics
        queueSummary={queueSummary}
        openAttentionCount={openAttentionCount}
        runningCount={runningCount}
        databaseSummary={databaseSummary}
        storageSummary={storageSummary}
        storage={storage}
        rustfs={rustfs}
        candidatesByStatus={candidatesByStatus}
      />

      <Section title="데이터">
        <section className="grid gap-4 xl:grid-cols-2">
          <StorageStatus
            metricsQuery={metricsQuery}
            rustfsQuery={rustfsQuery}
            rustfs={rustfs}
            storage={storage}
          />

          <Panel title="검수 후보 상태">
            {metricsQuery.isPending ? (
              <EmptyState>운영 지표를 불러오는 중입니다.</EmptyState>
            ) : metricsQuery.isError ? (
              <p className="text-sm text-text-secondary">
                위 운영 지표 오류를 해결한 뒤 검수 후보를 다시 확인하세요.
              </p>
            ) : (
              <CountList
                counts={candidatesByStatus}
                empty="검수 후보가 없습니다."
                labeler={candidateStatusLabel}
              />
            )}
          </Panel>
        </section>
      </Section>

      <Section title="보안">
        <section className="grid gap-4 xl:grid-cols-2">
          <LoginEventHistory loginEventsQuery={loginEventsQuery} />

          <AuditEventHistory auditQuery={auditQuery} />
        </section>
      </Section>
    </div>
  );
}

function StorageStatus({
  metricsQuery,
  rustfsQuery,
  rustfs,
  storage,
}: {
  metricsQuery: UseQueryResult<MetricsSummary, Error>;
  rustfsQuery: UseQueryResult<RustfsStatus, Error>;
  rustfs: RustfsStatus | undefined;
  storage:
    | {
        enabled?: boolean;
        endpoint?: string;
        console_url?: string;
        retention_policy?: string;
        health?: {
          ok: boolean;
          status_code: number | null;
          error: string | null;
        };
        assets?: { asset_type: string; count: number; size_bytes: number }[];
        total_objects?: number;
        total_size_bytes?: number;
      }
    | undefined;
}) {
  return (
    <Panel title="저장소 상세">
      {metricsQuery.isPending || rustfsQuery.isPending ? (
        <EmptyState>저장소 정보를 불러오는 중입니다.</EmptyState>
      ) : metricsQuery.isError || rustfsQuery.isError ? (
        <p className="text-sm text-text-secondary">
          위 오류를 해결한 뒤 저장소 상세를 다시 확인하세요.
        </p>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-2">
            <Metric
              label="상태"
              value={rustfs?.health?.ok ? "정상" : "확인 필요"}
            />
            <Metric
              label="객체 수"
              value={asNum(storage?.total_objects).toLocaleString()}
            />
            <Metric
              label="총 용량"
              value={formatBytes(storage?.total_size_bytes)}
            />
            <Metric label="보존 정책" value={rustfs?.retention_policy ?? "-"} />
          </div>
          {(storage?.assets ?? rustfs?.assets ?? []).length > 0 ? (
            <div className="mt-3 flex flex-col divide-y divide-border rounded-control border border-border text-sm">
              {(storage?.assets ?? rustfs?.assets ?? []).map((asset) => (
                <div
                  key={asset.asset_type}
                  className="flex items-center justify-between gap-3 px-3 py-2"
                >
                  <span className="text-text-secondary">
                    {assetTypeLabel(asset.asset_type)}
                  </span>
                  <span>
                    {asset.count.toLocaleString()}개 ·{" "}
                    {formatBytes(asset.size_bytes)}
                  </span>
                </div>
              ))}
            </div>
          ) : null}
        </>
      )}
    </Panel>
  );
}

function LoginEventHistory({
  loginEventsQuery,
}: {
  loginEventsQuery: UseQueryResult<LoginEventSummary[], Error>;
}) {
  return (
    <Panel title="로그인 기록">
      {loginEventsQuery.isPending ? (
        <EmptyState>로그인 기록을 불러오는 중입니다.</EmptyState>
      ) : loginEventsQuery.isError ? (
        <DataLoadError
          error={loginEventsQuery.error}
          fallback="로그인 기록을 불러오지 못했습니다."
          onRetry={() => void loginEventsQuery.refetch()}
        />
      ) : (loginEventsQuery.data ?? []).length > 0 ? (
        <div className="max-h-80 overflow-y-auto rounded-control border border-border text-sm">
          {(loginEventsQuery.data ?? []).map((event) => (
            <div
              key={event.id}
              className="border-b border-border px-3 py-2 last:border-b-0"
            >
              <div className="flex items-center justify-between gap-2">
                <span className="font-medium">
                  {loginEventLabel(event.event_type)}
                </span>
                <Badge
                  variant={
                    event.outcome === "succeeded" ? "secondary" : "outline"
                  }
                >
                  {loginOutcomeLabel(event.outcome)}
                </Badge>
              </div>
              <p className="mt-1 text-[12px] text-text-secondary">
                {formatDateTimeShort(event.created_at)} ·{" "}
                {event.attempted_username || "-"} · {event.reason || "-"}
              </p>
              <p className="truncate text-[12px] text-text-secondary">
                {event.client_ip || "unknown ip"}
              </p>
            </div>
          ))}
        </div>
      ) : (
        <EmptyState>저장된 로그인 기록이 없습니다.</EmptyState>
      )}
    </Panel>
  );
}

function AuditEventHistory({
  auditQuery,
}: {
  auditQuery: UseQueryResult<AuditLogSummary[], Error>;
}) {
  return (
    <Panel title="최근 감사 로그">
      {auditQuery.isPending ? (
        <EmptyState>감사 로그를 불러오는 중입니다.</EmptyState>
      ) : auditQuery.isError ? (
        <DataLoadError
          error={auditQuery.error}
          fallback="감사 로그를 불러오지 못했습니다."
          onRetry={() => void auditQuery.refetch()}
        />
      ) : (auditQuery.data ?? []).length > 0 ? (
        <div className="flex max-h-80 flex-col divide-y divide-border overflow-y-auto rounded-control border border-border text-sm">
          {(auditQuery.data ?? []).map((log) => (
            <div key={log.id} className="px-3 py-2">
              <div className="flex items-center justify-between gap-2">
                <span className="font-medium">
                  {auditActionLabel(log.action)}
                </span>
                <span className="text-[12px] text-text-secondary">
                  {formatDateTimeShort(log.created_at)}
                </span>
              </div>
              <p className="truncate text-text-secondary">
                {auditTargetLabel(log.actor_type)} ·{" "}
                {auditTargetLabel(log.target_type)}
                {log.target_id ? ` #${log.target_id}` : ""}
              </p>
            </div>
          ))}
        </div>
      ) : (
        <EmptyState>감사 로그가 없습니다.</EmptyState>
      )}
    </Panel>
  );
}

function OperationalMetrics({
  queueSummary,
  openAttentionCount,
  runningCount,
  databaseSummary,
  storageSummary,
  storage,
  rustfs,
  candidatesByStatus,
}: {
  queueSummary: string;
  openAttentionCount: number;
  runningCount: number;
  databaseSummary: string;
  storageSummary: string;
  storage:
    | {
        enabled?: boolean;
        endpoint?: string;
        console_url?: string;
        retention_policy?: string;
        health?: {
          ok: boolean;
          status_code: number | null;
          error: string | null;
        };
        assets?: { asset_type: string; count: number; size_bytes: number }[];
        total_objects?: number;
        total_size_bytes?: number;
      }
    | undefined;
  rustfs: RustfsStatus | undefined;
  candidatesByStatus: Record<string, number>;
}) {
  return (
    <StatStrip
      ariaLabel="운영 요약 지표"
      className="border-y border-border py-4"
      items={[
        {
          label: "실행 큐",
          value: queueSummary,
          tone:
            openAttentionCount > 0
              ? "warning"
              : runningCount > 0
                ? "info"
                : "neutral",
          href: openAttentionCount > 0 ? "/jobs?attention=open" : "/jobs",
        },
        {
          label: "DB 장소/영상",
          value: databaseSummary,
          tone: "neutral",
        },
        {
          label: "RustFS",
          value: storageSummary,
          tone:
            storage?.health?.ok || rustfs?.health?.ok ? "success" : "warning",
        },
        {
          label: "검수 후보",
          value:
            Object.entries(candidatesByStatus)
              .map(([key, value]) => `${candidateStatusLabel(key)} ${value}`)
              .join(" · ") || "후보 없음",
          tone:
            asNum(candidatesByStatus.needs_review) > 0 ? "warning" : "neutral",
          href: "/review",
        },
      ]}
      size="lg"
    />
  );
}

function StatusLoadErrors({
  queueQuery,
  metricsQuery,
  rustfsQuery,
}: {
  queueQuery: UseQueryResult<RunQueueSnapshot, Error>;
  metricsQuery: UseQueryResult<MetricsSummary, Error>;
  rustfsQuery: UseQueryResult<RustfsStatus, Error>;
}) {
  return (
    <div aria-label="상태 정보 불러오기 오류" className="grid gap-2">
      {queueQuery.error ? (
        <DataLoadError
          error={queueQuery.error}
          fallback="작업 대기열을 불러오지 못했습니다."
          onRetry={() => void queueQuery.refetch()}
        />
      ) : null}
      {metricsQuery.error ? (
        <DataLoadError
          error={metricsQuery.error}
          fallback="운영 지표를 불러오지 못했습니다."
          onRetry={() => void metricsQuery.refetch()}
        />
      ) : null}
      {rustfsQuery.error ? (
        <DataLoadError
          error={rustfsQuery.error}
          fallback="RustFS 상태를 불러오지 못했습니다."
          onRetry={() => void rustfsQuery.refetch()}
        />
      ) : null}
    </div>
  );
}

function buildOperationalSummary(
  queueQuery: Pick<
    UseQueryResult<RunQueueSnapshot>,
    "data" | "isPending" | "isError"
  >,
  metricsQuery: Pick<
    UseQueryResult<MetricsSummary>,
    "data" | "isPending" | "isError"
  >,
  rustfsQuery: Pick<
    UseQueryResult<RustfsStatus>,
    "data" | "isPending" | "isError"
  >,
) {
  const openAttentionCount = queueQuery.data?.open_attention_count ?? 0;
  const runningCount = queueQuery.data?.running_count ?? 0;
  const pendingCount = queueQuery.data?.pending_count ?? 0;
  const metrics = metricsQuery.data;
  const db = metrics?.database ?? {};
  const candidatesByStatus = asRecord(db.candidates_by_status);
  const storage = metrics?.storage;
  const rustfs = rustfsQuery.data;
  const queueSummary = queueQuery.isPending
    ? "불러오는 중"
    : queueQuery.isError
      ? "확인 필요"
      : `실행 ${runningCount} · 대기 ${pendingCount} · 확인 필요 ${openAttentionCount}`;
  const databaseSummary = metricsQuery.isPending
    ? "불러오는 중"
    : metricsQuery.isError
      ? "확인 필요"
      : `${asNum(db.travel_places).toLocaleString()} 장소 · ${asNum(
          db.youtube_videos,
        ).toLocaleString()} 영상`;
  const storageSummary =
    metricsQuery.isPending || rustfsQuery.isPending
      ? "불러오는 중"
      : metricsQuery.isError || rustfsQuery.isError
        ? "확인 필요"
        : `${storage?.health?.ok || rustfs?.health?.ok ? "정상" : "확인 필요"} · ${formatBytes(
            storage?.total_size_bytes,
          )}`;

  return {
    openAttentionCount,
    runningCount,
    candidatesByStatus,
    storage,
    rustfs,
    queueSummary,
    databaseSummary,
    storageSummary,
  };
}
