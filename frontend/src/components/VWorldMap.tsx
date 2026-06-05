"use client";

// maplibre-vworld-js 지도 뷰 컴포넌트 (스캐폴드).
// 실제 지도 초기화(VWorld WMTS 레이어, 마커, 상세 패널 동기화)는 T-013에서 구현한다.
export function VWorldMap() {
  return (
    <div
      id="vworld-map-container"
      className="h-full w-full"
      data-status="scaffold"
    >
      {/* T-013: maplibre-vworld-js 지도 렌더링 위치 */}
    </div>
  );
}
