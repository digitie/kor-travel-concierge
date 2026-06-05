"use client";

import maplibregl, { type Map, type Marker } from "maplibre-gl";
import { useEffect, useRef } from "react";

import { type DestinationSummary, VWORLD_SERVICE_KEY } from "@/lib/api";

type VWorldMapProps = {
  places: DestinationSummary[];
  selectedPlaceId: number | null;
  onSelectPlace: (placeId: number) => void;
};

const KOREA_CENTER: [number, number] = [127.8, 36.4];

export function VWorldMap({
  places,
  selectedPlaceId,
  onSelectPlace,
}: VWorldMapProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<Map | null>(null);
  const markersRef = useRef<Marker[]>([]);

  useEffect(() => {
    if (!containerRef.current || mapRef.current) {
      return;
    }
    mapRef.current = new maplibregl.Map({
      container: containerRef.current,
      style: buildVWorldStyle(VWORLD_SERVICE_KEY),
      center: KOREA_CENTER,
      zoom: 6.2,
      attributionControl: false,
    });
    mapRef.current.addControl(new maplibregl.NavigationControl(), "top-right");
    return () => {
      markersRef.current.forEach((marker) => marker.remove());
      markersRef.current = [];
      mapRef.current?.remove();
      mapRef.current = null;
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) {
      return;
    }
    markersRef.current.forEach((marker) => marker.remove());
    markersRef.current = places
      .filter((place) => Number.isFinite(place.latitude) && Number.isFinite(place.longitude))
      .map((place) => {
        const marker = new maplibregl.Marker({
          color: place.place_id === selectedPlaceId ? "#111827" : "#2563eb",
        })
          .setLngLat([place.longitude, place.latitude])
          .setPopup(
            new maplibregl.Popup({ offset: 18 }).setHTML(
              `<strong>${escapeHtml(place.name)}</strong>`,
            ),
          )
          .addTo(map);
        marker.getElement().addEventListener("click", () => onSelectPlace(place.place_id));
        return marker;
      });
    const selected = places.find((place) => place.place_id === selectedPlaceId);
    if (selected) {
      map.easeTo({
        center: [selected.longitude, selected.latitude],
        zoom: Math.max(map.getZoom(), 12),
        duration: 500,
      });
    }
  }, [onSelectPlace, places, selectedPlaceId]);

  return (
    <div
      id="vworld-map-container"
      ref={containerRef}
      className="h-full w-full bg-muted"
      data-status={VWORLD_SERVICE_KEY ? "vworld" : "fallback"}
    />
  );
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
