// Data-driven схема карточки ТС по типу агрегата: набор метрик/секций подстраивается
// под тип (буровая/компрессор/самосвал/АГП/каротаж/АТЗ/…). Один реестр метрик +
// схема на тип → карточка рендерит блоки без хардкода N карточек. Новый тип = одна
// запись в CARD_SCHEMA. Метрики ссылаются на поля payload (state/telemetry/derived).

import { VehicleDetail } from "./api";

type Tele = Record<string, number | null>;
export type MetricSrc = "state" | "telemetry" | "derived";

export interface MetricDef {
  label: string;
  unit: string;
  digits?: number;
  get: (d: VehicleDetail, t: Tele) => number | boolean | null | undefined;
}

// Единый реестр метрик (переиспользуется схемами разных типов).
export const METRICS: Record<string, MetricDef> = {
  voltage:   { label: "Напряжение бортсети", unit: "В", digits: 1, get: (d) => d.state?.voltage },
  ignition:  { label: "Зажигание", unit: "", get: (d) => d.state?.ignition },
  curSpeed:  { label: "Тек. скорость", unit: "км/ч", digits: 1, get: (d) => d.state?.current_speed },
  curFuel:   { label: "Тек. топливо", unit: "л", digits: 1, get: (d) => {
                 const v = d.state?.current_fuel; return v != null && v >= 0 ? v : null; } },
  maxSpeed:  { label: "Макс. скорость", unit: "км/ч", digits: 1,
               get: (d, t) => t.max_speed_kmh ?? d.track_max_speed },
  mileage:   { label: "Пробег", unit: "км", digits: 1, get: (_d, t) => t.mileage_km },
  engHours:  { label: "Моточасы", unit: "ч", digits: 1, get: (_d, t) => t.engine_hours },
  fuel:      { label: "Топливо", unit: "л", digits: 1, get: (_d, t) => t.fuel_l },
  fuelIdle:  { label: "Топливо простоя", unit: "л", digits: 1, get: (_d, t) => t.fuel_idle_l },
  speedKm:   { label: "Пробег с превыш.", unit: "км", digits: 1, get: (_d, t) => t.speeding_mileage_km },
  lPerMh:    { label: "Расход л/моточас", unit: "л/мч", digits: 1,
               get: (_d, t) => (t.engine_hours ? (t.fuel_l ?? 0) / t.engine_hours : null) },
  lPer100:   { label: "Расход л/100 км", unit: "л/100км", digits: 1,
               get: (_d, t) => (t.mileage_km ? (t.fuel_l ?? 0) / t.mileage_km * 100 : null) },
  idleShare: { label: "Доля простоя", unit: "%", digits: 0,
               get: (_d, t) => (t.engine_hours ? (t.fuel_idle_l ?? 0) / (t.fuel_l || 1) * 100 : null) },
  delivery:  { label: "Выдача ГСМ", unit: "л", digits: 1, get: (_d, t) => t.delivery_l },
};

export type SectionKey = "maint" | "tyres" | "speeding" | "onsite" | "balance";
export type MapWeight = "full" | "compact" | "hidden";

export interface CardSchema {
  primary: string;                 // ключ подсвеченной метрики
  mapWeight: MapWeight;
  online: string[];                // блок «Состояние·онлайн»
  telemetry: string[];             // тип-специфичный блок телеметрии
  sections: SectionKey[];          // профильные секции (ТО/шины/скорость/работа на месте/баланс)
  chart: boolean;                  // показывать график скорости
}

const MOBILE_ONLINE = ["voltage", "ignition", "curSpeed", "curFuel"];
const STATIC_ONLINE = ["voltage", "ignition", "curFuel"];

