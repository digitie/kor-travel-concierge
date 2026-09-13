"use client";

import dynamic from "next/dynamic";
import { useCallback, useMemo, useState } from "react";
import type { MapLibreMap, MarkerProps, PopupProps, VWorldMapViewProps } from "vworld-map-web";

import { type DestinationSummary, VWORLD_SERVICE_KEY } from "@/lib/api";

// vworld-map-web은 브라우저 전용(DOM/WebGL)이라 SSR을 끄고 동적 import한다.
// (kor-travel-map/pinvi의 vworld-map-web 소비 패턴과 동일. maplibre-gl CSS는
// app/globals.css가 이미 전역으로 import한다.)
const VWorldMapView = dynamic<VWorldMapViewProps>(
  () => import("vworld-map-web").then((mod) => mod.VWorldMapView),
  { ssr: false, loading: () => <MapLoadingSkeleton /> },
);
const Marker = dynamic<MarkerProps>(
  () => import("vworld-map-web").then((mod) => mod.Marker),
  { ssr: false },
);
const Popup = dynamic<PopupProps>(
  () => import("vworld-map-web").then((mod) => mod.Popup),
  { ssr: false },
);

type VWorldMapProps = {
  places: DestinationSummary[];
  selectedPlaceId: number | null;
  onSelectPlace: (placeId: number) => void;
  focusKey?: number;
};

type VisiblePlace = {
  place: DestinationSummary;
  // 1-based 목록 행 번호(places 배열 index + 1)와 동기화한 마커 번호.
  number: number;
  lngLat: [number, number];
};

type CameraTarget = { center: [number, number]; zoom: number };

const KOREA_CENTER: [number, number] = [127.8, 36.4];
const KOREA_MAX_BOUNDS: [[number, number], [number, number]] = [
  [123.0, 31.0],
  [133.5, 40.8],
];
const INITIAL_ZOOM = 6.2;
const VWORLD_MIN_ZOOM = 6;
const FOCUS_ZOOM = 12;
// VWorldMapView는 apiKey가 비어 있으면 지도/마커/팝업을 전혀 마운트하지 않고
// fallback만 렌더한다(vworld-map-web의 설계). 키가 없는 개발 환경에서도 목록·마커
// 클릭 UX는 그대로 동작해야 하므로(E2E도 이를 전제), 더미 키로 지도는 항상 띄우고
// 실제 키 부재는 별도 오버레이 배지로 알린다. 더미 키의 VWorld 타일 요청은
// unsupportedTileFallback으로 우아하게 대체된다.
const KEYLESS_PLACEHOLDER_KEY = "keyless-dev-placeholder";

