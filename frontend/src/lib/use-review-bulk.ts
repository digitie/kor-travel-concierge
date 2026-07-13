"use client";

import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";

import {
  ApiRequestError,
  executeReviewBulk,
  previewReviewBulk,
  type ReviewBulkAction,
  type ReviewBulkScope,
  type ReviewBulkScopeForAction,
} from "./api";
import {
  INITIAL_REVIEW_BULK_STATE,
  beginNextReviewBulkChunk,
  beginReviewBulkPreview,
  cancelReviewBulk,
  confirmReviewBulk,
  createReviewBulkDraft,
  expireReviewBulkConfirmation,
  failReviewBulkExecution,
  failReviewBulkPreview,
  receiveReviewBulkExecution,
  receiveReviewBulkPreview,
  resetReviewBulk,
  retryReviewBulk,
  reviewBulkConfirmationDelayMs,
  reviewBulkConfirmationRef,
  reviewBulkExecuteRef,
  reviewBulkExecuteRequest,
  reviewBulkPreviewRef,
  reviewBulkPreviewRequest,
  type ReviewBulkCompletedState,
  type ReviewBulkFailure,
  type ReviewBulkState,
} from "./review-bulk";

type UseReviewBulkOptions = {
  onSettled: (state: ReviewBulkCompletedState) => void | Promise<void>;
};

type RequestReviewBulkPreview = <Action extends ReviewBulkAction>(
  action: Action,
  scope: NoInfer<ReviewBulkScopeForAction<Action>>,
) => void;

function bulkFailure(error: unknown): ReviewBulkFailure {
  const status = error instanceof ApiRequestError ? error.status : null;
  const message =
    error instanceof Error
      ? error.message
      : "일괄 검수 요청 결과를 확인하지 못했습니다.";
  if (status === 410) return { kind: "expired", message };
  if (status === 409) return { kind: "stale_conflict", message };
  if (
    status == null ||
    status === 408 ||
    status === 425 ||
    status === 429 ||
    status >= 500
  ) {
    return { kind: "retryable", message };
  }
  return { kind: "fatal", message };
}

