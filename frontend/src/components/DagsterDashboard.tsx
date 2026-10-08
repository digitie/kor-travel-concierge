"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { DagsterOperations } from "@kor-travel/ui/dagster-operations";
import { parseHealthyDagsterSummary, type ConciergeSnapshot } from "@/lib/dagster";

const JOB_LABELS: Record<string, string> = {
  concierge_interactive: "즉시 수집", concierge_batch: "대량 수집",
  concierge_source_scan: "수집원 탐색", concierge_feature_exports: "결과 내보내기",
};

const LOAD_ERROR = "Dagster 상태를 확인하지 못했습니다. 마지막 정상 조회를 표시합니다.";

export function DagsterDashboard() {
  // last-good는 이 인증 화면의 수명에만 존재한다. 전역 query/localStorage에 적재하지 않는다.
  const [snapshot, setSnapshot] = useState<ConciergeSnapshot | null>(null);
  const [publicUrl, setPublicUrl] = useState("");
  const [error, setError] = useState<string | undefined>();
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const pending = useRef<AbortController | null>(null);
  const sequence = useRef(0);
  const refresh = useCallback(async () => {
    pending.current?.abort();
    const controller = new AbortController();
    pending.current = controller;
    const request = ++sequence.current;
    setLoading(true);
    try {
      const response = await fetch("/api/v1/admin/dagster/summary", {
        cache: "no-store", signal: AbortSignal.any([controller.signal, AbortSignal.timeout(15_000)]),
      });
      if (response.status === 401 || response.status === 403) {
        if (request === sequence.current) { setSnapshot(null); setSelected(null); }
        throw new Error("관리자 인증 만료");
      }
      if (!response.ok) throw new Error("조회 실패");
      const payload = parseHealthyDagsterSummary(await response.json());
      if (controller.signal.aborted || request !== sequence.current) return;
      const nextPublicUrl = payload.publicUrl.replace(/\/$/, "");
      setSnapshot(payload.snapshot);
      setPublicUrl(nextPublicUrl);
      setSelected(current => payload.snapshot!.runs.some(run => run.runId === current) ? current : null);
      setError(undefined);
    } catch {
      if (!controller.signal.aborted && request === sequence.current) setError(LOAD_ERROR);
    } finally {
      if (request === sequence.current) setLoading(false);
    }
  }, []);
  useEffect(() => {
    const first = setTimeout(() => { void refresh(); }, 0);
    const interval = setInterval(() => { void refresh(); }, 30_000);
    return () => { clearTimeout(first); clearInterval(interval); pending.current?.abort(); };
  }, [refresh]);
  return <section data-kt-surface className="min-w-0" aria-label="Dagster 운영 상태">
    <p className="mb-4 text-sm text-text-secondary">수집 결과·중지·재시작은 <Link href="/jobs">작업 화면</Link>에서 확인합니다.</p>
    <DagsterOperations snapshot={snapshot} error={error} loading={loading}
      jobLabel={name => JOB_LABELS[name] ?? name}
      onRefresh={() => { void refresh(); }} showRunDetails selectedRunId={selected}
      onSelectRun={id => setSelected(current => current === id ? null : id)}
      runUrl={id => `${publicUrl}/runs/${encodeURIComponent(id)}`}
      locationUrl={snapshot?.repositories[0] ? `${publicUrl}/locations/${encodeURIComponent(`${snapshot.repositories[0].name}@${snapshot.repositories[0].locationName}`)}` : undefined}
      scheduleUrl={(name, repository) => `${publicUrl}/locations/${encodeURIComponent(`${repository.name}@${repository.locationName}`)}/schedules/${encodeURIComponent(name)}`}
      renderRunDetail={run => {
        if (!run) return null;
        const domain = snapshot?.runs.find(item => item.runId === run.runId)?.domainRunId;
        return <div key={run.runId} data-testid="concierge-selected-run" className="min-w-0 space-y-2 break-words">
          <h3 className="font-semibold">{run.jobName}</h3>
          <p className="break-all">실행 ID: <code>{run.runId}</code></p>
          <p>상태: {run.status} · 시간 상한: {run.maxRuntimeSeconds ? `${run.maxRuntimeSeconds}초` : "미확인"}</p>
          <a href={`${publicUrl}/runs/${encodeURIComponent(run.runId)}`} target="_blank" rel="noreferrer">Dagster 실행 로그</a>
          {domain ? <p><Link href={`/jobs/${domain}`}>수집 작업 #{domain} 상세·중지·재시작</Link></p> : null}
        </div>;
      }} testId="concierge-common-dagster" />
  </section>;
}
