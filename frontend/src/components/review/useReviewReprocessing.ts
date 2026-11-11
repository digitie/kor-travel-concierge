"use client";

import type { ReprocessStage } from "@/lib/api";
import { reprocessVideos, RUN_QUEUE_QUERY_KEY } from "@/lib/api";
import { usePersistedState } from "@/lib/use-persisted-state";
import type { QueryClient } from "@tanstack/react-query";
import { useMutation } from "@tanstack/react-query";
import { useCallback, useMemo, useState } from "react";

export function useReviewReprocessing({
  queryClient,
}: {
  queryClient: QueryClient;
}) {
  const [cart, setCart] = usePersistedState<string[]>("ktc.review.cart", []);
  const [reprocessStage, setReprocessStage] =
    useState<ReprocessStage>("transcript");
  const cartSet = useMemo(() => new Set(cart), [cart]);
  const toggleCart = useCallback(
    (videoId: string) => {
      setCart((prev) =>
        prev.includes(videoId)
          ? prev.filter((v) => v !== videoId)
          : [...prev, videoId],
      );
    },
    [setCart],
  );
  const reprocessMutation = useMutation({
    mutationFn: () => reprocessVideos(cart, reprocessStage),
    onSuccess: () => {
      setCart([]);
      queryClient.invalidateQueries({ queryKey: RUN_QUEUE_QUERY_KEY });
    },
  });
  return {
    cart,
    setCart,
    reprocessStage,
    setReprocessStage,
    cartSet,
    toggleCart,
    reprocessMutation,
  };
}
