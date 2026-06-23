"use client";

// Общий загрузчик Яндекс.Карт (один script на всё приложение) — используют
// и карта геозон, и карточка ТС (трек), чтобы не грузить скрипт дважды.

let ymapsPromise: Promise<any> | null = null;

export const YANDEX_KEY = process.env.NEXT_PUBLIC_YANDEX_MAPS_API_KEY ?? "";

export function loadYmaps(apiKey: string = YANDEX_KEY): Promise<any> {
  if (typeof window === "undefined") return Promise.reject(new Error("no window"));
  const w = window as unknown as { ymaps?: any };
  if (w.ymaps?.Map) return Promise.resolve(w.ymaps);
  if (!ymapsPromise) {
    ymapsPromise = new Promise((resolve, reject) => {
      const s = document.createElement("script");
      s.src = `https://api-maps.yandex.ru/2.1/?apikey=${apiKey}&lang=ru_RU`;
      s.async = true;
      s.onload = () => w.ymaps.ready(() => resolve(w.ymaps));
      s.onerror = () => reject(new Error("yandex maps failed to load"));
      document.head.appendChild(s);
    });
  }
  return ymapsPromise;
}
