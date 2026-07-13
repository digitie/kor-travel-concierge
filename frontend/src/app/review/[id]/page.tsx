"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { ArrowLeftIcon } from "lucide-react";

import { AppShell } from "@/components/AppShell";
import { CandidateDetailView } from "@/components/CandidateDetailView";
import { parseReviewCandidateIdValue } from "@/lib/review-list-state";

export default function CandidateDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const id = parseReviewCandidateIdValue(params.id);

  return (
    <AppShell title="검수 후보 상세">
      <div className="mx-auto w-full max-w-2xl p-4">
        <Link
          href="/review"
          className="inline-flex items-center gap-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground"
        >
          <ArrowLeftIcon className="size-4" />
          검수 큐로
        </Link>
        <div className="mt-3 rounded-xl border p-4">
          {id != null ? (
            <CandidateDetailView
              candidateId={id}
              onDeleted={() => router.push("/review")}
            />
          ) : (
            <p role="alert" className="text-sm text-destructive">
              잘못된 후보 ID
            </p>
          )}
        </div>
      </div>
    </AppShell>
  );
}
