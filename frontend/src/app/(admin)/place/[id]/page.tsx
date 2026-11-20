"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { ArrowLeftIcon } from "lucide-react";

import { PlaceDetailView } from "@/components/PlaceDetailView";

export default function PlaceDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const id = Number(params.id);

  return (
    <>
      <div className="ktc-workspace w-full max-w-3xl">
        <Link
          href="/"
          className="inline-flex items-center gap-1.5 text-sm font-bold text-text-secondary transition-colors hover:text-brand"
        >
          <ArrowLeftIcon className="size-4" />
          결과로
        </Link>
        <div className="mt-4 rounded-panel border border-border bg-card p-4">
          {Number.isFinite(id) ? (
            <PlaceDetailView placeId={id} onDeleted={() => router.push("/")} />
          ) : (
            <p className="text-sm text-destructive">잘못된 장소 ID</p>
          )}
        </div>
      </div>
    </>
  );
}
