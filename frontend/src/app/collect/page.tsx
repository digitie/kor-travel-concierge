import { AppShell } from "@/components/AppShell";
import { CollectWorkspace } from "@/components/CollectWorkspace";

export default function CollectPage() {
  return (
    <AppShell
      title="수집"
      description="YouTube 검색어, 재생목록, 유튜버 입력을 수집 작업으로 등록합니다."
      section="수집"
      contentClassName="flex min-h-0 flex-1 p-0"
    >
      <CollectWorkspace />
    </AppShell>
  );
}
