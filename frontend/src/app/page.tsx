import { VWorldMap } from "@/components/VWorldMap";

// 메인 화면: 장소 리스트 + VWorld 지도 뷰 (스캐폴드).
// 리스트/마커/상세 패널 동기화와 검수 큐는 T-013에서 구현한다.
export default function HomePage() {
  return (
    <main className="flex h-screen">
      <section
        id="destination-list"
        className="w-1/3 overflow-y-auto border-r p-4"
      >
        <h1 className="text-lg font-semibold">TripMate Agent</h1>
        {/* T-013: 수집된 여행지 리스트 */}
      </section>
      <section className="w-2/3">
        <VWorldMap />
      </section>
    </main>
  );
}
