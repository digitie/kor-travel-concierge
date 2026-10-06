"use client";
import { useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { LoginForm as CommonLoginForm, type LoginSubmission } from "@kor-travel/ui/login-form";
import { sanitizeLocalPath } from "@kor-travel/ui/navigation";

const ERROR_MESSAGES: Record<string, string> = {
  AUTH_MISCONFIGURED: "관리자 인증 설정이 아직 준비되지 않았습니다.",
  INVALID_CREDENTIALS: "아이디 또는 비밀번호를 확인하세요.",
  INVALID_JSON: "요청 형식이 올바르지 않습니다.",
  INVALID_ORIGIN: "허용되지 않은 요청 출처입니다.",
  RATE_LIMITED: "로그인 시도가 잠시 제한되었습니다. 잠시 뒤 다시 시도하세요.",
};

export function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  async function submit({ credentials, nextPath }: LoginSubmission) {
    setError(null);
    try {
      const response = await fetch("/api/auth/login", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...credentials, next: nextPath }),
        signal: AbortSignal.timeout(10_000),
      });
      const payload = (await response.json().catch(() => ({}))) as { error?: string; next?: string };
      if (!response.ok) {
        setError(ERROR_MESSAGES[payload.error ?? ""] ?? "로그인하지 못했습니다.");
        return;
      }
      queryClient.clear();
      router.replace(sanitizeLocalPath(payload.next ?? nextPath));
      router.refresh();
    } catch {
      setError("네트워크 오류로 로그인하지 못했습니다. 잠시 뒤 다시 시도하세요.");
    }
  }
  return <section data-kt-surface className="w-full max-w-sm">
    <h1 className="sr-only">관리자 로그인</h1>
    <CommonLoginForm brand="Travel Concierge" description="내부 전용 관리자 콘솔"
      defaultUsername="admin" nextPath={searchParams.get("next") ?? "/"}
      onSubmit={submit} error={error} onClearError={() => setError(null)}
      testId="concierge-common-login" footer={<p>Travel Concierge Admin UI · 내부 전용 콘솔</p>} />
  </section>;
}
