import type { CrawlRunSummary, RunQueueSnapshot } from "./api";
import { runStateLabel } from "./display-labels";

function targetLabel(run: CrawlRunSummary): string {
  return run.target_label ?? run.target_id ?? run.source ?? "작업";
}

export function buildRunQueueDisplay(
  snapshot: RunQueueSnapshot | undefined,
  isError: boolean,
) {
  const runs = snapshot?.items ?? [];
  const openAttentionCount = snapshot?.open_attention_count ?? 0;
  const runningCount = snapshot?.running_count ?? 0;
  const pendingCount = snapshot?.pending_count ?? 0;
  const activeCount = runningCount + pendingCount;
  const running = runs.filter((run) => run.state.toLowerCase() === "running");
  const pending = runs.filter((run) => run.state.toLowerCase() === "pending");
  const current = running[0] ?? pending[0] ?? null;
  const statusHref = openAttentionCount > 0 ? "/jobs?attention=open" : "/jobs";
  const summary = isError
    ? "작업 상태 오류"
    : current
      ? `${runStateLabel(current.state)} · ${targetLabel(current)} · ${
          current.current_message ?? "로그 대기 중"
        }`
      : "유휴 상태";

  return {
    openAttentionCount,
    runningCount,
    pendingCount,
    activeCount,
    current,
    statusHref,
    summary,
  };
}
