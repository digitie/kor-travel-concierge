"use client";

import { FormEvent, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Loader2Icon, LogInIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Field, FieldDescription, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";

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
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setError(null);
    const next = searchParams.get("next") ?? "/";
    try {
      const response = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password, next }),
      });
      const payload = (await response.json().catch(() => ({}))) as {
        error?: string;
        next?: string;
      };
      if (!response.ok) {
        setError(ERROR_MESSAGES[payload.error ?? ""] ?? "로그인하지 못했습니다.");
        return;
      }
      router.replace(payload.next ?? "/");
      router.refresh();
    } catch {
      setError("네트워크 오류로 로그인하지 못했습니다. 잠시 뒤 다시 시도하세요.");
    } finally {
      setPending(false);
    }
  }

  return (
    <form
      onSubmit={onSubmit}
      className="flex w-full max-w-sm flex-col gap-5 rounded-lg border bg-background p-6 shadow-card"
    >
      <div className="flex flex-col gap-1">
        <h1 className="text-xl font-semibold tracking-tight">관리자 로그인</h1>
        <p className="text-sm text-muted-foreground">Kor Travel Concierge</p>
      </div>

      <Field>
        <FieldLabel htmlFor="login-username">아이디</FieldLabel>
        <Input
          id="login-username"
          autoComplete="username"
          value={username}
          onChange={(event) => setUsername(event.target.value)}
        />
      </Field>

      <Field>
        <FieldLabel htmlFor="login-password">비밀번호</FieldLabel>
        <Input
          id="login-password"
          type="password"
          autoComplete="current-password"
          autoFocus
          aria-describedby={error ? "login-error" : undefined}
          aria-invalid={Boolean(error)}
          value={password}
          onChange={(event) => setPassword(event.target.value)}
        />
        {error ? (
          <FieldDescription
            id="login-error"
            role="alert"
            aria-live="polite"
            className="text-destructive"
          >
            {error}
          </FieldDescription>
        ) : null}
      </Field>

      <Button type="submit" disabled={pending}>
        {pending ? (
          <Loader2Icon data-icon="inline-start" className="animate-spin" />
        ) : (
          <LogInIcon data-icon="inline-start" />
        )}
        로그인
      </Button>
    </form>
  );
}