export function useReviewBulk({ onSettled }: UseReviewBulkOptions) {
  const [state, setState] = useState<ReviewBulkState>(
    INITIAL_REVIEW_BULK_STATE,
  );
  const stateRef = useRef<ReviewBulkState>(INITIAL_REVIEW_BULK_STATE);
  const [dialogOpen, setDialogOpen] = useState(false);
  const previewAbortRef = useRef<AbortController | null>(null);
  const drivePromiseRef = useRef<Promise<void> | null>(null);
  const onSettledRef = useRef(onSettled);

  // URL/list scope commit과 마지막 chunk 응답이 같은 frame에 겹쳐도 settlement가
  // 이전 render의 cache callback을 실행하지 않도록 paint 전 최신 callback을 publish한다.
  useLayoutEffect(() => {
    onSettledRef.current = onSettled;
  }, [onSettled]);

  useEffect(
    () => () => {
      previewAbortRef.current?.abort();
      previewAbortRef.current = null;
    },
    [],
  );

  const publish = useCallback(
    (update: (current: ReviewBulkState) => ReviewBulkState) => {
      const next = update(stateRef.current);
      stateRef.current = next;
      setState(next);
      return next;
    },
    [],
  );

  useEffect(() => {
    const ref = reviewBulkConfirmationRef(state);
    if (!ref) return;

    let timer: ReturnType<typeof setTimeout> | null = null;
    let disposed = false;
    const schedule = () => {
      if (disposed) return;
      const delay = reviewBulkConfirmationDelayMs(ref.expiresAt, Date.now());
      // 2099 같은 먼 mock 시각도 브라우저가 1ms로 overflow시키지 않는다.
      // 상한에 닿으면 callback에서 남은 시간을 다시 계산해 분할 예약한다.
      timer = setTimeout(() => {
        if (disposed) return;
        const firedAtMs = Date.now();
        if (reviewBulkConfirmationDelayMs(ref.expiresAt, firedAtMs) > 0) {
          schedule();
          return;
        }
        publish((current) =>
          expireReviewBulkConfirmation(current, ref, firedAtMs),
        );
      }, delay);
    };
    schedule();

    return () => {
      disposed = true;
      if (timer != null) clearTimeout(timer);
    };
  }, [publish, state]);

  const performPreview = useCallback(
    async (previewing: ReviewBulkState) => {
      const ref = reviewBulkPreviewRef(previewing);
      const request = reviewBulkPreviewRequest(previewing);
      if (!ref || !request) return;
      previewAbortRef.current?.abort();
      const controller = new AbortController();
      previewAbortRef.current = controller;
      try {
        const preview = await previewReviewBulk(request, controller.signal);
        publish((current) =>
          receiveReviewBulkPreview(current, ref, preview),
        );
      } catch (error) {
        if (!controller.signal.aborted) {
          publish((current) =>
            failReviewBulkPreview(current, ref, bulkFailure(error)),
          );
        }
      } finally {
        if (previewAbortRef.current === controller) {
          previewAbortRef.current = null;
        }
      }
    },
    [publish],
  );

  const drive = useCallback(() => {
    const start = (): Promise<void> => {
      if (drivePromiseRef.current) return drivePromiseRef.current;
      const promise = (async () => {
        while (true) {
          let current = stateRef.current;
          if (current.status !== "executing") return;
          if (current.request == null) {
            current = publish((value) =>
              beginNextReviewBulkChunk(value, crypto.randomUUID()),
            );
          }
          const ref = reviewBulkExecuteRef(current);
          const request = reviewBulkExecuteRequest(current);
          if (!ref || !request) return;
          try {
            const result = await executeReviewBulk(request);
            const next = publish((value) =>
              receiveReviewBulkExecution(value, ref, result),
            );
            if (next.status === "completed" || next.status === "partial") {
              await onSettledRef.current(next);
              return;
            }
            if (next.status !== "executing") return;
          } catch (error) {
            publish((value) =>
              failReviewBulkExecution(value, ref, bulkFailure(error)),
            );
            return;
          }
        }
      })();
      drivePromiseRef.current = promise;

      const releaseAndResumeCurrentGeneration = () => {
        if (drivePromiseRef.current !== promise) return;
        drivePromiseRef.current = null;
        // terminal publish 뒤 onSettled를 기다리는 동안 새 operation이 confirm될 수
        // 있다. old Promise를 놓은 직후 현재 executing 세대를 새 driver가 이어받는다.
        if (stateRef.current.status === "executing") void start();
      };
      void promise.then(
        releaseAndResumeCurrentGeneration,
        releaseAndResumeCurrentGeneration,
      );
      return promise;
    };

    return start();
  }, [publish]);

  const requestPreview = useCallback(
    ((action: ReviewBulkAction, scope: ReviewBulkScope) => {
      const draft = createReviewBulkDraft(action, scope);
      const next = publish((current) =>
        beginReviewBulkPreview(current, draft),
      );
      setDialogOpen(true);
      void performPreview(next);
    }) as RequestReviewBulkPreview,
    [performPreview, publish],
  );

  const confirm = useCallback(() => {
    const next = publish((current) =>
      confirmReviewBulk(current, crypto.randomUUID()),
    );
    if (next.status === "executing") void drive();
  }, [drive, publish]);

  const retry = useCallback(() => {
    const current = stateRef.current;
    // partial은 page가 current filter 또는 unresolved selection으로 새 draft를
    // 만들어야 한다. 성공 ID까지 든 옛 selection/filter를 여기서 재사용하지 않는다.
    if (current.status === "partial") return;
    if (current.status === "expired") {
      // 실행 도중 410은 일부 반영됐을 수 있으므로 old scope를 재사용하지 않는다.
      // 화면에서 token-free 요약을 확인한 뒤 목록 새로고침으로만 빠져나간다.
      if (current.progress != null) return;
      requestPreview(current.draft.action, current.draft.scope);
      return;
    }
    const next = publish((value) => retryReviewBulk(value));
    if (next.status === "previewing") {
      void performPreview(next);
    } else if (next.status === "executing") {
      void drive();
    }
  }, [drive, performPreview, publish, requestPreview]);

  const cancelUnconfirmed = useCallback(() => {
    const current = stateRef.current;
    if (
      current.status !== "previewing" &&
      current.status !== "confirm" &&
      !(current.status === "error" && current.phase === "preview") &&
      !(current.status === "expired" && current.progress == null)
    ) {
      return;
    }
    previewAbortRef.current?.abort();
    previewAbortRef.current = null;
    publish(cancelReviewBulk);
    setDialogOpen(false);
  }, [publish]);

  const reset = useCallback(() => {
    // terminal 결과를 닫을 때도 남은 operation 자료를 메모리에서 명시적으로 폐기한다.
    previewAbortRef.current?.abort();
    previewAbortRef.current = null;
    publish(resetReviewBulk);
    setDialogOpen(false);
  }, [publish]);

  return {
    state,
    dialogOpen,
    setDialogOpen,
    requestPreview,
    confirm,
    retry,
    cancelUnconfirmed,
    reset,
  };
}
