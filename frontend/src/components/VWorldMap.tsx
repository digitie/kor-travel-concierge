"use client";

import maplibregl, { type Map as MapLibreMap, type Marker } from "maplibre-gl";
import { useEffect, useMemo, useRef } from "react";

import { type DestinationSummary, VWORLD_SERVICE_KEY } from "@/lib/api";

type VWorldMapProps = {
  places: DestinationSummary[];
  selectedPlaceId: number | null;
  onSelectPlace: (placeId: number) => void;
};

type MarkerEntry = {
  marker: Marker;
  place: DestinationSummary;
  // 1-based 목록 행 번호(places 배열 index + 1)와 동기화한 마커 번호.
  number: number;
  onClick: () => void;
};

const KOREA_CENTER: [number, number] = [127.8, 36.4];
const KOREA_TILE_BOUNDS: [number, number, number, number] = [124.0, 32.0, 132.5, 39.8];
const KOREA_MAX_BOUNDS: [[number, number], [number, number]] = [
  [123.0, 31.0],
  [133.5, 40.8],
];
const VWORLD_MIN_ZOOM = 6;

export function VWorldMap({
  places,
  selectedPlaceId,
  onSelectPlace,
}: VWorldMapProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const markersRef = useRef<Map<number, MarkerEntry>>(new Map());
  const selectedPlaceCoordinates = useMemo(() => {
    if (selectedPlaceId == null) {
      return null;
    }
    const place = places.find((item) => item.place_id === selectedPlaceId);
    const lngLat = place ? getLngLat(place) : null;
    return lngLat ? { place, lngLat } : null;
  }, [places, selectedPlaceId]);

  useEffect(() => {
    if (!containerRef.current || mapRef.current) {
      return;
    }
    const markers = markersRef.current;
    mapRef.current = new maplibregl.Map({
      container: containerRef.current,
      style: buildVWorldStyle(VWORLD_SERVICE_KEY),
      center: KOREA_CENTER,
      zoom: 6.2,
      minZoom: VWORLD_MIN_ZOOM,
      maxBounds: KOREA_MAX_BOUNDS,
      attributionControl: false,
    });
    mapRef.current.addControl(new maplibregl.NavigationControl(), "top-right");
    return () => {
      markers.forEach((entry) => removeMarkerEntry(entry));
      markers.clear();
      mapRef.current?.remove();
      mapRef.current = null;
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) {
      return;
    }
    // 목록 행 번호(index + 1)를 좌표 유효성과 무관하게 보존한 뒤,
    // 지오코딩되고 좌표가 유효한 장소만 마커로 렌더한다. 표시 번호는 목록과 일치한다.
    const visiblePlaces = places
      .map((place, index) => ({
        place,
        number: index + 1,
        lngLat: getLngLat(place),
      }))
      .filter(
        (entry): entry is {
          place: DestinationSummary;
          number: number;
          lngLat: [number, number];
        } => entry.lngLat != null,
      );
    const visibleIds = new Set(visiblePlaces.map(({ place }) => place.place_id));

    markersRef.current.forEach((entry, placeId) => {
      if (!visibleIds.has(placeId)) {
        removeMarkerEntry(entry);
        markersRef.current.delete(placeId);
      }
    });

    visiblePlaces.forEach(({ place, number, lngLat }) => {
      const existing = markersRef.current.get(place.place_id);
      const onClick = () => onSelectPlace(place.place_id);
      if (existing) {
        const element = existing.marker.getElement();
        element.removeEventListener("click", existing.onClick);
        element.addEventListener("click", onClick);
        existing.marker.setLngLat(lngLat);
        existing.marker.setPopup(buildPopup(place));
        existing.place = place;
        existing.number = number;
        existing.onClick = onClick;
        syncMarkerElement(element, place, number, place.place_id === selectedPlaceId);
        return;
      }

      const element = document.createElement("button");
      element.type = "button";
      const marker = new maplibregl.Marker({ element, anchor: "bottom" })
        .setLngLat(lngLat)
        .setPopup(buildPopup(place))
        .addTo(map);
      element.addEventListener("click", onClick);
      syncMarkerElement(element, place, number, place.place_id === selectedPlaceId);
      markersRef.current.set(place.place_id, { marker, place, number, onClick });
    });
  }, [onSelectPlace, places, selectedPlaceId]);

  useEffect(() => {
    markersRef.current.forEach((entry) => {
      syncMarkerElement(
        entry.marker.getElement(),
        entry.place,
        entry.number,
        entry.place.place_id === selectedPlaceId,
      );
    });
  }, [selectedPlaceId]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) {
      return;
    }
    if (selectedPlaceCoordinates) {
      map.easeTo({
        center: selectedPlaceCoordinates.lngLat,
        zoom: Math.max(map.getZoom(), 12),
        duration: 500,
      });
    }
  }, [selectedPlaceCoordinates]);

  return (
    <div className="relative h-full w-full">
      <div
        id="vworld-map-container"
        ref={containerRef}
        role="region"
        aria-label="VWorld 지도"
        className="h-full w-full bg-muted"
        data-status={VWORLD_SERVICE_KEY ? "vworld" : "fallback"}
      />
      {!VWORLD_SERVICE_KEY ? (
        <div className="pointer-events-none absolute inset-0 grid place-items-center bg-muted/70 text-sm text-muted-foreground">
          VWorld 지도 키 없음
        </div>
      ) : null}
    </div>
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

function buildPopup(place: DestinationSummary): maplibregl.Popup {
  return new maplibregl.Popup({ offset: 18 }).setHTML(
    `<strong>${escapeHtml(place.name)}</strong>`,
  );
}

function removeMarkerEntry(entry: MarkerEntry): void {
  entry.marker.getElement().removeEventListener("click", entry.onClick);
  entry.marker.remove();
}

function syncMarkerElement(
  element: HTMLElement,
  place: DestinationSummary,
  number: number,
  selected: boolean,
): void {
  // 목록 행 번호와 동일한 1-based 번호를 읽기 쉬운 원형 배지로 표시한다.
  let badge = element.querySelector<HTMLElement>("[data-slot='marker-badge']");
  if (!badge) {
    badge = document.createElement("span");
    badge.dataset.slot = "marker-badge";
    element.replaceChildren(badge);
  }
  badge.textContent = String(number);
  element.setAttribute("aria-label", `${number}번 ${place.name} 선택`);
  element.dataset.selected = String(selected);
  element.dataset.markerNumber = String(number);
  // marker root의 transform은 MapLibre가 좌표 배치에 사용하므로 절대 덮어쓰지 않는다.
  // 선택 마커의 시각적 lift는 내부 badge에만 적용한다.
  const size = selected ? "28px" : "22px";
  element.style.width = size;
  element.style.height = size;
  element.style.boxSizing = "border-box";
  element.style.padding = "0";
  element.style.display = "flex";
  element.style.alignItems = "center";
  element.style.justifyContent = "center";
  element.style.borderRadius = "9999px";
  element.style.border = "0";
  element.style.background = "transparent";
  element.style.cursor = "pointer";
  element.style.zIndex = selected ? "2" : "1";
  element.style.fontFamily =
    "var(--font-sans, Pretendard), Pretendard, 'Noto Sans KR', 'Apple SD Gothic Neo', 'Malgun Gothic', sans-serif";

  badge.style.width = "100%";
  badge.style.height = "100%";
  badge.style.boxSizing = "border-box";
  badge.style.display = "flex";
  badge.style.alignItems = "center";
  badge.style.justifyContent = "center";
  badge.style.borderRadius = "9999px";
  badge.style.border = "2px solid #ffffff";
  badge.style.fontSize = selected ? "13px" : "11px";
  badge.style.fontWeight = "700";
  badge.style.lineHeight = "1";
  badge.style.color = "#ffffff";
  badge.style.backgroundColor = selected ? "var(--brand)" : "var(--text-secondary)";
  badge.style.boxShadow = selected
    ? "0 0 0 3px rgba(47, 118, 95, 0.24), 0 8px 18px rgba(60, 63, 61, 0.22)"
    : "0 6px 14px rgba(60, 63, 61, 0.18)";
  badge.style.transform = selected ? "translateY(-2px)" : "translateY(0)";
  badge.style.transition =
    "background-color 150ms ease, transform 150ms ease, box-shadow 150ms ease, width 150ms ease, height 150ms ease";
}

function buildVWorldStyle(key: string): maplibregl.StyleSpecification {
  if (!key) {
    return {
      version: 8,
      sources: {},
      layers: [
        {
          id: "fallback-background",
          type: "background",
          paint: { "background-color": "#e8edf3" },
        },
      ],
    };
  }
  return {
    version: 8,
    sources: {
      vworld: {
        type: "raster",
        tiles: [
          `https://api.vworld.kr/req/wmts/1.0.0/${key}/Base/{z}/{y}/{x}.png`,
        ],
        tileSize: 256,
        minzoom: VWORLD_MIN_ZOOM,
        bounds: KOREA_TILE_BOUNDS,
        attribution: "VWorld",
      },
    },
    layers: [
      {
        id: "vworld-base",
        type: "raster",
        source: "vworld",
      },
    ],
  };
}

function escapeHtml(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
