import * as React from "react";

import { cn } from "@/lib/utils";

// kor-travel-map admin frontend의 textarea primitive와 동일 — Input과 같은 토큰/포커스 규칙.
function Textarea({ className, ...props }: React.ComponentProps<"textarea">) {
  return (
    <textarea
      data-slot="textarea"
      className={cn(
        "min-h-24 w-full min-w-0 rounded-md border border-input bg-card px-3 py-2 text-[14px] transition-colors outline-none placeholder:text-text-tertiary focus-visible:border-brand focus-visible:ring-3 focus-visible:ring-brand/20 disabled:pointer-events-none disabled:cursor-not-allowed disabled:bg-surface-muted disabled:text-text-disabled aria-invalid:border-destructive aria-invalid:ring-3 aria-invalid:ring-destructive/20 dark:bg-card dark:disabled:bg-surface-muted dark:aria-invalid:border-destructive/50 dark:aria-invalid:ring-destructive/40",
        className,
      )}
      {...props}
    />
  );
}

export { Textarea };
