import { mergeProps } from "@base-ui/react/merge-props"
import { useRender } from "@base-ui/react/use-render"
import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "@/lib/utils"

const badgeVariants = cva(
  "group/badge inline-flex h-6 w-fit shrink-0 items-center justify-center gap-1 overflow-hidden rounded-md border border-transparent px-2 py-0.5 text-[12px] font-bold tracking-[0.05em] whitespace-nowrap uppercase transition-colors focus-visible:border-brand focus-visible:ring-[3px] focus-visible:ring-brand/20 has-data-[icon=inline-end]:pr-1.5 has-data-[icon=inline-start]:pl-1.5 aria-invalid:border-destructive aria-invalid:ring-destructive/20 dark:aria-invalid:ring-destructive/40 [&>svg]:pointer-events-none [&>svg]:!size-3",
  {
    variants: {
      variant: {
        default: "bg-brand text-brand-foreground [&>a]:hover:bg-brand/90",
        secondary:
          "bg-brand-tint text-brand [&>a]:hover:bg-brand-tint/80",
        destructive:
          "bg-destructive/10 text-destructive focus-visible:ring-destructive/20 dark:bg-destructive/20 dark:focus-visible:ring-destructive/40 [&>a]:hover:bg-destructive/20",
        outline:
          "border-border bg-card text-text-secondary [&>a]:hover:bg-surface-subtle [&>a]:hover:text-text-primary",
        ghost:
          "text-text-secondary hover:bg-surface-subtle hover:text-text-primary",
        link: "text-brand underline-offset-4 hover:underline",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
)

function Badge({
  className,
  variant = "default",
  render,
  ...props
}: useRender.ComponentProps<"span"> & VariantProps<typeof badgeVariants>) {
  return useRender({
    defaultTagName: "span",
    props: mergeProps<"span">(
      {
        className: cn(badgeVariants({ variant }), className),
      },
      props
    ),
    render,
    state: {
      slot: "badge",
      variant,
    },
  })
}

export { Badge, badgeVariants }