export function VWorldMap({
  places,
  selectedPlaceId,
  onSelectPlace,
  focusKey = 0,
}: VWorldMapProps) {
  // react-hooks/refs: ref는 렌더 중 읽을 수 없으므로(값은 커밋 이후에만 접근),
  // cameraTarget 계산에 쓰이는 두 값은 ref 대신 state로 추적한다. zoomend/moveend는
  // 제스처가 끝날 때만 발생해(연속 프레임이 아님) 리렌더 비용이 문제되지 않는다.
  const [currentZoom, setCurrentZoom] = useState(INITIAL_ZOOM);
  // 선택 해제 시 카메라를 국가 전체 뷰로 되돌리지 않고 마지막 초점을 유지하기 위한
  // state. cameraTarget이 undefined가 되면 vworld-map-web은 이를 base center/zoom
  // props로 취급해 그쪽으로 다시 easeTo한다(선택 해제 = 예상치 못한 카메라 이동).
  const [lastCameraTarget, setLastCameraTarget] = useState<CameraTarget | undefined>(undefined);
  // 선택 대상이 "새로" 바뀐(장소·focusKey·좌표 중 하나라도 달라진) 시점에만 그
  // 순간의 줌을 한 번 캡처해 카메라를 고정한다. pinnedSignature가 같으면 더 이상
  // 재계산하지 않는다 — 예전엔 activeCameraTarget이 currentZoom에 계속 의존해
  // 지도의 모든 zoomend/moveend마다 다시 계산됐고, Math.max(currentZoom, FOCUS_ZOOM)가
  // 매번 재적용돼 선택된 장소가 있는 동안 FOCUS_ZOOM 아래로 축소하면 지도가 즉시
  // 다시 튕겨 올라왔다(사용자가 지도에서 직접 줌을 바꿀 수 없었던 원인). focusKey는
  // 목록 재클릭(DestinationWorkspace)을, 좌표 자체는 focusKey 없이 좌표만 바뀌는
  // 소비처(ReviewWorkspace — 폼에서 좌표를 고치는 동안 selectedPlaceId는 고정 sentinel)를
  // 함께 커버한다. 렌더 중 조건부 setState(React가 명시적으로 허용하는 "파생 state
  // 조정" 패턴)로 갱신해 useEffect의 추가 렌더 cascade를 피한다.
  const [pinnedSignature, setPinnedSignature] = useState<string | undefined>(undefined);
  const [pinnedFocusTarget, setPinnedFocusTarget] = useState<CameraTarget | undefined>(undefined);

  const visiblePlaces = useMemo<VisiblePlace[]>(
    () =>
      places
        .map((place, index) => ({
          place,
          number: index + 1,
          lngLat: getLngLat(place),
        }))
        .filter((entry): entry is VisiblePlace => entry.lngLat != null),
    [places],
  );

  const selectedPlaceCoordinates = useMemo(() => {
    if (selectedPlaceId == null) {
      return null;
    }
    const entry = visiblePlaces.find(({ place }) => place.place_id === selectedPlaceId);
    return entry ? { place: entry.place, lngLat: entry.lngLat } : null;
  }, [visiblePlaces, selectedPlaceId]);

  if (selectedPlaceCoordinates) {
    const signature = `${selectedPlaceId}:${focusKey}:${selectedPlaceCoordinates.lngLat[0]}:${selectedPlaceCoordinates.lngLat[1]}`;
    if (signature !== pinnedSignature) {
      setPinnedSignature(signature);
      // focusKey가 같은 장소로 다시 증가해도(재중심 요청) vworld-map-web의 값 기반
      // sameCamera 비교가 "동일 카메라"로 합쳐 애니메이션을 건너뛰지 않도록, 화면에
      // 보이지 않는 수준의 zoom 지터로 값을 구분한다.
      setPinnedFocusTarget({
        center: selectedPlaceCoordinates.lngLat,
        zoom: Math.max(currentZoom, FOCUS_ZOOM) + focusKey * 1e-9,
      });
    }
  }

  // 선택된 장소가 있는 동안에는 위에서 고정한 값만 쓴다(currentZoom을 계속
  // 따라가며 다시 계산하지 않음 — 그러면 사용자의 지도 줌 조작을 덮어쓴다).
  const activeCameraTarget = selectedPlaceCoordinates ? pinnedFocusTarget : undefined;

  if (activeCameraTarget && activeCameraTarget !== lastCameraTarget) {
    setLastCameraTarget(activeCameraTarget);
  }

  // 선택 해제 시 undefined 대신 마지막 초점을 그대로 반환해 카메라를 제자리에 둔다.
  const cameraTarget = activeCameraTarget ?? lastCameraTarget;

  const handleCameraTrackingEvent = useCallback((event: { target: MapLibreMap }) => {
    setCurrentZoom(event.target.getZoom());
  }, []);

  return (
    <div
      id="vworld-map-container"
      role="region"
      aria-label="VWorld 지도"
      data-status={VWORLD_SERVICE_KEY ? "vworld" : "fallback"}
      className="relative h-full w-full"
    >
      <VWorldMapView
        apiKey={VWORLD_SERVICE_KEY || KEYLESS_PLACEHOLDER_KEY}
        layerType="Base"
        center={KOREA_CENTER}
        zoom={INITIAL_ZOOM}
        minZoom={VWORLD_MIN_ZOOM}
        maxBounds={KOREA_MAX_BOUNDS}
        navigation
        geolocate={false}
        scale={false}
        cameraTarget={cameraTarget}
        onZoomEnd={handleCameraTrackingEvent}
        onMoveEnd={handleCameraTrackingEvent}
        fallback={<MapFallback />}
        loadingSkeleton={<MapLoadingSkeleton />}
        unsupportedTileFallback={{ label: "VWorld 타일" }}
        className="h-full w-full"
      >
        {visiblePlaces.map(({ place, number, lngLat }) => (
          <Marker
            key={place.place_id}
            lngLat={lngLat}
            anchor="bottom"
            selected={place.place_id === selectedPlaceId}
            ariaLabel={`${number}번 ${place.name} 선택`}
            interactionId={String(number)}
            onClick={() => onSelectPlace(place.place_id)}
          >
            <MarkerBadge number={number} selected={place.place_id === selectedPlaceId} />
          </Marker>
        ))}
        {selectedPlaceCoordinates ? (
          <Popup
            lngLat={selectedPlaceCoordinates.lngLat}
            offset={18}
            closeButton={false}
            closeOnClick={false}
          >
            <strong>{selectedPlaceCoordinates.place.name}</strong>
          </Popup>
        ) : null}
      </VWorldMapView>
      {!VWORLD_SERVICE_KEY ? (
        <div className="pointer-events-none absolute inset-0 grid place-items-center bg-muted/70 text-sm text-muted-foreground">
          VWorld 지도 키 없음
        </div>
      ) : null}
    </div>
  );
}

