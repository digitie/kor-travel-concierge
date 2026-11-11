"use client";

import dynamic from "next/dynamic";
import { useStore } from "zustand";
import { createMapCameraStore } from "@/lib/map-camera";
import { useCallback, useEffect, useLayoutEffect, useMemo, useState, type ReactNode } from "react";
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
const MAP_LOADING_TIMEOUT_MS = 15_000;

export function VWorldMap({
  places,
  selectedPlaceId,
  onSelectPlace,
  focusKey = 0,
}: VWorldMapProps) {
  const [mapAttempt, setMapAttempt] = useState(0);
  const retryMap = useCallback(() => setMapAttempt((attempt) => attempt + 1), []);
  const [camera] = useState(() => createMapCameraStore(INITIAL_ZOOM, FOCUS_ZOOM));
  // zoom만 바뀌면 이 구독 값은 그대로라 마커와 팝업을 다시 그리지 않는다.
  const cameraTarget = useStore(camera.store, (state) => state.target);

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

  useLayoutEffect(() => {
    if (selectedPlaceId != null && selectedPlaceCoordinates) {
      camera.focus(selectedPlaceId, focusKey, selectedPlaceCoordinates.lngLat);
    }
    // 선택 해제 시 이전 카메라 목표를 유지한다.
  }, [camera, focusKey, selectedPlaceCoordinates, selectedPlaceId]);

  const handleCameraTrackingEvent = useCallback((event: { target: MapLibreMap }) => {
    camera.trackZoom(event.target.getZoom());
  }, [camera]);

  return (
    <div
      id="vworld-map-container"
      role="region"
      aria-label="VWorld 지도"
      data-status={VWORLD_SERVICE_KEY ? "vworld" : "fallback"}
      className="relative h-full w-full"
    >
      <MapWebGLGuard key={mapAttempt} onRetry={retryMap}>
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
          fallback={<MapFallback onRetry={retryMap} />}
          loadingSkeleton={<MapLoadingSkeleton onRetry={retryMap} />}
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
      </MapWebGLGuard>
      {!VWORLD_SERVICE_KEY ? (
        <div className="pointer-events-none absolute inset-0 grid place-items-center bg-muted/70 text-sm text-muted-foreground">
          VWorld 지도 키 없음
        </div>
      ) : null}
    </div>
  );
}

function MapWebGLGuard({ children, onRetry }: { children: ReactNode; onRetry: () => void }) {
  const [status, setStatus] = useState<"checking" | "ready" | "unsupported" | "unreleasable">("checking");

  useEffect(() => {
    // MapLibre 6는 WebGL2 초기화 실패 때 throw 없이 미완성 Map을 반환한다.
    // 어댑터의 load/fallback 모두 발화하지 않는 경로를 지도 생성 전에 차단한다.
    const frame = window.requestAnimationFrame(() => {
      const canvas = document.createElement("canvas");
      canvas.width = canvas.height = 1;
      let allocated = false;
      let result: "ready" | "unsupported" | "unreleasable" = "unsupported";
      try {
        const context = canvas.getContext("webgl2", {
          alpha: true, depth: true, stencil: true, premultipliedAlpha: true,
          antialias: false, preserveDrawingBuffer: false,
          powerPreference: "high-performance", failIfMajorPerformanceCaveat: false,
          desynchronized: false,
        });
        if (context) {
          allocated = true;
          result = "unreleasable";
          const release = context.getExtension("WEBGL_lose_context");
          if (release) {
            release.loseContext();
            // 검사 context의 loss가 확인된 경우에만 실제 지도를 생성한다.
            // 해제가 불확실하면 재검사로 context를 추가 생성하지 않는다.
            if (context.isContextLost()) result = "ready";
          }
        }
      } catch {
        result = allocated ? "unreleasable" : "unsupported";
      }
      setStatus(result);
    });
    return () => window.cancelAnimationFrame(frame);
  }, []);

  if (status === "checking") return <MapLoadingSkeleton />;
  if (status === "unsupported") return <MapFallback onRetry={onRetry} />;
  if (status === "unreleasable") {
    return (
      <div className="absolute inset-0 grid place-items-center bg-muted px-4 text-center text-sm text-muted-foreground">
        <p role="alert">지도를 안전하게 초기화하지 못했습니다. 페이지를 새로고침하거나 다른 브라우저로 접속해 주세요.</p>
      </div>
    );
  }
  return children;
}

function MapLoadingSkeleton({ onRetry }: { onRetry?: () => void }) {
  const [timedOut, setTimedOut] = useState(false);

  useEffect(() => {
    // 타일 요청이 끝나지 않으면 MapLibre의 load 이벤트도 오지 않는다.
    // 자동 재시도 대신 운영자가 지도만 재생성하도록 하며, 준비되면 이 컴포넌트가
    // 사라져 타이머도 정리된다. 장소 목록·선택·카메라 목표는 상위에 보존한다.
    const timer = window.setTimeout(() => setTimedOut(true), MAP_LOADING_TIMEOUT_MS);
    return () => window.clearTimeout(timer);
  }, []);

  return (
    <div className="absolute inset-0 grid place-items-center bg-muted text-sm text-muted-foreground">
      <div className="grid justify-items-center gap-3 px-4 text-center">
        <p role="status">
          {timedOut ? "지도 응답이 지연되고 있습니다. 네트워크 연결을 확인해 주세요." : "지도 로딩 중"}
        </p>
        {timedOut && (onRetry ? <MapRetryButton onRetry={onRetry} /> : <p>페이지를 새로고침해 주세요.</p>)}
      </div>
    </div>
  );
}

function MapRetryButton({ onRetry }: { onRetry: () => void }) {
  return (
    <button
      type="button"
      onClick={onRetry}
      className="rounded-md border border-border bg-background px-4 py-2 text-foreground hover:bg-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
    >
      지도 다시 시도
    </button>
  );
}

function MapFallback({ onRetry }: { onRetry: () => void }) {
  // apiKey는 항상 비어 있지 않은 값이므로 WebGL 등 초기화 실패에서 나타난다.
  return (
    <div className="grid h-full w-full place-items-center bg-muted text-sm text-muted-foreground">
      <div className="grid justify-items-center gap-3 px-4 text-center">
        <p role="alert">지도를 불러오지 못했습니다. 브라우저의 그래픽 가속 설정을 확인해 주세요.</p>
        <MapRetryButton onRetry={onRetry} />
      </div>
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
