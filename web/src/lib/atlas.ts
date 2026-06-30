// Atlas BI — палитра, селекторы и форматтеры для Power-BI-стиля дашборда.
// Дизайн-источник: Claude Design «Omnicomm money tab / Atlas BI».
// Все числа — РЕАЛЬНЫЕ из снапшота (org.kpi уже сроллапен по поддереву).

import {
  Economics, Maintenance, OrgNode, Recommendation, SensorHealth, ViolationRow,
} from "./api";
import { indexOrgs, subtreeOrgIds } from "./scope";

// ---- Палитра (1:1 с дизайном) ----
export const C = {
  bg: "#eef1f5", ink: "#1b2733", panel: "#fff",
  line: "#e6e9ee", line2: "#dfe4ea", railBg: "#e7ebf1", railLine: "#dbe1e9",
  headRule: "#eef1f5", track: "#f2f4f8",
  blue: "#1f6fd6", red: "#d4453b", green: "#2e9e5b", amber: "#d39a1e", teal: "#0c97a4",
  ink2: "#3a4a5e", muted: "#5b6b80", muted2: "#748499", faint: "#8a98ac", faint2: "#9aa7ba",
  excel: "#107c41",
  blueSoft: "#9bbce8", greySoft: "#8a98b0",
} as const;

export const FONT = "'Segoe UI',Roboto,system-ui,sans-serif";

// ---- Форматтеры ----
const NB = " ";
export function compactM(v: number): string {
  v = v ?? 0;
  const a = Math.abs(v);
  if (a >= 1e6) return (v / 1e6).toFixed(1).replace(".", ",") + "М";
  if (a >= 1e3) return Math.round(v / 1e3) + "к";
  return Math.round(v).toLocaleString("ru-RU");
}
export const mlnTg = (v: number) => compactM(v) + NB + "₸";
export const ru = (v: number, frac = 0) =>
  new Intl.NumberFormat("ru-RU", { minimumFractionDigits: frac, maximumFractionDigits: frac })
    .format(v ?? 0);

// SVG-полилиния спарклайна (0..70 × 0..24), arr — последние точки.
export function spark(arr: number[]): string {
  const m = Math.max(...arr) || 1; const n = arr.length;
  return arr.map((v, i) => (i / (n - 1) * 70).toFixed(1) + "," + (24 - v / m * 22).toFixed(1)).join(" ");
}

// ---- Селекторы организаций (ДЗО) ----
// Минимальный мобильный пробег ДЗО, при котором ₸/км и л/100 показательны.
// Ниже — техника стоит/работает на моточасах (АЗС/генераторы/спецтехника):
// «fuel / ≈0 км» даёт абсурдный л/100 → показываем «—» (вентиль доверия).
export const MIN_RATE_KM = 300;

export interface DzoRow {
  org_id: string; name: string; veh: number;
  potential: number; fuelCost: number; km: number; fuelL: number;
  // ₸/км и л/100 — по МОБИЛЬНОЙ технике (движущейся), деньги/топливо — по всем ТС.
  mobileKm: number; mobileFuelL: number; price: number;
  cpkm: number; l100: number; rateOk: boolean;
  episodes: number; pubEp: number; techEp: number;
  online: number; sensorTotal: number; sensorPct: number;
  overdue: number;
}
export interface Agg {
  veh: number; potential: number; fuelCost: number; km: number; fuelL: number;
  mobileKm: number; mobileFuelL: number;
  cpkm: number; l100: number; rateOk: boolean;
  episodes: number; pubEp: number; techEp: number;
  online: number; sensorTotal: number; sensorPct: number; overdue: number;
}

// Узлы «ДЗО» для слайсера/баров = непосредственные подразделения текущего корня.
// Холдинг КАП имеет единственного посредника (Казатомпром) — спускаемся сквозь него
// к 24 ДЗО. Скоуп-корень (ДЗО/подорг) → его прямые дети; лист без детей → сам узел.
export function dzoNodes(orgs: OrgNode[]): OrgNode[] {
  const root = orgs[0];
  if (!root) return [];
  let node = root;
  while (node.children?.length === 1) node = node.children[0];   // пропуск посредника
  const list = node.children?.length ? node.children : [root];
  return [...list].sort((a, b) => b.vehicle_count - a.vehicle_count);
}

