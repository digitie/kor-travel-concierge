"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ActivityIcon } from "lucide-react";

import { getMetrics } from "@/lib/api";
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

function asNum(value: unknown): number {
  return typeof value === "number" ? value : 0;
}
function asRecord(value: unknown): Record<string, number> {
  return value && typeof value === "object"
    ? (value as Record<string, number>)
    : {};
}
function formatBytes(bytes: number | undefined): string {
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(value >= 10 || unit === 0 ? 0 : 1)} ${units[unit]}`;
}

export function OpsMetricsDialog() {
  const [open, setOpen] = useState(false);
  const metricsQuery = useQuery({
    queryKey: ["metrics"],
    queryFn: getMetrics,
    enabled: open,
    refetchInterval: open ? 10_000 : false,
  });
  const metrics = metricsQuery.data;
  const storage = metrics?.storage;
  const db = metrics?.database ?? {};
  const candidatesByStatus = asRecord(db.candidates_by_status);
  const runsByState = asRecord(db.runs_by_state);

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger
        render={
          <Button type="button" variant="outline" size="sm">
            <ActivityIcon data-icon="inline-start" />
            운영
          </Button>
        }
      />
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>운영 지표</DialogTitle>
          <DialogDescription>
            스토리지·데이터베이스 상세 수치 (10초마다 갱신)
          </DialogDescription>
        </DialogHeader>

        {metrics ? (
          <div className="flex flex-col gap-5">
            <section className="flex flex-col gap-2">
              <h3 className="text-sm font-semibold">스토리지 (RustFS)</h3>
              <div className="grid grid-cols-3 gap-2">
                <Metric
                  label="상태"
                  value={storage?.health?.ok ? "정상" : "확인 필요"}
                />
                <Metric label="객체 수" value={asNum(storage?.total_objects).toLocaleString()} />
                <Metric label="총 용량" value={formatBytes(storage?.total_size_bytes)} />
              </div>
              {storage?.assets?.length ? (
                <div className="flex flex-col gap-1 rounded-lg border p-2 text-xs">
                  {storage.assets.map((asset) => (
                    <div
                      key={asset.asset_type}
                      className="flex items-center justify-between gap-3"
                    >
                      <span className="text-muted-foreground">
                        {asset.asset_type}
                      </span>
                      <span>
                        {asset.count.toLocaleString()}개 ·{" "}
                        {formatBytes(asset.size_bytes)}
                      </span>
                    </div>
                  ))}
                </div>
              ) : null}
            </section>

            <section className="flex flex-col gap-2 border-t pt-4">
              <h3 className="text-sm font-semibold">데이터베이스</h3>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                <Metric label="영상" value={asNum(db.youtube_videos).toLocaleString()} />
                <Metric label="채널" value={asNum(db.youtube_channels).toLocaleString()} />
                <Metric label="재생목록" value={asNum(db.youtube_playlists).toLocaleString()} />
                <Metric label="언급 매핑" value={asNum(db.video_place_mappings).toLocaleString()} />
                <Metric label="장소" value={asNum(db.travel_places).toLocaleString()} />
                <Metric
                  label="지오코딩"
                  value={asNum(db.travel_places_geocoded).toLocaleString()}
                />
                <Metric
                  label="반복 작업"
                  value={asNum(db.active_recurring_targets).toLocaleString()}
                />
                <Metric label="export" value={asNum(db.feature_exports).toLocaleString()} />
              </div>
            </section>

            <section className="grid grid-cols-1 gap-4 border-t pt-4 sm:grid-cols-2">
              <div className="flex flex-col gap-2">
                <h3 className="text-sm font-semibold">검수 후보 상태</h3>
                <CountList counts={candidatesByStatus} empty="후보 없음" />
              </div>
              <div className="flex flex-col gap-2">
                <h3 className="text-sm font-semibold">작업 상태</h3>
                <CountList counts={runsByState} empty="작업 없음" />
              </div>
            </section>
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">
            {metricsQuery.error
              ? metricsQuery.error.message
              : "지표를 불러오는 중…"}
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
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-1 rounded-lg border p-2.5">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="text-lg font-semibold">{value}</span>
    </div>
  );
}

function CountList({
  counts,
  empty,
}: {
  counts: Record<string, number>;
  empty: string;
}) {
  const entries = Object.entries(counts);
  if (entries.length === 0) {
    return (
      <p className="rounded-lg border p-2 text-xs text-muted-foreground">
        {empty}
      </p>
    );
  }
  return (
    <div className="flex flex-col gap-1 rounded-lg border p-2 text-xs">
      {entries.map(([key, value]) => (
        <div key={key} className="flex items-center justify-between gap-3">
          <span className="text-muted-foreground">{key}</span>
          <span>{value.toLocaleString()}</span>
        </div>
      ))}
    </div>
  );
}
