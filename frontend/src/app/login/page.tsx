import { Suspense } from "react";

import { sanitizeLocalPath } from "@kor-travel/ui/navigation";

import { LoginForm } from "@/components/LoginForm";

export default async function LoginPage({ searchParams }: { searchParams: Promise<{ next?: string | string[] }> }) {
  const query = await searchParams;
  const nextPath = sanitizeLocalPath(typeof query.next === "string" ? query.next : "/");
  return (
    <main className="relative grid min-h-dvh place-items-center overflow-hidden bg-surface-page px-4 py-10 before:absolute before:inset-x-0 before:top-0 before:h-2 before:bg-[var(--shell-rail)]">
      <Suspense fallback={null}>
        <LoginForm nextPath={nextPath} />
      </Suspense>
    </main>
  );
}
