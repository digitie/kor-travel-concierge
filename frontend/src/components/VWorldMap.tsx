"use client";

import maplibregl, { type Map as MapLibreMap, type Marker } from "maplibre-gl";
import { useEffect, useRef } from "react";

import { type DestinationSummary, VWORLD_SERVICE_KEY } from "@/lib/api";

type VWorldMapProps = {
  places: DestinationSummary[];
  selectedPlaceId: number | null;
  onSelectPlace: (placeId: number) => void;
};

type MarkerEntry = {
  marker: Marker;
  place: DestinationSummary;
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
    const visiblePlaces = places.filter(hasValidCoordinates);
    const visibleIds = new Set(visiblePlaces.map((place) => place.place_id));

    markersRef.current.forEach((entry, placeId) => {
      if (!visibleIds.has(placeId)) {
        removeMarkerEntry(entry);
        markersRef.current.delete(placeId);
      }
    });

    visiblePlaces.forEach((place) => {
      const existing = markersRef.current.get(place.place_id);
      const onClick = () => onSelectPlace(place.place_id);
      if (existing) {
        const element = existing.marker.getElement();
        element.removeEventListener("click", existing.onClick);
        element.addEventListener("click", onClick);
        existing.marker.setLngLat([place.longitude, place.latitude]);
        existing.marker.setPopup(buildPopup(place));
        existing.place = place;
        existing.onClick = onClick;
        syncMarkerElement(element, place, place.place_id === selectedPlaceId);
        return;
      }

      const element = document.createElement("button");
      element.type = "button";
      const marker = new maplibregl.Marker({ element, anchor: "bottom" })
        .setLngLat([place.longitude, place.latitude])
        .setPopup(buildPopup(place))
        .addTo(map);
      element.addEventListener("click", onClick);
      syncMarkerElement(element, place, place.place_id === selectedPlaceId);
      markersRef.current.set(place.place_id, { marker, place, onClick });
    });
  }, [onSelectPlace, places, selectedPlaceId]);

  useEffect(() => {
    markersRef.current.forEach((entry) => {
      syncMarkerElement(
        entry.marker.getElement(),
        entry.place,
        entry.place.place_id === selectedPlaceId,
      );
    });
  }, [selectedPlaceId]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) {
      return;
    }
    const entry = selectedPlaceId ? markersRef.current.get(selectedPlaceId) : null;
    if (entry) {
      map.easeTo({
        center: [entry.place.longitude, entry.place.latitude],
        zoom: Math.max(map.getZoom(), 12),
        duration: 500,
      });
    }
  }, [selectedPlaceId]);

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

function hasValidCoordinates(place: DestinationSummary): boolean {
  return Number.isFinite(place.latitude) && Number.isFinite(place.longitude);
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
  selected: boolean,
): void {
  element.setAttribute("aria-label", `${place.name} 선택`);
  element.dataset.selected = String(selected);
  element.style.width = selected ? "18px" : "14px";
  element.style.height = selected ? "18px" : "14px";
  element.style.borderRadius = "9999px";
  element.style.border = "2px solid #ffffff";
  element.style.backgroundColor = selected ? "#111827" : "#2563eb";
  element.style.boxShadow = selected
    ? "0 0 0 3px rgba(17, 24, 39, 0.22), 0 8px 18px rgba(15, 23, 42, 0.28)"
    : "0 6px 14px rgba(37, 99, 235, 0.26)";
  element.style.cursor = "pointer";
  element.style.transform = selected ? "translateY(-2px)" : "translateY(0)";
  element.style.transition = "background-color 150ms ease, transform 150ms ease, box-shadow 150ms ease";
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
          paint: { "background-color": "#e5e7eb" },
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
