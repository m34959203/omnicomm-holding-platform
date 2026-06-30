"use client";

import { useEffect, useRef, useState } from "react";
import { VehicleDetail, getVehicle, getVehicleTelemetry } from "@/lib/api";
import { num } from "@/lib/format";
import { YANDEX_KEY, loadYmaps } from "@/lib/ymaps";
import { LineChart } from "./charts";

// Карточка ТС: спутниковая карта с треком + график скорости во времени +
// телеметрия. Аналог «карточки ТС» Omnicomm. Недоступные по REST поля
// (напряжение бортсети, темп. топлива, водитель) показываем честным прочерком.
export default function VehicleCard({
  terminalId, name, onClose, period,
}: {
  terminalId: string;
  name?: string;
  onClose: () => void;
  period?: { start_ts: number; end_ts: number };  // окно карточки; нет → период отчёта
}) {
  // Подпись окна: одни сутки эпизода → дата; иначе диапазон; нет period → «за период отчёта».
  const windowLabel = (() => {
    if (!period) return "за период отчёта";
    const f = (ts: number) => new Date(ts * 1000).toLocaleDateString("ru-RU");
    return period.end_ts - period.start_ts <= 26 * 3600 ? f(period.start_ts)
      : `${f(period.start_ts)} — ${f(period.end_ts)}`;
  })();
  const [data, setData] = useState<VehicleDetail | null>(null);
  const [telem, setTelem] = useState<Record<string, number | null> | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const mapRef = useRef<HTMLDivElement>(null);
  const mapObj = useRef<any>(null);

  useEffect(() => {
    let cancelled = false;
    // трек — быстро (~1-2с): карта + график появляются сразу. Окно = period (сутки
    // эпизода) или дефолт бэкенда (период отчёта).
    getVehicle(terminalId, period)
      .then((d) => { if (!cancelled) setData(d); })
      .catch((e) => { if (!cancelled) setErr(String(e?.message ?? e)); });
    // телеметрия — медленно (~16с, сводный отчёт): догружаем лениво
    getVehicleTelemetry(terminalId)
      .then((r) => { if (!cancelled) setTelem(r.telemetry ?? {}); })
      .catch(() => { if (!cancelled) setTelem({}); });
    return () => { cancelled = true; };
  }, [terminalId, period?.start_ts, period?.end_ts]);

  // карта с треком — после загрузки данных
  useEffect(() => {
    if (!data || !mapRef.current || !YANDEX_KEY || !data.track.length) return;
    let cancelled = false;
    loadYmaps().then((ymaps) => {
      if (cancelled || !mapRef.current) return;
      const coords = data.track.map((t) => [t.lat, t.lon]);
      const last = data.last ?? data.track[data.track.length - 1];
      const map = new ymaps.Map(mapRef.current, {
        center: [last.lat, last.lon], zoom: 12, type: "yandex#hybrid",
        controls: ["zoomControl"],
      }, { suppressMapOpenBlock: true });
      mapObj.current = map;
      map.geoObjects.add(new ymaps.Polyline(coords, {}, {
        strokeColor: "#1f6fd6", strokeWidth: 3, strokeOpacity: 0.9,
      }));
      const start = data.track[0];
      map.geoObjects.add(new ymaps.Placemark([start.lat, start.lon],
        { hintContent: "старт" }, { preset: "islands#grayCircleDotIcon" }));
      map.geoObjects.add(new ymaps.Placemark([last.lat, last.lon],
        { hintContent: data.name || terminalId, balloonContent: `${num(last.speed, 1)} км/ч` },
        { preset: "islands#greenAutoIcon", iconColor: "#1f6fd6" }));
      const b = map.geoObjects.getBounds();
      if (b) map.setBounds(b, { checkZoomRange: true, zoomMargin: 30 });
    }).catch(() => {});
    return () => {
      cancelled = true;
      if (mapObj.current) { mapObj.current.destroy(); mapObj.current = null; }
    };
  }, [data, terminalId]);

  const t = telem ?? {};
  const speeds = (data?.speed_series ?? []).map((s) => s.speed);
  const loadingT = telem === null; // телеметрия ещё грузится
  const tv = (v: number | null | undefined, suffix: string) =>
    loadingT ? "…" : v != null ? `${num(v, 1)} ${suffix}` : "—";

  const tele: [string, string][] = [
    ["Макс. скорость", data ? `${num(t.max_speed_kmh ?? data.track_max_speed, 1)} км/ч` : "…"],
    ["Пробег", tv(t.mileage_km, "км")],
    ["Моточасы", tv(t.engine_hours, "ч")],
    ["Топливо", tv(t.fuel_l, "л")],
    ["Топливо простоя", tv(t.fuel_idle_l, "л")],
    ["Точек трека", data ? num(data.track_points) : "…"],
  ];

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center p-4"
      style={{ background: "rgba(0,0,0,.7)" }} onClick={onClose}>
      <div className="flex max-h-[92vh] w-full max-w-6xl flex-col overflow-hidden border border-line-strong"
        style={{ background: "var(--paper)" }} onClick={(e) => e.stopPropagation()}>
        {/* шапка */}
        <div className="flex items-baseline justify-between gap-4 border-b border-line px-6 py-4">
          <div>
            <span className="eyebrow">Карточка ТС · {windowLabel}</span>
            <h3 className="display text-2xl text-ink">{data?.name || name || terminalId}</h3>
          </div>
          <button onClick={onClose}
            className="eyebrow text-ink-faint transition-colors hover:text-accent">закрыть ✕</button>
        </div>

        {err && (
          <div className="px-6 py-10 text-sm text-danger">Не удалось загрузить ТС: {err}</div>
        )}

        {!err && (
          <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
            <div className="grid gap-px bg-line-strong lg:grid-cols-[1.7fr_1fr]">
              {/* карта */}
              <div ref={mapRef} style={{ background: "var(--surface)", minHeight: "46vh" }}
                className="w-full">
                {!data && <div className="flex h-full items-center justify-center text-sm text-ink-faint">загрузка трека…</div>}
              </div>
              {/* состояние онлайн + телеметрия */}
              <div className="flex flex-col bg-paper p-6" style={{ background: "var(--paper)" }}>
                <span className="eyebrow">Состояние · онлайн</span>
                <div className="mt-3 grid grid-cols-2 gap-x-6">
                  <div className="border-t border-line py-3">
                    <span className="eyebrow">Напряжение бортсети</span>
                    <p className="data text-xl text-accent">
                      {data?.state?.voltage != null ? `${num(data.state.voltage, 1)} В` : data ? "—" : "…"}
                    </p>
                  </div>
                  <div className="border-t border-line py-3">
                    <span className="eyebrow">Зажигание</span>
                    <p className="data text-xl text-ink">
                      {data?.state?.ignition == null ? (data ? "—" : "…") : data.state.ignition ? "вкл" : "выкл"}
                    </p>
                  </div>
                  <div className="border-t border-line py-3">
                    <span className="eyebrow">Тек. скорость</span>
                    <p className="data text-xl text-ink">
                      {data?.state?.current_speed != null ? `${num(data.state.current_speed, 1)} км/ч` : data ? "—" : "…"}
                    </p>
                  </div>
                  <div className="border-t border-line py-3">
                    <span className="eyebrow">Тек. топливо</span>
                    <p className="data text-xl text-ink">
                      {data?.state?.current_fuel != null && data.state.current_fuel >= 0
                        ? `${num(data.state.current_fuel, 1)} л` : data ? "—" : "…"}
                    </p>
                  </div>
                </div>
                {data?.state?.address && (
                  <p className="data mt-2 text-xs text-ink-dim">{data.state.address}</p>
                )}

                <span className="eyebrow mt-6">Телеметрия · за сутки</span>
                <div className="mt-3 grid grid-cols-2 gap-x-6">
                  {tele.map(([k, v]) => (
                    <div key={k} className="border-t border-line py-3">
                      <span className="eyebrow">{k}</span>
                      <p className="data text-xl text-ink">{v}</p>
                    </div>
                  ))}
                </div>
                <p className="data mt-4 text-[0.7rem] leading-relaxed text-ink-faint">
                  Темп. топлива и водитель недоступны через REST. Напряжение бортсети —
                  из текущего состояния ТС (/vehicles/state).
                </p>
              </div>
            </div>

            {/* график скорости во времени */}
            <div className="px-6 py-5">
              <span className="eyebrow">Скорость во времени · км/ч</span>
              <div className="mt-3">
                {speeds.length > 1
                  ? <LineChart series={speeds} unit="км/ч" />
                  : <p className="data text-sm text-ink-faint">нет точек трека за период</p>}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
