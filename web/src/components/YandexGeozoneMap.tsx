"use client";

import { useEffect, useRef, useState } from "react";
import { GeoFeature } from "@/lib/api";
import { loadYmaps } from "@/lib/ymaps";

// Карта геозон на Яндекс.Картах. Тип «Гибрид» (yandex#hybrid) = спутник + подписи
// дорог/городов, «Схема» (yandex#map) — векторная схема. Геозоны рисуются нативными
// ymaps.Polygon/ymaps.Polyline, клик по фигуре → балун с названием и лимитом.
// Требует NEXT_PUBLIC_YANDEX_MAPS_API_KEY (JS API, ограничение по referrer-домену).

export default function YandexGeozoneMap({
  features,
  apiKey,
}: {
  features: GeoFeature[];
  apiKey: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const mapRef = useRef<any>(null);
  const [mapType, setMapType] = useState<"yandex#hybrid" | "yandex#map">("yandex#hybrid");
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!ref.current || !features.length) return;
    let cancelled = false;

    loadYmaps(apiKey)
      .then((ymaps) => {
        if (cancelled || !ref.current) return;

        const map = new ymaps.Map(
          ref.current,
          { center: [48.0, 67.0], zoom: 5, type: mapType, controls: ["zoomControl"] },
          { suppressMapOpenBlock: true },
        );
        mapRef.current = map;

        for (const f of features) {
          const color = `rgb(${f.color.join(",")})`;
          // GeoJSON-порядок [lng, lat] → Яндекс ожидает [lat, lng].
          const coords = f.path.map(([lng, lat]) => [lat, lng]);
          const props = { balloonContent: f.tooltip, hintContent: f.name };

          const shape =
            f.kind === "polygon"
              ? new ymaps.Polygon([coords], props, {
                  fillColor: color,
                  fillOpacity: 0.25,
                  strokeColor: color,
                  strokeOpacity: 0.95,
                  strokeWidth: 1.6,
                })
              : new ymaps.Polyline(coords, props, {
                  strokeColor: color,
                  strokeOpacity: 0.95,
                  // f.width из Omnicomm — ширина коридора в МЕТРАХ, не пиксели;
                  // рисуем фиксированной тонкой линией, иначе линия = полоса в пол-экрана.
                  strokeWidth: 3,
                });
          map.geoObjects.add(shape);
        }

        // Вписать все геозоны в видимую область.
        const bounds = map.geoObjects.getBounds();
        if (bounds) {
          map.setBounds(bounds, { checkZoomRange: true, zoomMargin: 32 });
        }
      })
      .catch((e) => !cancelled && setErr(String(e?.message ?? e)));

    return () => {
      cancelled = true;
      if (mapRef.current) {
        mapRef.current.destroy();
        mapRef.current = null;
      }
    };
  }, [features, apiKey, mapType]);

  if (err)
    return (
      <div className="flex h-64 flex-col items-center justify-center gap-2 border border-line-strong text-sm">
        <span className="text-danger">Яндекс.Карты не загрузились</span>
        <span className="data text-xs text-ink-faint">{err}</span>
        <span className="data text-xs text-ink-faint">
          проверьте ключ и referrer-ограничение домена
        </span>
      </div>
    );

  return (
    <div className="relative">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-3">
        <div className="flex items-baseline gap-3">
          <span className="eyebrow">Геозоны · {features.length}</span>
          <span className="data text-xs text-ink-faint">
            Яндекс.Карты · клик — название и лимит
          </span>
        </div>
        <div className="flex gap-1">
          {(["yandex#hybrid", "yandex#map"] as const).map((t) => (
            <button
              key={t}
              onClick={() => setMapType(t)}
              className={`border px-3 py-1 text-[0.7rem] uppercase tracking-[0.12em] transition-colors ${
                mapType === t
                  ? "border-accent text-accent"
                  : "border-line-strong text-ink-dim hover:text-ink"
              }`}
              style={{ fontFamily: "var(--font-mono)" }}
            >
              {t === "yandex#hybrid" ? "Гибрид" : "Схема"}
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
