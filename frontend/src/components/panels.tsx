import type { ReactNode } from "react";
import Link from "next/link";
import { CheckCircle2Icon } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

// 상태/작업 상세/수집 화면이 각자 복붙하던 대시보드 조각(Section/Panel/MetricCard/
// Metric/CountList/EmptyState)의 단일 출처. 제목 텍스트와 heading 역할은 E2E가
// 검증하므로 렌더 구조(h2)를 유지한다.

/** 화면 내 큰 묶음(작업/데이터/보안 등). 제목 + 선택적 우측 액션. */
export function Section({
  title,
  actions,
  children,
}: {
  title: string;
  actions?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="flex flex-col gap-3">
      {actions ? (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-[15px] font-bold">{title}</h2>
          {actions}
        </div>
      ) : (
        <h2 className="text-[15px] font-bold">{title}</h2>
      )}
      {children}
    </section>
  );
}

/** 정보 단위 경계 카드(DESIGN-RULES 3). 제목은 h2 유지(E2E). */
export function Panel({
  title,
  icon,
  className,
  children,
}: {
  title: string;
  icon?: ReactNode;
  className?: string;
  children: ReactNode;
}) {
  return (
    <section
      className={cn(
        "rounded-lg border border-surface-muted bg-card p-4 shadow-[var(--shadow-card)]",
        className,
      )}
    >
      <h2 className="mb-3 flex items-center gap-1.5 text-[14px] font-bold">
        {icon ?? <CheckCircle2Icon className="size-4 text-brand" />}
        {title}
      </h2>
      {children}
    </section>
  );
}

/** 목록 패널 상단 제목 + 개수 배지 줄(장소/후보/반복 작업 목록 공용). */
export function PanelHeader({
  title,
  count,
  icon,
}: {
  title: string;
  count: ReactNode;
  icon?: ReactNode;
}) {
  return (
    <div className="flex items-center justify-between gap-3">
      <h2 className="flex items-center gap-1.5 text-sm font-semibold">
        {icon}
        {title}
      </h2>
      <Badge variant="secondary">{count}</Badge>
    </div>
  );
}

/** KPI 카드(아이콘 + uppercase 라벨 + 굵은 값). href를 주면 카드 전체가 링크가 된다. */
export function MetricCard({
  icon,
  label,
  value,
  tone = "neutral",
  href,
}: {
  icon: ReactNode;
  label: string;
  value: string;
  tone?: "neutral" | "active" | "warn";
  href?: string;
}) {
  const body = (
    <>
      <span
        className={
          tone === "active"
            ? "mt-0.5 text-brand"
            : tone === "warn"
              ? "mt-0.5 text-warning"
              : "mt-0.5 text-text-secondary"
        }
      >
        {icon}
      </span>
      <span className="min-w-0">
        <span className="block text-[12px] font-bold uppercase tracking-[0.05em] text-text-secondary">
          {label}
        </span>
        <span className="mt-1 block text-[16px] font-bold leading-snug text-text-primary">
          {value}
        </span>
      </span>
    </>
  );
  const className =
    "flex min-w-0 items-start gap-3 rounded-lg border border-surface-muted bg-card p-4 shadow-[var(--shadow-card)]";
  if (href) {
    return (
      <Link
        href={href}
        className={cn(
          className,
          "transition-colors hover:border-brand/40 hover:bg-brand-tint/40",
        )}
      >
        {body}
      </Link>
    );
  }
  return <div className={className}>{body}</div>;
}

/** 작은 라벨/값 셀(요약 그리드·다이얼로그 요약 공용). KPI 숫자는 size="lg"로 크게(규칙 8). */
export function Metric({
  label,
  value,
  size = "sm",
}: {
  label: string;
  value: string;
  size?: "sm" | "lg";
}) {
  return (
    <div className="flex flex-col gap-1 rounded-lg border border-surface-muted bg-surface-subtle p-3">
      <span className="text-[12px] font-bold uppercase tracking-[0.05em] text-text-secondary">
        {label}
      </span>
      <span
        className={
          size === "lg"
            ? "text-[18px] font-bold leading-snug text-text-primary whitespace-nowrap"
            : "text-[14px] font-bold text-text-primary"
        }
      >
        {value}
      </span>
    </div>
  );
}

/** key→count 목록(상태 집계 공용). labeler로 한국어 라벨 변환. */
export function CountList({
  counts,
  empty,
  labeler,
}: {
  counts: Record<string, number>;
  empty: string;
  labeler?: (key: string) => string;
}) {
  const entries = Object.entries(counts);
  if (entries.length === 0) {
    return <EmptyState>{empty}</EmptyState>;
  }
  return (
    <div className="flex flex-col gap-1 rounded-lg border border-surface-muted p-2 text-[13px]">
      {entries.map(([key, value]) => (
        <div key={key} className="flex items-center justify-between gap-3 px-1 py-0.5">
          <span className="text-text-secondary">{labeler ? labeler(key) : key}</span>
          <span className="font-medium tabular-nums">{value.toLocaleString()}</span>
        </div>
      ))}
    </div>
  );
}

/** 비어 있음/로딩 안내 문단(공용). */
export function EmptyState({ children }: { children: ReactNode }) {
  return (
    <p className="rounded-lg border border-surface-muted bg-surface-subtle p-3 text-[13px] text-text-secondary">
      {children}
    </p>
  );
}
