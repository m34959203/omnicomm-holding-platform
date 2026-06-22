"use client";

import { useEffect, useRef, useState } from "react";
import { setOptions, importLibrary } from "@googlemaps/js-api-loader";
import { GeoFeature } from "@/lib/api";

// Карта геозон на Google Maps (mapTypeId hybrid: спутник + подписи дорог/городов).
// Геозоны рисуются нативными Polygon/Polyline, клик → InfoWindow с названием+лимитом.
// Требует NEXT_PUBLIC_GOOGLE_MAPS_KEY (билинг + Maps JS API).

export default function GoogleGeozoneMap({
  features,
  apiKey,
}: {
  features: GeoFeature[];
  apiKey: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [mapType, setMapType] = useState<"hybrid" | "roadmap">("hybrid");
  const [err, setErr] = useState<string | null>(null);
  const mapRef = useRef<google.maps.Map | null>(null);

  useEffect(() => {
    if (!ref.current || !features.length) return;
    let cancelled = false;

    setOptions({ key: apiKey, v: "weekly" });
    Promise.all([importLibrary("maps"), importLibrary("core")])
      .then(([{ Map, Polygon, Polyline, InfoWindow }, { LatLngBounds }]) => {
        if (cancelled || !ref.current) return;

        const bounds = new LatLngBounds();
        const map = new Map(ref.current, {
          mapTypeId: mapType,
          disableDefaultUI: false,
          mapTypeControl: false,
          streetViewControl: false,
          backgroundColor: "#0c0c0d",
        });
        mapRef.current = map;
        const info = new InfoWindow();

        for (const f of features) {
          const color = `rgb(${f.color.join(",")})`;
          const path = f.path.map(([lng, lat]) => {
            bounds.extend({ lat, lng });
            return { lat, lng };
          });
          const opts = {
            strokeColor: color,
            strokeOpacity: 0.95,
            strokeWeight: f.kind === "line" ? 3 : 1.6,
          };
          const shape =
            f.kind === "polygon"
              ? new Polygon({ paths: path, fillColor: color, fillOpacity: 0.25, ...opts })
              : new Polyline({ path, ...opts });
          shape.setMap(map);
          shape.addListener("click", (e: google.maps.PolyMouseEvent) => {
            info.setContent(
              `<div style="font:12px ui-monospace,monospace;color:#0c0c0d">${f.tooltip}</div>`,
            );
            info.setPosition(e.latLng);
            info.open(map);
          });
        }
        map.fitBounds(bounds, 48);
      })
      .catch((e) => !cancelled && setErr(String(e?.message ?? e)));

    return () => {
      cancelled = true;
      mapRef.current = null;
    };
  }, [features, apiKey, mapType]);

  if (err)
    return (
      <div className="flex h-64 flex-col items-center justify-center gap-2 border border-line-strong text-sm">
        <span className="text-danger">Google Maps не загрузилась</span>
        <span className="data text-xs text-ink-faint">{err}</span>
        <span className="data text-xs text-ink-faint">
          проверьте ключ, биллинг и referrer-ограничение домена
        </span>
      </div>
    );

  return (
    <div className="relative">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-3">
        <div className="flex items-baseline gap-3">
          <span className="eyebrow">Геозоны · {features.length}</span>
          <span className="data text-xs text-ink-faint">Google Maps · клик — название и лимит</span>
        </div>
        <div className="flex gap-1">
          {(["hybrid", "roadmap"] as const).map((t) => (
            <button
              key={t}
              onClick={() => setMapType(t)}
              className={`border px-3 py-1 text-[0.7rem] uppercase tracking-[0.12em] transition-colors ${
                mapType === t ? "border-accent text-accent" : "border-line-strong text-ink-dim hover:text-ink"
              }`}
              style={{ fontFamily: "var(--font-mono)" }}
            >
              {t === "hybrid" ? "Гибрид" : "Схема"}
            </button>
          ))}
        </div>
      </div>
      <div ref={ref} className="w-full overflow-hidden border border-line-strong" style={{ height: "64vh" }} />
    </div>
  );
}
