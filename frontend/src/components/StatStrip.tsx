import type { ReactNode } from "react";
import Link from "next/link";

import { HelpTip } from "@/components/HelpTip";
import { cn } from "@/lib/utils";

type StatTone = "success" | "warning" | "destructive" | "info" | "neutral";

type StatStripItem = {
  key?: string;
  label: string;
  value: ReactNode | number | null | undefined;
  unit?: string;
  caption?: ReactNode;
  tone?: StatTone;
  href?: string;
  help?: ReactNode;
};

type StatStripProps = {
  items: StatStripItem[];
  isLoading?: boolean;
  size?: "default" | "lg";
  framed?: boolean;
  ariaLabel?: string;
  className?: string;
};

const TONE_DOT: Record<StatTone, string> = {
  success: "bg-success",
  warning: "bg-warning",
  destructive: "bg-destructive",
  info: "bg-info",
  neutral: "bg-text-tertiary",
};

function valueText(value: StatStripItem["value"], loading: boolean) {
  if (loading || value === null || value === undefined) return "—";
  if (typeof value === "number") return value.toLocaleString();
  return value;
}

// 아이콘 타일·그림자 대신 숫자와 hairline만으로 KPI를 표현한다.
function StatStrip({
  items,
  isLoading = false,
  size = "default",
  framed = false,
  ariaLabel,
  className,
}: StatStripProps) {
  return (
    <dl
      aria-busy={isLoading || undefined}
      aria-label={ariaLabel}
      className={cn(
        "grid grid-cols-[repeat(auto-fit,minmax(9rem,1fr))] gap-y-4 [&>*:not(:first-child)]:border-l [&>*:not(:first-child)]:border-border",
        framed && "rounded-panel border border-border bg-card px-2 py-4",
        className,
      )}
      data-slot="stat-strip"
    >
      {items.map((item) => {
        const loading = isLoading;
        const label = item.href ? (
          <Link
            className="rounded-control no-underline underline-offset-4 hover:text-text-primary hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus max-md:inline-flex max-md:items-center"
            href={item.href}
          >
            {item.label}
          </Link>
        ) : (
          item.label
        );
        const hasValue = !loading && item.value !== null && item.value !== undefined;
        return (
          <div
            className="flex min-w-0 flex-col gap-1 px-4 first:pl-0"
            key={item.key ?? item.label}
          >
            <dt className="flex items-center gap-1.5 text-xs font-medium text-text-secondary">
              {item.tone ? (
                <span
                  aria-hidden="true"
                  className={cn("size-1.5 shrink-0 rounded-full", TONE_DOT[item.tone])}
                />
              ) : null}
              <span className="min-w-0 break-words">{label}</span>
              {item.help ? <HelpTip label={item.label}>{item.help}</HelpTip> : null}
            </dt>
            <dd className="flex min-w-0 flex-col gap-1">
              <span
                aria-busy={loading || undefined}
                className={cn(
                  "flex min-w-0 flex-wrap items-baseline gap-x-1 font-semibold tabular-nums text-text-primary",
                  size === "lg" ? "text-2xl" : "text-lg",
                  loading && "text-text-tertiary",
                )}
              >
                {/* 핵심 숫자가 말줄임으로 사라지지 않도록 좁은 화면에서는 줄을 바꾼다. */}
                <span className="min-w-0 break-words">{valueText(item.value, loading)}</span>
                {item.unit && hasValue ? (
                  <span className="text-xs font-medium text-text-secondary">{item.unit}</span>
                ) : null}
              </span>
              {item.caption ? (
                <span className="text-2xs text-text-secondary">{item.caption}</span>
              ) : null}
            </dd>
          </div>
        );
      })}
    </dl>
  );
}

export { StatStrip };
export type { StatStripItem, StatStripProps };
