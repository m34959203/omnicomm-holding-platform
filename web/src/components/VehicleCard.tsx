"use client";

import { useEffect, useRef, useState } from "react";
import { VehicleDetail, getVehicle, getVehicleTelemetry } from "@/lib/api";
import { num } from "@/lib/format";
import { schemaFor, METRICS, metricText, SectionKey } from "@/lib/cardSchema";
import { YANDEX_KEY, loadYmaps } from "@/lib/ymaps";
import { LineChart } from "./charts";
import ModelRef from "./atlas/ModelRef";

const SECTION_LABEL: Record<SectionKey, string> = {
  maint: "Контроль ТО", tyres: "Шины", speeding: "Скоростной режим",
  onsite: "Работа на месте", balance: "Баланс топлива",
};

// Карточка ТС — АДАПТИВНАЯ ПО ТИПУ АГРЕГАТА: набор параметров, референс модели и
// сетка подстраиваются под тип (буровая/компрессор/самосвал/АГП/каротаж/АТЗ…).
// Схема типа — `lib/cardSchema`. Недоступные по REST поля — честным прочерком.
export default function VehicleCard({
  terminalId, name, onClose, period,
}: {
  terminalId: string;
  name?: string;
  onClose: () => void;
  period?: { start_ts: number; end_ts: number };
}) {
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
    // имя → бэк определяет тип агрегата + референс модели
    getVehicle(terminalId, period, name)
      .then((d) => { if (!cancelled) setData(d); })
      .catch((e) => { if (!cancelled) setErr(String(e?.message ?? e)); });
    getVehicleTelemetry(terminalId)
      .then((r) => { if (!cancelled) setTelem(r.telemetry ?? {}); })
      .catch(() => { if (!cancelled) setTelem({}); });
    return () => { cancelled = true; };
  }, [terminalId, name, period?.start_ts, period?.end_ts]);

  const schema = schemaFor(data?.vehicle_type);
  const showMap = schema.mapWeight !== "hidden";

  // карта с треком
  useEffect(() => {
    if (!data || !showMap || !mapRef.current || !YANDEX_KEY || !data.track.length) return;
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
  }, [data, terminalId, showMap]);

  const t = telem ?? {};
  const speeds = (data?.speed_series ?? []).map((s) => s.speed);
  const loadingT = telem === null;
  const mapMinHeight = schema.mapWeight === "compact" ? "30vh" : "46vh";
  const gridCols = schema.mapWeight === "compact" ? "lg:grid-cols-[1fr_1.3fr]" : "lg:grid-cols-[1.7fr_1fr]";

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center p-4"
      style={{ background: "rgba(0,0,0,.7)" }} onClick={onClose}>
      <div className="flex max-h-[92vh] w-full max-w-6xl flex-col overflow-hidden border border-line-strong"
        style={{ background: "var(--paper)" }} onClick={(e) => e.stopPropagation()}>
        {/* шапка: идентити + тип-бейдж + референс модели */}
        <div className="flex items-start justify-between gap-4 border-b border-line px-6 py-4">
          <div className="min-w-0 flex-1">
            <span className="eyebrow">Карточка ТС · {windowLabel}</span>
            <div className="flex items-center gap-3">
              <h3 className="display truncate text-2xl text-ink">{data?.name || name || terminalId}</h3>
              {data?.type_label && (
                <span style={{ fontSize: 11, fontWeight: 600, padding: "2px 9px", borderRadius: 12,
                  background: "rgba(31,111,214,.1)", color: "#1f6fd6", whiteSpace: "nowrap" }}>
                  {data.type_label}
                </span>
              )}
            </div>
            <div className="mt-3 max-w-xl">
              <ModelRef model={data?.model_ref} type={data?.vehicle_type} />
            </div>
          </div>
          <button onClick={onClose}
            className="eyebrow text-ink-faint transition-colors hover:text-accent">закрыть ✕</button>
        </div>

        {err && (
          <div className="px-6 py-10 text-sm text-danger">Не удалось загрузить ТС: {err}</div>
        )}

        {!err && (
          <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
            <div className={`grid gap-px bg-line-strong ${showMap ? gridCols : ""}`}>
              {/* карта (скрыта для полностью привязанных объектов) */}
              {showMap && (
                <div ref={mapRef} style={{ background: "var(--surface)", minHeight: mapMinHeight }}
                  className="w-full">
                  {!data && <div className="flex h-full items-center justify-center text-sm text-ink-faint">загрузка трека…</div>}
                </div>
              )}
              {/* состояние онлайн + тип-специфичная телеметрия */}
              <div className="flex flex-col bg-paper p-6" style={{ background: "var(--paper)" }}>
                {!showMap && data?.state?.address && (
                  <p className="data mb-3 text-xs text-ink-dim">Стоит: {data.state.address}</p>
                )}
                <span className="eyebrow">Состояние · онлайн</span>
                <div className="mt-3 grid grid-cols-2 gap-x-6">
                  {schema.online.map((key) => (
                    <div key={key} className="border-t border-line py-3">
                      <span className="eyebrow">{METRICS[key]?.label ?? key}</span>
                      <p className={`data text-xl ${key === "voltage" ? "text-accent" : "text-ink"}`}>
                        {metricText(key, data, t, false)}
                      </p>
                    </div>
                  ))}
                </div>

                <span className="eyebrow mt-6">Телеметрия · за сутки</span>
                <div className="mt-3 grid grid-cols-2 gap-x-6">
                  {schema.telemetry.map((key) => {
                    const primary = key === schema.primary;
                    return (
                      <div key={key} className="border-t border-line py-3">
                        <span className="eyebrow">{METRICS[key]?.label ?? key}{primary ? " ·главный" : ""}</span>
                        <p className={`data text-xl ${primary ? "text-accent" : "text-ink"}`}>
                          {metricText(key, data, t, loadingT)}
                        </p>
                      </div>
                    );
                  })}
                </div>

                {/* профильные разделы для этого типа (данные — на соответствующих вкладках) */}
                {schema.sections.length > 0 && (
                  <>
                    <span className="eyebrow mt-6">Разделы для этого типа</span>
                    <div className="mt-2 flex flex-wrap gap-2">
                      {schema.sections.map((s) => (
                        <span key={s} style={{ fontSize: 11, padding: "3px 9px", borderRadius: 12,
                          background: "rgba(120,132,153,.12)", color: "#5b6b80" }}>
                          {SECTION_LABEL[s]}
                        </span>
                      ))}
                    </div>
                  </>
                )}

                <p className="data mt-4 text-[0.7rem] leading-relaxed text-ink-faint">
                  Набор параметров подобран под тип агрегата. Недоступные по REST поля
                  (темп. топлива, водитель, обороты) — прочерк. Напряжение бортсети — из /vehicles/state.
                </p>
              </div>
            </div>

            {/* график скорости — только для подвижной техники (стационару плоская линия бесполезна) */}
            {schema.chart && (
              <div className="px-6 py-5">
                <span className="eyebrow">Скорость во времени · км/ч</span>
                <div className="mt-3">
                  {speeds.length > 1
                    ? <LineChart series={speeds} unit="км/ч" />
                    : <p className="data text-sm text-ink-faint">нет точек трека за период</p>}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
