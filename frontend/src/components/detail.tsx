import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

// 장소/검수 후보 상세 화면 공용 조각(제목 섹션·라벨/값 행).

export function DetailSection({
  title,
  divided,
  children,
}: {
  title: string;
  /** true면 위 구분선(장소 상세 스타일) */
  divided?: boolean;
  children: ReactNode;
}) {
  return (
    <section className={cn("flex flex-col gap-1.5", divided && "border-t pt-3")}>
      <h4 className="text-xs font-semibold text-muted-foreground">{title}</h4>
      {children}
    </section>
  );
}

export function DetailRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3 text-sm">
      <span className="shrink-0 text-muted-foreground">{label}</span>
      <span className="truncate text-right font-medium">{value}</span>
    </div>
  );
}
