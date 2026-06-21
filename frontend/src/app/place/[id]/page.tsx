"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { ArrowLeftIcon } from "lucide-react";

import { AppNav } from "@/components/AppNav";
import { PlaceDetailView } from "@/components/PlaceDetailView";

export default function PlaceDetailPage() {
  const params = useParams<{ id: string }>();
  const id = Number(params.id);

  return (
    <main className="flex min-h-screen flex-col bg-background">
      <AppNav />
      <div className="mx-auto w-full max-w-2xl p-4">
        <Link
          href="/"
          className="inline-flex items-center gap-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground"
        >
          <ArrowLeftIcon className="size-4" />
          결과로
        </Link>
        <div className="mt-3 rounded-xl border p-4">
          {Number.isFinite(id) ? (
            <PlaceDetailView placeId={id} />
          ) : (
            <p className="text-sm text-destructive">잘못된 장소 ID</p>
          )}
        </div>
      </div>
    </main>
  );
}
