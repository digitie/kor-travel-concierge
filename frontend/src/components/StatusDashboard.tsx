"use client";

import { useSyncExternalStore } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangleIcon,
  DatabaseIcon,
  HardDriveIcon,
  ListChecksIcon,
  RefreshCwIcon,
} from "lucide-react";

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
import { asNum, asRecord, formatBytes, formatDateTimeShort } from "@/lib/format";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  CountList,
  EmptyState,
  Metric,
  MetricCard,
  Panel,
  Section,
} from "@/components/panels";

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

  const openAttentionCount = queueQuery.data?.open_attention_count ?? 0;
  const runningCount = queueQuery.data?.running_count ?? 0;
  const pendingCount = queueQuery.data?.pending_count ?? 0;
  const metrics = metricsQuery.data;
  const db = metrics?.database ?? {};
  const candidatesByStatus = asRecord(db.candidates_by_status);
  const storage = metrics?.storage;
  const rustfs = rustfsQuery.data;

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
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-[16px] font-bold">운영 요약</h2>
        <Button type="button" variant="outline" size="sm" onClick={refresh}>
          <RefreshCwIcon data-icon="inline-start" />
          새로고침
        </Button>
      </div>

      <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <MetricCard
          icon={<ListChecksIcon className="size-4" />}
          label="실행 큐"
          value={`실행 ${runningCount} · 대기 ${pendingCount} · 확인 필요 ${openAttentionCount}`}
          tone={
            openAttentionCount > 0
              ? "warn"
              : runningCount > 0
                ? "active"
                : "neutral"
          }
          href={openAttentionCount > 0 ? "/jobs?attention=open" : "/jobs"}
        />
        <MetricCard
          icon={<DatabaseIcon className="size-4" />}
          label="DB 장소/영상"
          value={`${asNum(db.travel_places).toLocaleString()} 장소 · ${asNum(
            db.youtube_videos,
          ).toLocaleString()} 영상`}
        />
        <MetricCard
          icon={<HardDriveIcon className="size-4" />}
          label="RustFS"
          value={`${storage?.health?.ok || rustfs?.health?.ok ? "정상" : "확인 필요"} · ${formatBytes(
            storage?.total_size_bytes,
          )}`}
          tone={storage?.health?.ok || rustfs?.health?.ok ? "neutral" : "warn"}
        />
        <MetricCard
          icon={<AlertTriangleIcon className="size-4" />}
          label="검수 후보"
          value={Object.entries(candidatesByStatus)
            .map(([key, value]) => `${candidateStatusLabel(key)} ${value}`)
            .join(" · ") || "후보 없음"}
          tone={asNum(candidatesByStatus.needs_review) > 0 ? "warn" : "neutral"}
          href="/review"
        />
      </section>

      <Section title="데이터">
        <section className="grid gap-4 xl:grid-cols-2">
          <Panel title="저장소 상세">
            <div className="grid grid-cols-2 gap-2">
              <Metric label="상태" value={rustfs?.health?.ok ? "정상" : "확인 필요"} />
              <Metric
                label="객체 수"
                value={asNum(storage?.total_objects).toLocaleString()}
              />
              <Metric label="총 용량" value={formatBytes(storage?.total_size_bytes)} />
              <Metric label="보존 정책" value={rustfs?.retention_policy ?? "-"} />
            </div>
            {(storage?.assets ?? rustfs?.assets ?? []).length > 0 ? (
              <div className="mt-3 flex flex-col divide-y divide-surface-muted rounded-lg border border-surface-muted text-[13px]">
                {(storage?.assets ?? rustfs?.assets ?? []).map((asset) => (
                  <div
                    key={asset.asset_type}
                    className="flex items-center justify-between gap-3 px-3 py-2"
                  >
                    <span className="text-text-secondary">
                      {assetTypeLabel(asset.asset_type)}
                    </span>
                    <span>
                      {asset.count.toLocaleString()}개 · {formatBytes(asset.size_bytes)}
                    </span>
                  </div>
                ))}
              </div>
            ) : null}
          </Panel>

          <Panel title="검수 후보 상태">
            <CountList
              counts={candidatesByStatus}
              empty="검수 후보가 없습니다."
              labeler={candidateStatusLabel}
            />
          </Panel>
        </section>
      </Section>

      <Section title="보안">
        <section className="grid gap-4 xl:grid-cols-2">
          <Panel title="로그인 기록">
            {(loginEventsQuery.data ?? []).length > 0 ? (
              <div className="max-h-80 overflow-y-auto rounded-lg border border-surface-muted text-[13px]">
                {(loginEventsQuery.data ?? []).map((event) => (
                  <div
                    key={event.id}
                    className="border-b border-surface-muted px-3 py-2 last:border-b-0"
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

          <Panel title="최근 감사 로그">
            {(auditQuery.data ?? []).length > 0 ? (
              <div className="flex max-h-80 flex-col divide-y divide-surface-muted overflow-y-auto rounded-lg border border-surface-muted text-[13px]">
                {(auditQuery.data ?? []).map((log) => (
                  <div key={log.id} className="px-3 py-2">
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-medium">{auditActionLabel(log.action)}</span>
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
        </section>
      </Section>
    </div>
  );
}
