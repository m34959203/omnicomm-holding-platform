"use client";

import { GeoFeature } from "@/lib/api";
import YandexGeozoneMap from "./YandexGeozoneMap";
import GoogleGeozoneMap from "./GoogleGeozoneMap";
import MapLibreGeozoneMap from "./MapLibreGeozoneMap";

// Выбор рендерера карты по доступному ключу:
//  1) Яндекс.Карты (hybrid: спутник + подписи) — основной;
//  2) Google Maps (hybrid) — если задан только он;
//  3) бесплатный MapLibre-гибрид (спутник Esri + подписи Carto) — без ключей.
const YANDEX_KEY = process.env.NEXT_PUBLIC_YANDEX_MAPS_API_KEY ?? "";
const GOOGLE_KEY = process.env.NEXT_PUBLIC_GOOGLE_MAPS_KEY ?? "";

export default function GeozoneMap({ features }: { features: GeoFeature[] }) {
  if (YANDEX_KEY) return <YandexGeozoneMap features={features} apiKey={YANDEX_KEY} />;
  if (GOOGLE_KEY) return <GoogleGeozoneMap features={features} apiKey={GOOGLE_KEY} />;
  return <MapLibreGeozoneMap features={features} />;
}