export function buildDzoRows(
  orgs: OrgNode[], recs: Recommendation[], sensor: SensorHealth | null,
  maint: Maintenance | null, vehicleOrg: Record<string, string>,
): DzoRow[] {
  const byId = indexOrgs(orgs);
  return dzoNodes(orgs).map((n) => {
    const ids = subtreeOrgIds(byId, n.org_id);
    let episodes = 0, pubEp = 0, techEp = 0;
    for (const r of recs) if (ids.has(vehicleOrg[r.terminal_id])) {
      episodes += r.episodes; pubEp += r.public_episodes; techEp += r.tech_episodes;
    }
    let online = 0, sensorTotal = 0;
    for (const t of sensor?.terminals ?? []) if (ids.has(vehicleOrg[t.terminal_id])) {
      sensorTotal++; if (t.status === "online") online++;
    }
    let overdue = 0;
    for (const it of maint?.items ?? []) if (ids.has(vehicleOrg[it.terminal_id]) && it.status === "просрочено") overdue++;
    const k = n.kpi;
    const mobileKm = +k.mobile_mileage_km || 0;
    const mobileFuelL = +k.mobile_fuel_l || 0;
    const price = +k.fuel_price_kzt || 0;
    const rateOk = mobileKm >= MIN_RATE_KM && (+k.mobile_count || 0) > 0;
    return {
      org_id: n.org_id, name: n.name, veh: n.vehicle_count,
      potential: +k.potential_savings || 0, fuelCost: +k.total_fuel_cost || 0,
      km: +k.total_mileage_km || 0, fuelL: +k.total_fuel_l || 0,
      mobileKm, mobileFuelL, price,
      cpkm: rateOk ? mobileFuelL * price / mobileKm : 0,
      l100: rateOk ? mobileFuelL / mobileKm * 100 : 0,
      rateOk,
      episodes, pubEp, techEp, online, sensorTotal,
      sensorPct: sensorTotal ? online / sensorTotal : 0, overdue,
    };
  });
}

export function aggregate(rows: DzoRow[]): Agg {
  const s = (f: (r: DzoRow) => number) => rows.reduce((a, r) => a + f(r), 0);
  const km = s((r) => r.km), fuelL = s((r) => r.fuelL), fuelCost = s((r) => r.fuelCost);
  const mobileKm = s((r) => r.mobileKm), mobileFuelL = s((r) => r.mobileFuelL);
  const price = rows.find((r) => r.price)?.price ?? 0;
  const online = s((r) => r.online), sensorTotal = s((r) => r.sensorTotal);
  const rateOk = mobileKm >= MIN_RATE_KM;
  return {
    veh: s((r) => r.veh), potential: s((r) => r.potential), fuelCost, km, fuelL,
    mobileKm, mobileFuelL,
    cpkm: rateOk ? mobileFuelL * price / mobileKm : 0,
    l100: rateOk ? mobileFuelL / mobileKm * 100 : 0, rateOk,
    episodes: s((r) => r.episodes), pubEp: s((r) => r.pubEp), techEp: s((r) => r.techEp),
    online, sensorTotal, sensorPct: sensorTotal ? online / sensorTotal : 0,
    overdue: s((r) => r.overdue),
  };
}

// Превышения по геозонам (для страницы «Скоростной режим»).
export interface ZoneRow { name: string; limit: string; max: number; events: number }
export function zonesFromViol(rows: ViolationRow[]): ZoneRow[] {
  const m = new Map<string, { limit: number | null; max: number; events: number }>();
  for (const r of rows) {
    const key = r.geozone || "Без геозоны";
    const cur = m.get(key) ?? { limit: r.limit_kmh, max: 0, events: 0 };
    cur.events++; cur.max = Math.max(cur.max, r.excess_kmh ?? 0);
    if (cur.limit == null) cur.limit = r.limit_kmh;
    m.set(key, cur);
  }
  return [...m.entries()]
    .map(([name, v]) => ({ name, limit: v.limit ? v.limit + " км/ч" : "—", max: Math.round(v.max), events: v.events }))
    .sort((a, b) => b.events - a.events);
}

// Разбивка превышений по тяжести (по величине превышения).
export function severityBuckets(rows: ViolationRow[]): { s6: number; s20: number; s40: number } {
  let s6 = 0, s20 = 0, s40 = 0;
  for (const r of rows) {
    const e = r.excess_kmh ?? 0;
    if (e >= 40) s40++; else if (e >= 20) s20++; else s6++;
  }
  return { s6, s20, s40 };
}
