"use client";

import * as React from "react";
import { NativeSelect, NativeSelectOption } from "@kor-travel/ui/native-select";
import {
  Select as CommonSelect,
  SelectItem as CommonSelectItem,
  SelectTrigger as CommonSelectTrigger,
} from "@kor-travel/ui/select";
export {
  SelectContent,
  SelectGroup,
  SelectLabel,
  SelectScrollDownButton,
  SelectScrollUpButton,
  SelectSeparator,
  SelectValue,
} from "@kor-travel/ui/select";

// Radix가 예약한 빈 문자열을 기존 필터의 전체/없음 값과 구분한다.
const EMPTY_VALUE = "__concierge_empty_option__";
export function SelectItem({
  value,
  ...props
}: React.ComponentProps<typeof CommonSelectItem>) {
  return (
    <CommonSelectItem value={value === "" ? EMPTY_VALUE : value} {...props} />
  );
}
export const SelectTrigger = CommonSelectTrigger;

type NativeItem = { value: string; label: React.ReactNode; disabled?: boolean };
function collectItems(children: React.ReactNode, items: NativeItem[] = []) {
  React.Children.forEach(children, (child) => {
    if (!React.isValidElement(child)) return;
    const props = child.props as {
      value?: string;
      children?: React.ReactNode;
      disabled?: boolean;
    };
    if (child.type === SelectItem)
      items.push({
        value: props.value ?? "",
        label: props.children,
        disabled: props.disabled,
      });
    else if (props.children) collectItems(props.children, items);
  });
  return items;
}
function triggerProps(
  children: React.ReactNode,
): React.ComponentProps<typeof CommonSelectTrigger> | undefined {
  let result: React.ComponentProps<typeof CommonSelectTrigger> | undefined;
  React.Children.forEach(children, (child) => {
    if (!React.isValidElement(child)) return;
    const props = child.props as React.ComponentProps<
      typeof CommonSelectTrigger
    >;
    if (child.type === SelectTrigger) result = props;
    else if (props.children) result ??= triggerProps(props.children);
  });
  return result;
}
/** 터치 환경은 기존 OS picker, 데스크톱은 공통 Radix 프리미티브를 사용한다. */
export function Select({
  value,
  defaultValue,
  onValueChange,
  children,
  disabled,
  ...props
}: React.ComponentProps<typeof CommonSelect>) {
  const [coarse, setCoarse] = React.useState(false);
  React.useEffect(() => {
    const query = window.matchMedia?.("(pointer: coarse)");
    if (!query) return;
    const update = () => setCoarse(query.matches);
    update();
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);
  const items = collectItems(children);
  const encode = (next: string | undefined) =>
    next === "" && items.some((item) => item.value === "") ? EMPTY_VALUE : next;
  if (coarse && value !== undefined && onValueChange && items.length) {
    const trigger = triggerProps(children);
    return (
      <NativeSelect
        data-slot="select-native"
        value={value}
        disabled={disabled ?? trigger?.disabled}
        name={props.name}
        required={props.required}
        form={props.form}
        dir={props.dir}
        id={trigger?.id}
        size={trigger?.size}
        aria-label={trigger?.["aria-label"]}
        aria-labelledby={trigger?.["aria-labelledby"]}
        aria-invalid={trigger?.["aria-invalid"]}
        className={trigger?.className ?? "w-full"}
        onChange={(event) => onValueChange(event.currentTarget.value)}
      >
        {items.map((item) => (
          <NativeSelectOption
            key={item.value}
            value={item.value}
            disabled={item.disabled}
          >
            {item.label}
          </NativeSelectOption>
        ))}
      </NativeSelect>
    );
  }
  return (
    <CommonSelect
      {...props}
      disabled={disabled}
      value={encode(value)}
      defaultValue={encode(defaultValue)}
      onValueChange={(next) =>
        onValueChange?.(next === EMPTY_VALUE ? "" : next)
      }
    >
      {children}
    </CommonSelect>
  );
}
