import { AppShell } from "@/components/AppShell";
import { DestinationWorkspace } from "@/components/DestinationWorkspace";

export default function HomePage() {
  return (
    <AppShell
      title="결과"
      description="수집된 여행지와 출처 영상을 지도와 목록으로 확인합니다."
      section="여행지"
      contentClassName="flex min-h-0 flex-1 p-0"
      viewportLocked
    >
      <DestinationWorkspace />
    </AppShell>
  );
}
