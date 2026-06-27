"use client";

import {
  type CrawlRunSummary,
  type SourceTargetSummary,
} from "@/lib/api";
import { JobDetailView } from "@/components/JobDetailView";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

// 1회성 작업(run)은 별도 페이지(/jobs/[id])로 이동하므로, 이 다이얼로그는 주로
// 반복 작업(target) 상세에 쓰인다. 본문은 JobDetailView를 공용으로 사용한다.
export function JobDetailDialog({
  run,
  target,
  onClose,
}: {
  run?: CrawlRunSummary | null;
  target?: SourceTargetSummary | null;
  onClose: () => void;
}) {
  const open = Boolean(run || target);
  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="max-h-[85vh] max-w-2xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>작업 상세</DialogTitle>
          <DialogDescription>
            {run
              ? "1회성 작업의 입력값·결과·수집 영상"
              : "반복 작업의 설정과 그동안 수집한 영상"}
          </DialogDescription>
        </DialogHeader>
        <JobDetailView run={run} target={target} onNavigate={onClose} />
      </DialogContent>
    </Dialog>
  );
}
