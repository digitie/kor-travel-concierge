"use client";

import { useState } from "react";
import { CheckIcon, CopyIcon } from "lucide-react";

import { Button } from "@/components/ui/button";

// 클립보드 복사 버튼(작업 로그·생성된 API 키 등 공용).
export function CopyButton({
  text,
  label = "복사",
  copiedLabel = "복사됨",
  size = "sm",
}: {
  text: string;
  label?: string;
  copiedLabel?: string;
  size?: "xs" | "sm";
}) {
  const [copied, setCopied] = useState(false);
  return (
    <Button
      type="button"
      size={size}
      variant="outline"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
          setCopied(true);
          window.setTimeout(() => setCopied(false), 1500);
        } catch {
          // 클립보드 권한이 막힌 환경에서는 조용히 무시한다.
        }
      }}
    >
      {copied ? (
        <CheckIcon data-icon="inline-start" />
      ) : (
        <CopyIcon data-icon="inline-start" />
      )}
      {copied ? copiedLabel : label}
    </Button>
  );
}
