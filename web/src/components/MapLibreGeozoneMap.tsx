"use client";

import { useEffect, useRef, useState } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { GeoFeature } from "@/lib/api";

// Настоящая карта геозон СТ КАП с двумя подложками (без токенов):
//  • «Гибрид» — спутник Esri World Imagery + прозрачные подписи дорог/городов Carto
//  • «Тёмная» — тёмная карта Carto (editorial-noir)
// Поверх — геозоны (площадки/трассы), подписи лимитов и клик-попап с названием.

const SAT_LABELS = (s: string) =>
  `https://${s}.basemaps.cartocdn.com/rastertiles/voyager_only_labels/{z}/{x}/{y}@2x.png`;
const DARK = (s: string) =>
  `https://${s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}@2x.png`;

const STYLE_HYBRID: maplibregl.StyleSpecification = {
  version: 8,
  glyphs: "https://fonts.openmaptiles.org/{fontstack}/{range}.pbf",
  sources: {
    sat: {
      type: "raster", tileSize: 256,
      tiles: ["https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"],
      attribution: "Esri, Maxar, Earthstar Geographics",
    },
    labels: {
      type: "raster", tileSize: 256,
      tiles: [SAT_LABELS("a"), SAT_LABELS("b"), SAT_LABELS("c")],
      attribution: "© OpenStreetMap, © CARTO",
    },
  },
  layers: [
    { id: "sat", type: "raster", source: "sat" },
    { id: "labels", type: "raster", source: "labels" },
  ],
};

const STYLE_DARK: maplibregl.StyleSpecification = {
  version: 8,
  glyphs: "https://fonts.openmaptiles.org/{fontstack}/{range}.pbf",
  sources: {
    carto: {
      type: "raster", tileSize: 256,
      tiles: [DARK("a"), DARK("b"), DARK("c")],
      attribution: "© OpenStreetMap, © CARTO",
    },
  },
  layers: [{ id: "carto", type: "raster", source: "carto" }],
};

function toGeoJSON(features: GeoFeature[]) {
  return {
    type: "FeatureCollection" as const,
    features: features.map((f) => ({
      type: "Feature" as const,
      properties: {
        label: f.limit ? `${f.limit}` : "",
        full: f.tooltip,
        color: `rgb(${f.color.join(",")})`,
        kind: f.kind,
      },
      geometry:
        f.kind === "polygon"
          ? { type: "Polygon" as const, coordinates: [f.path] }
          : { type: "LineString" as const, coordinates: f.path },
    })),
  };
}

function addOverlay(map: maplibregl.Map, features: GeoFeature[]) {
  if (map.getSource("gz")) return;
  map.addSource("gz", { type: "geojson", data: toGeoJSON(features) });
  map.addLayer({
    id: "gz-fill", type: "fill", source: "gz",
    filter: ["==", ["get", "kind"], "polygon"],
    paint: { "fill-color": ["get", "color"], "fill-opacity": 0.25 },
  });
  map.addLayer({
    id: "gz-poly-line", type: "line", source: "gz",
    filter: ["==", ["get", "kind"], "polygon"],
    paint: { "line-color": ["get", "color"], "line-width": 1.6, "line-opacity": 0.95 },
  });
  map.addLayer({
    id: "gz-line", type: "line", source: "gz",
    filter: ["==", ["get", "kind"], "line"],
    paint: {
      "line-color": ["get", "color"], "line-opacity": 0.9,
      "line-width": ["interpolate", ["linear"], ["zoom"], 6, 2.5, 13, 7],
    },
  });
  map.addLayer({
    id: "gz-label", type: "symbol", source: "gz",
    filter: ["!=", ["get", "label"], ""],
    layout: {
      "text-field": ["get", "label"], "text-font": ["Noto Sans Regular"],
      "text-size": 12, "symbol-placement": "point",
    },
    paint: {
      "text-color": "#1f6fd6", "text-halo-color": "#ffffff", "text-halo-width": 1.8,
    },
  });

  const popup = (e: maplibregl.MapLayerMouseEvent) => {
    const f = e.features?.[0];
    if (!f) return;
    new maplibregl.Popup({ closeButton: false, offset: 8 })
      .setLngLat(e.lngLat)
      .setHTML(
        `<div style="font:12px ui-monospace,monospace;color:#0c0c0d">${
          (f.properties as { full?: string }).full ?? ""
        }</div>`,
      )
      .addTo(e.target);
  };
  for (const id of ["gz-fill", "gz-line", "gz-poly-line"]) {
    map.on("click", id, popup);
    map.on("mouseenter", id, () => (map.getCanvas().style.cursor = "pointer"));
    map.on("mouseleave", id, () => (map.getCanvas().style.cursor = ""));
  }
}

export default function MapLibreGeozoneMap({ features }: { features: GeoFeature[] }) {
  const ref = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const [base, setBase] = useState<"hybrid" | "dark">("hybrid");

  useEffect(() => {
    if (!ref.current || !features.length) return;
    const pts = features.flatMap((f) => f.path);
    const lons = pts.map((p) => p[0]);
    const lats = pts.map((p) => p[1]);

    const map = new maplibregl.Map({
      container: ref.current,
      style: base === "hybrid" ? STYLE_HYBRID : STYLE_DARK,
      bounds: [[Math.min(...lons), Math.min(...lats)], [Math.max(...lons), Math.max(...lats)]],
      fitBoundsOptions: { padding: 48 },
      attributionControl: { compact: true },
    });
    mapRef.current = map;
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    map.on("load", () => addOverlay(map, features));

    return () => { map.remove(); mapRef.current = null; };
  }, [features, base]);

  if (!features.length)
    return (
      <div className="flex h-64 items-center justify-center text-sm text-ink-faint">
        Геозоны доступны на боевом контуре.
      </div>
    );

  return (
    <div className="relative">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-3">
        <div className="flex items-baseline gap-3">
          <span className="eyebrow">Геозоны · {features.length}</span>
          <span className="data text-xs text-ink-faint">клик по участку — название и лимит</span>
        </div>
        <div className="flex gap-1">
          {(["hybrid", "dark"] as const).map((b) => (
            <button
              key={b}
              onClick={() => setBase(b)}
              className={`border px-3 py-1 text-[0.7rem] uppercase tracking-[0.12em] transition-colors ${
                base === b
                  ? "border-accent text-accent"
                  : "border-line-strong text-ink-dim hover:text-ink"
              }`}
              style={{ fontFamily: "var(--font-mono)" }}
            >
              {b === "hybrid" ? "Гибрид" : "Тёмная"}
            </button>
          ))}
        </div>
      </div>
      <div
        ref={ref}
        className="w-full overflow-hidden border border-line-strong"
        style={{ height: "64vh" }}
      />
    </div>
  );
}
