"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { ArrowLeftIcon } from "lucide-react";

import { AppShell } from "@/components/AppShell";
import { CandidateDetailView } from "@/components/CandidateDetailView";

export default function CandidateDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const id = Number(params.id);

  return (
    <AppShell
      title="검수 후보 상세"
      description="후보 장소의 출처 영상, 근거 문장, 같은 영상의 다른 장소를 확인합니다."
      section="검수"
    >
      <div className="mx-auto w-full max-w-2xl p-4">
        <Link
          href="/review"
          className="inline-flex items-center gap-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground"
        >
          <ArrowLeftIcon className="size-4" />
          검수 큐로
        </Link>
        <div className="mt-3 rounded-xl border p-4">
          {Number.isFinite(id) ? (
            <CandidateDetailView
              candidateId={id}
              onDeleted={() => router.push("/review")}
            />
          ) : (
            <p className="text-sm text-destructive">잘못된 후보 ID</p>
          )}
        </div>
      </div>
    </AppShell>
  );
}
