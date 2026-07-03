"use client";

import type { ReactNode } from "react";
import { CircleHelpIcon } from "lucide-react";

import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";

// 필드 옆 도움말 아이콘 버튼. 긴 설명은 화면 상시 노출 대신 여기로 옮긴다.
// hover 툴팁 대신 클릭 popover라 터치 기기에서도 동작한다.
export function HelpTip({
  children,
  label = "도움말",
}: {
  children: ReactNode;
  label?: string;
}) {
  return (
    <Popover>
      <PopoverTrigger
        render={
          <button
            type="button"
            aria-label={label}
            className="relative inline-flex size-5 shrink-0 items-center justify-center rounded-full text-text-tertiary transition-colors outline-none after:absolute after:-inset-2 hover:bg-surface-subtle hover:text-text-primary focus-visible:ring-3 focus-visible:ring-brand/20"
          >
            <CircleHelpIcon className="size-3.5" />
          </button>
        }
      />
      <PopoverContent
        side="top"
        className="w-auto max-w-72 text-[12px] leading-relaxed text-text-secondary"
      >
        {children}
      </PopoverContent>
    </Popover>
  );
}
