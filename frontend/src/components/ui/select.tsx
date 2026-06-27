"use client"

import * as React from "react"
import { Select as SelectPrimitive } from "@base-ui/react/select"

import { cn } from "@/lib/utils"
import { ChevronDownIcon, CheckIcon, ChevronUpIcon } from "lucide-react"

const selectTriggerBaseClassName =
  "flex w-fit items-center justify-between gap-1.5 rounded-lg border border-input bg-transparent py-2 pr-2 pl-2.5 text-sm whitespace-nowrap transition-colors outline-none select-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50 aria-invalid:border-destructive aria-invalid:ring-3 aria-invalid:ring-destructive/20 data-[placeholder]:text-muted-foreground data-[size=default]:h-8 data-[size=sm]:h-7 data-[size=sm]:rounded-[min(var(--radius-md),10px)] [&>[data-slot=select-value]]:line-clamp-1 [&>[data-slot=select-value]]:flex [&>[data-slot=select-value]]:items-center [&>[data-slot=select-value]]:gap-1.5 dark:bg-input/30 dark:hover:bg-input/50 dark:aria-invalid:border-destructive/50 dark:aria-invalid:ring-destructive/40 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4"

// 터치(coarse pointer) 기기 여부. SSR/첫 렌더는 false(데스크톱 Base UI)로 두고,
// 마운트 후 갱신해 hydration 불일치를 피한다.
function useCoarsePointer() {
  const [coarse, setCoarse] = React.useState(false)
  React.useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return
    const mq = window.matchMedia("(pointer: coarse)")
    const update = () => setCoarse(mq.matches)
    update()
    mq.addEventListener?.("change", update)
    return () => mq.removeEventListener?.("change", update)
  }, [])
  return coarse
}

type NativeItem = { value: string; label: React.ReactNode; disabled?: boolean }

// Select 자식 트리에서 SelectItem(값·라벨)을 재귀 수집한다.
function collectNativeItems(
  children: React.ReactNode,
  acc: NativeItem[] = []
): NativeItem[] {
  React.Children.forEach(children, (child) => {
    if (!React.isValidElement(child)) return
    const props = child.props as Record<string, unknown>
    if (child.type === SelectItem) {
      acc.push({
        value: String(props.value ?? ""),
        label: props.children as React.ReactNode,
        disabled: Boolean(props.disabled),
      })
    } else if (props.children) {
      collectNativeItems(props.children as React.ReactNode, acc)
    }
  })
  return acc
}

// 호출부 SelectTrigger의 className/aria-invalid를 native select에 그대로 전달하기 위해 추출한다.
function findTriggerProps(
  children: React.ReactNode
): { className?: string; "aria-invalid"?: boolean } {
  let found: { className?: string; "aria-invalid"?: boolean } = {}
  React.Children.forEach(children, (child) => {
    if (!React.isValidElement(child) || found.className !== undefined) return
    const props = child.props as Record<string, unknown>
    if (child.type === SelectTrigger) {
      found = {
        className: (props.className as string) ?? "",
        "aria-invalid": Boolean(props["aria-invalid"]),
      }
    } else if (props.children) {
      const nested = findTriggerProps(props.children as React.ReactNode)
      if (nested.className !== undefined) found = nested
    }
  })
  return found
}

// 모바일/터치 fallback: OS 네이티브 picker라 Samsung Internet 등 모든 모바일 브라우저에서 동작한다.
function NativeSelect({
  value,
  onValueChange,
  items,
  triggerClassName,
  ariaInvalid,
  disabled,
}: {
  value: string
  onValueChange: (value: string) => void
  items: NativeItem[]
  triggerClassName?: string
  ariaInvalid?: boolean
  disabled?: boolean
}) {
  return (
    <div className={cn("relative w-full", triggerClassName)}>
      <select
        data-slot="select-native"
        value={value}
        disabled={disabled}
        aria-invalid={ariaInvalid}
        onChange={(event) => onValueChange(event.currentTarget.value)}
        className={cn(
          selectTriggerBaseClassName,
          "w-full cursor-pointer appearance-none bg-transparent pr-9"
        )}
      >
        {items.map((item) => (
          <option key={item.value} value={item.value} disabled={item.disabled}>
            {item.label}
          </option>
        ))}
      </select>
      <ChevronDownIcon className="pointer-events-none absolute top-1/2 right-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
    </div>
  )
}

// 데스크톱(fine pointer)은 Base UI Select, 터치 기기는 native <select>로 렌더링한다.
// 제네릭을 유지해 호출부의 value 타입 추론(onValueChange 파라미터)을 보존한다.
function Select<Value>(props: SelectPrimitive.Root.Props<Value>) {
  const coarse = useCoarsePointer()
  const { value, onValueChange, children, disabled } = props
  if (
    coarse &&
    value !== undefined &&
    !Array.isArray(value) &&
    typeof onValueChange === "function"
  ) {
    const items = collectNativeItems(children)
    if (items.length > 0) {
      const trigger = findTriggerProps(children)
      const emit = onValueChange as unknown as (next: string) => void
      return (
        <NativeSelect
          value={String(value)}
          onValueChange={(next) => emit(next)}
          items={items}
          triggerClassName={trigger.className}
          ariaInvalid={trigger["aria-invalid"]}
          disabled={Boolean(disabled)}
        />
      )
    }
  }
  return <SelectPrimitive.Root {...props} />
}

function SelectGroup({ className, ...props }: SelectPrimitive.Group.Props) {
  return (
    <SelectPrimitive.Group
      data-slot="select-group"
      className={cn("scroll-my-1 p-1", className)}
      {...props}
    />
  )
}