// Схемы по типам (KPI-набор ранжирован под специфику агрегата — от панели специалистов).
export const CARD_SCHEMA: Record<string, CardSchema> = {
  drill_rig: { primary: "lPerMh", mapWeight: "compact", online: STATIC_ONLINE,
    telemetry: ["engHours", "fuel", "lPerMh", "fuelIdle"], sections: ["maint", "onsite"], chart: false },
  drill_rig_mobile: { primary: "lPerMh", mapWeight: "full", online: MOBILE_ONLINE,
    telemetry: ["engHours", "mileage", "lPerMh", "lPer100", "fuel", "speedKm"],
    sections: ["maint", "tyres", "speeding"], chart: true },
  compressor: { primary: "lPerMh", mapWeight: "compact", online: STATIC_ONLINE,
    telemetry: ["engHours", "fuel", "lPerMh", "fuelIdle"], sections: ["maint", "onsite"], chart: false },
  logging_station: { primary: "engHours", mapWeight: "full", online: MOBILE_ONLINE,
    telemetry: ["engHours", "mileage", "maxSpeed", "fuel"], sections: ["maint", "speeding"], chart: true },
  agp: { primary: "engHours", mapWeight: "compact", online: MOBILE_ONLINE,
    telemetry: ["engHours", "mileage", "fuel", "lPerMh"], sections: ["maint"], chart: true },
  tanker: { primary: "delivery", mapWeight: "full", online: MOBILE_ONLINE,
    telemetry: ["mileage", "fuel", "lPer100", "maxSpeed"], sections: ["balance", "speeding", "maint"], chart: true },
  dump_truck: { primary: "lPer100", mapWeight: "full", online: MOBILE_ONLINE,
    telemetry: ["mileage", "maxSpeed", "lPer100", "fuel", "speedKm", "fuelIdle"],
    sections: ["speeding", "tyres", "maint"], chart: true },
  semi_truck: { primary: "lPer100", mapWeight: "full", online: MOBILE_ONLINE,
    telemetry: ["mileage", "maxSpeed", "lPer100", "fuel", "speedKm"],
    sections: ["speeding", "tyres", "maint"], chart: true },
  offroad_special: { primary: "lPer100", mapWeight: "full", online: MOBILE_ONLINE,
    telemetry: ["mileage", "maxSpeed", "lPer100", "engHours", "speedKm", "fuel"],
    sections: ["speeding", "tyres", "maint"], chart: true },
  loader: { primary: "lPerMh", mapWeight: "compact", online: STATIC_ONLINE,
    telemetry: ["engHours", "fuel", "lPerMh", "fuelIdle"], sections: ["maint", "tyres", "onsite"], chart: false },
  excavator: { primary: "lPerMh", mapWeight: "compact", online: STATIC_ONLINE,
    telemetry: ["engHours", "fuel", "lPerMh", "fuelIdle"], sections: ["maint", "onsite"], chart: false },
  crane: { primary: "lPerMh", mapWeight: "compact", online: STATIC_ONLINE,
    telemetry: ["engHours", "fuel", "lPerMh", "fuelIdle"], sections: ["maint", "onsite"], chart: false },
  tractor: { primary: "lPerMh", mapWeight: "compact", online: MOBILE_ONLINE,
    telemetry: ["engHours", "mileage", "fuel", "lPerMh"], sections: ["maint", "onsite"], chart: true },
  refuse_truck: { primary: "lPerMh", mapWeight: "full", online: MOBILE_ONLINE,
    telemetry: ["mileage", "engHours", "lPerMh", "lPer100", "fuel", "fuelIdle"],
    sections: ["maint", "tyres", "onsite"], chart: true },
  vacuum_sweeper: { primary: "lPerMh", mapWeight: "full", online: MOBILE_ONLINE,
    telemetry: ["mileage", "engHours", "lPerMh", "lPer100", "fuel"],
    sections: ["maint", "tyres"], chart: true },
  bus: { primary: "lPer100", mapWeight: "full", online: MOBILE_ONLINE,
    telemetry: ["mileage", "maxSpeed", "lPer100", "fuel", "speedKm", "fuelIdle"],
    sections: ["speeding", "maint", "tyres"], chart: true },
  car: { primary: "lPer100", mapWeight: "full", online: MOBILE_ONLINE,
    telemetry: ["mileage", "maxSpeed", "lPer100", "fuel", "speedKm"],
    sections: ["speeding", "maint"], chart: true },
  truck: { primary: "lPer100", mapWeight: "full", online: MOBILE_ONLINE,
    telemetry: ["mileage", "maxSpeed", "lPer100", "fuel", "speedKm", "fuelIdle"],
    sections: ["speeding", "tyres", "maint"], chart: true },
  other: { primary: "maxSpeed", mapWeight: "full", online: MOBILE_ONLINE,
    telemetry: ["maxSpeed", "mileage", "engHours", "fuel", "fuelIdle", "speedKm"],
    sections: ["maint"], chart: true },
};

export const schemaFor = (t?: string): CardSchema => CARD_SCHEMA[t ?? "other"] ?? CARD_SCHEMA.other;

// Отформатировать значение метрики: «— » (нет данных) / «…» (грузится) / «12,3 ед».
export function metricText(
  key: string, d: VehicleDetail | null, t: Tele, loading: boolean,
): string {
  const m = METRICS[key];
  if (!m) return "—";
  if (!d) return "…";
  const v = m.get(d, t);
  if (typeof v === "boolean") return v ? "вкл" : "выкл";
  if (v == null || Number.isNaN(v)) return loading ? "…" : "—";
  const n = new Intl.NumberFormat("ru-RU", {
    minimumFractionDigits: m.digits ?? 0, maximumFractionDigits: m.digits ?? 0,
  }).format(v as number);
  return m.unit ? `${n} ${m.unit}` : n;
}
