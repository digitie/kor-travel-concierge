"use client";

import { ArrowLeft, RefreshCw } from "lucide-react";
import { useEffect } from "react";

import { Button } from "@/components/ui/button";
import {
  errorRecoveryMessage,
  errorReloadStorageKey,
  isLikelyRecoverableNextRuntimeError,
} from "@/lib/error-recovery";

type AppErrorPanelProps = {
  error: Error & { digest?: string };
  reset?: () => void;
  // standalone: global-error에서 bare html/body 안에 렌더될 때 전달한다. 패널은
  // 항상 스스로 중앙 정렬하므로 분기 렌더는 없지만, 공용 API로 prop을 유지한다.
  standalone?: boolean;
};

export function AppErrorPanel({ error, reset }: AppErrorPanelProps) {
  const recoverable = isLikelyRecoverableNextRuntimeError(error);
  const details = errorRecoveryMessage(error);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    if (!recoverable) {
      return;
    }
    const storageKey = errorReloadStorageKey(window.location.pathname);
    let alreadyReloaded = false;
    try {
      alreadyReloaded = window.sessionStorage.getItem(storageKey) === "1";
    } catch {
      alreadyReloaded = false;
    }
    if (alreadyReloaded) {
      return;
    }
    try {
      window.sessionStorage.setItem(storageKey, "1");
    } catch {
      // sessionStorage 접근 불가 시 자동 새로고침을 건너뛴다.
      return;
    }
    window.location.reload();
  }, [recoverable]);

  const retry = () => {
    if (typeof window !== "undefined") {
      try {
        window.sessionStorage.removeItem(errorReloadStorageKey(window.location.pathname));
      } catch {
        // sessionStorage 접근 불가는 무시한다.
      }
    }
    if (reset) {
      reset();
      return;
    }
    if (typeof window !== "undefined") {
      window.location.reload();
    }
  };

  const goBack = () => {
    if (typeof window === "undefined") {
      return;
    }
    if (window.history.length > 1) {
      window.history.back();
      return;
    }
    window.location.assign("/");
  };

  return (
    <div className="flex min-h-screen w-full items-center justify-center bg-surface-page p-6">
      <div className="w-full max-w-md rounded-lg border border-line bg-card p-6 shadow-card">
        <p className="text-xs font-semibold uppercase tracking-wide text-brand">
          UI RUNTIME ERROR
        </p>
        <h1 className="mt-2 text-lg font-semibold text-text-strong">
          페이지를 다시 불러오지 못했습니다
        </h1>
        <p className="mt-2 text-sm text-text-secondary">
          {recoverable
            ? "현재 탭의 화면 런타임 상태가 서버와 맞지 않아 새로고침이 필요합니다."
            : "현재 탭의 UI 상태가 서버와 맞지 않거나, 화면 렌더링 중 오류가 발생했습니다."}
        </p>
        <div className="mt-4 flex flex-wrap gap-2">
          <Button onClick={retry}>
            <RefreshCw />
            다시 시도
          </Button>
          <Button variant="outline" onClick={goBack}>
            <ArrowLeft />
            이전 화면
          </Button>
        </div>
        <details className="mt-4">
          <summary className="cursor-pointer text-xs text-text-secondary">오류 정보</summary>
          <pre className="mt-2 overflow-auto text-xs text-text-tertiary">
            {details || "no details"}
          </pre>
        </details>
      </div>
    </div>
  );
}

export default AppErrorPanel;