function SelectValue({ className, ...props }: SelectPrimitive.Value.Props) {
  return (
    <SelectPrimitive.Value
      data-slot="select-value"
      className={cn("flex flex-1 text-left", className)}
      {...props}
    />
  )
}

function SelectTrigger({
  className,
  size = "default",
  children,
  ...props
}: SelectPrimitive.Trigger.Props & {
  size?: "sm" | "default"
}) {
  return (
    <SelectPrimitive.Trigger
      data-slot="select-trigger"
      data-size={size}
      className={cn(selectTriggerBaseClassName, className)}
      {...props}
    >
      {children}
      <SelectPrimitive.Icon
        render={
          <ChevronDownIcon className="pointer-events-none size-4 text-muted-foreground" />
        }
      />
    </SelectPrimitive.Trigger>
  )
}

function SelectContent({
  className,
  children,
  side = "bottom",
  sideOffset = 4,
  align = "center",
  alignOffset = 0,
  alignItemWithTrigger = true,
  ...props
}: SelectPrimitive.Popup.Props &
  Pick<
    SelectPrimitive.Positioner.Props,
    "align" | "alignOffset" | "side" | "sideOffset" | "alignItemWithTrigger"
  >) {
  return (
    <SelectPrimitive.Portal>
      <SelectPrimitive.Positioner
        side={side}
        sideOffset={sideOffset}
        align={align}
        alignOffset={alignOffset}
        alignItemWithTrigger={alignItemWithTrigger}
        className="isolate z-50"
      >
        <SelectPrimitive.Popup
          data-slot="select-content"
          data-align-trigger={alignItemWithTrigger}
          className={cn(
            "relative isolate z-50 max-h-[var(--available-height)] w-[var(--anchor-width)] min-w-36 origin-[var(--transform-origin)] overflow-x-hidden overflow-y-auto rounded-lg bg-popover text-popover-foreground shadow-md ring-1 ring-foreground/10 duration-100 data-[align-trigger=true]:animate-none data-[side=bottom]:slide-in-from-top-2 data-[side=inline-end]:slide-in-from-left-2 data-[side=inline-start]:slide-in-from-right-2 data-[side=left]:slide-in-from-right-2 data-[side=right]:slide-in-from-left-2 data-[side=top]:slide-in-from-bottom-2 data-[closed]:animate-out data-[closed]:fade-out-0 data-[closed]:zoom-out-95 data-[open]:animate-in data-[open]:fade-in-0 data-[open]:zoom-in-95",
            className
          )}
          {...props}
        >
          <SelectScrollUpButton />
          <SelectPrimitive.List>{children}</SelectPrimitive.List>
          <SelectScrollDownButton />
        </SelectPrimitive.Popup>
      </SelectPrimitive.Positioner>
    </SelectPrimitive.Portal>
  )
}

function SelectLabel({
  className,
  ...props
}: SelectPrimitive.GroupLabel.Props) {
  return (
    <SelectPrimitive.GroupLabel
      data-slot="select-label"
      className={cn("px-1.5 py-1 text-xs text-muted-foreground", className)}
      {...props}
    />
  )
}

function SelectItem({
  className,
  children,
  ...props
}: SelectPrimitive.Item.Props) {
  return (
    <SelectPrimitive.Item
      data-slot="select-item"
      className={cn(
        "relative flex w-full cursor-default items-center gap-1.5 rounded-md py-1 pr-8 pl-1.5 text-sm outline-none select-none focus:bg-accent focus:text-accent-foreground data-[disabled]:pointer-events-none data-[disabled]:opacity-50 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4 [&>span:last-child]:flex [&>span:last-child]:items-center [&>span:last-child]:gap-2",
        className
      )}
      {...props}
    >
      <SelectPrimitive.ItemText className="flex flex-1 shrink-0 gap-2 whitespace-nowrap">
        {children}
      </SelectPrimitive.ItemText>
      <SelectPrimitive.ItemIndicator
        render={
          <span className="pointer-events-none absolute right-2 flex size-4 items-center justify-center" />
        }
      >
        <CheckIcon className="pointer-events-none" />
      </SelectPrimitive.ItemIndicator>
    </SelectPrimitive.Item>
  )
}

function SelectSeparator({
  className,
  ...props
}: SelectPrimitive.Separator.Props) {
  return (
    <SelectPrimitive.Separator
      data-slot="select-separator"
      className={cn("pointer-events-none -mx-1 my-1 h-px bg-border", className)}
      {...props}
    />
  )
}

function SelectScrollUpButton({
  className,
  ...props
}: React.ComponentProps<typeof SelectPrimitive.ScrollUpArrow>) {
  return (
    <SelectPrimitive.ScrollUpArrow
      data-slot="select-scroll-up-button"
      className={cn(
        "top-0 z-10 flex w-full cursor-default items-center justify-center bg-popover py-1 [&_svg:not([class*='size-'])]:size-4",
        className
      )}
      {...props}
    >
      <ChevronUpIcon
      />
    </SelectPrimitive.ScrollUpArrow>
  )
}

function SelectScrollDownButton({
  className,
  ...props
}: React.ComponentProps<typeof SelectPrimitive.ScrollDownArrow>) {
  return (
    <SelectPrimitive.ScrollDownArrow
      data-slot="select-scroll-down-button"
      className={cn(
        "bottom-0 z-10 flex w-full cursor-default items-center justify-center bg-popover py-1 [&_svg:not([class*='size-'])]:size-4",
        className
      )}
      {...props}
    >
      <ChevronDownIcon
      />
    </SelectPrimitive.ScrollDownArrow>
  )
}

export {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectScrollDownButton,
  SelectScrollUpButton,
  SelectSeparator,
  SelectTrigger,
  SelectValue,
}
