"use client";

import { ReviewWorkspaceView } from "./ReviewWorkspaceView";
import { useReviewWorkspaceController } from "./useReviewWorkspaceController";

export function ReviewWorkspace() {
  const model = useReviewWorkspaceController();
  return <ReviewWorkspaceView {...model} />;
}
