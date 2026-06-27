import * as React from "react"

import { cn } from "@/lib/utils"

const Input = React.forwardRef<HTMLInputElement, React.ComponentProps<"input">>(
  ({ className, type, ...props }, ref) => (
    <input
      ref={ref}
      type={type}
      data-slot="input"
      className={cn(
        "h-10 w-full min-w-0 rounded-md border border-input bg-card px-3 py-2 text-[14px] transition-colors outline-none file:inline-flex file:h-6 file:border-0 file:bg-transparent file:text-[13px] file:font-medium file:text-text-primary placeholder:text-text-tertiary focus-visible:border-brand focus-visible:ring-3 focus-visible:ring-brand/20 disabled:pointer-events-none disabled:cursor-not-allowed disabled:bg-surface-muted disabled:text-text-disabled aria-invalid:border-destructive aria-invalid:ring-3 aria-invalid:ring-destructive/20 dark:bg-card dark:disabled:bg-surface-muted dark:aria-invalid:border-destructive/50 dark:aria-invalid:ring-destructive/40",
        className
      )}
      {...props}
    />
  )
)

Input.displayName = "Input"

export { Input }