function MapLoadingSkeleton() {
  return (
    <div className="absolute inset-0 grid place-items-center bg-muted text-sm text-muted-foreground">
      지도 로딩 중
    </div>
  );
}

function MapFallback() {
  // apiKey는 항상 비어 있지 않은 값(실제 키 또는 KEYLESS_PLACEHOLDER_KEY)을 전달하므로
  // 이 fallback은 실질적으로 "map-init-error"(WebGL 등 초기화 실패)에서만 나타난다.
  return (
    <div className="grid h-full w-full place-items-center bg-muted text-sm text-muted-foreground">
      지도를 불러오지 못했습니다
    </div>
  );
}

function MarkerBadge({ number, selected }: { number: number; selected: boolean }) {
  return (
    <span
      style={{
        width: selected ? "28px" : "22px",
        height: selected ? "28px" : "22px",
        boxSizing: "border-box",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        borderRadius: "9999px",
        border: "2px solid #ffffff",
        fontFamily:
          "var(--font-sans, Pretendard), Pretendard, 'Noto Sans KR', 'Apple SD Gothic Neo', 'Malgun Gothic', sans-serif",
        fontSize: selected ? "13px" : "11px",
        fontWeight: 700,
        lineHeight: 1,
        color: "#ffffff",
        cursor: "pointer",
        backgroundColor: selected ? "var(--brand)" : "var(--text-secondary)",
        boxShadow: selected
          ? "0 0 0 3px rgba(47, 118, 95, 0.24), 0 8px 18px rgba(60, 63, 61, 0.22)"
          : "0 6px 14px rgba(60, 63, 61, 0.18)",
        transform: selected ? "translateY(-2px)" : "translateY(0)",
        transition:
          "background-color 150ms ease, transform 150ms ease, box-shadow 150ms ease, width 150ms ease, height 150ms ease",
      }}
    >
      {number}
    </span>
  );
}

function getLngLat(place: DestinationSummary): [number, number] | null {
  const latitude = Number(place.latitude);
  const longitude = Number(place.longitude);
  if (
    !Number.isFinite(latitude) ||
    !Number.isFinite(longitude) ||
    latitude < -90 ||
    latitude > 90 ||
    longitude < -180 ||
    longitude > 180
  ) {
    return null;
  }
  return [longitude, latitude];
}
