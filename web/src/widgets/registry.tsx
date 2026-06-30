"use client";
// Реестр виджетов гибкого рабочего стола. Виджеты — карточки на примитивах
// atlas/ui + текущий data-слой (серверные агрегаты/скоуп). Без тяжёлых либ.

import { Economics, FuelDetail, Maintenance, Recommendation, SensorHealth, SpeedTrend, ViolationsDetail } from "@/lib/api";
import { Agg, C, DzoRow, aggregate, compactM, mlnTg, ru } from "@/lib/atlas";
import { BarRow, Donut, Gauge, Legend, Td, Th, tableWrap, theadStyle, trRule } from "@/components/atlas/ui";
import { WidgetType } from "./types";

// Данные, доступные всем виджетам (вычислены в page.tsx, со скоупом ДЗО).
export interface WidgetData {
  rows: DzoRow[]; agg: Agg;                 // текущий глобальный скоуп (слайсер)
  allRows: DzoRow[];                        // все ДЗО — для per-widget override
  eco: Economics | null;
  ecoByOrg: Record<string, Economics>;      // экономика по ДЗО — для override
  dzoList: { org_id: string; name: string }[];
  sensor: SensorHealth | null;
  maint: Maintenance | null;
  recs: Recommendation[];
  violDet: ViolationsDetail | null; violDetLoading: boolean;
  fuelDet: FuelDetail | null; fuelDetLoading: boolean; fuelPrice: number;
  trend: SpeedTrend | null; trendLoading: boolean;
  onVehicle: (id: string, name?: string, ts?: number) => void;
  onSelectDzo: (orgId: string) => void;
}
export interface WidgetProps {
  id: string;
  data: WidgetData;
  settings?: Record<string, unknown>;
}
export interface MetricOpt { value: string; label: string }
export interface WidgetMeta {
  type: WidgetType;
  title: string;
  dataKey: string;                 // секция снапшота (для lazy-by-binding)
  component: React.ComponentType<WidgetProps>;
  defaultSize: { w: number; h: number };
  minSize?: { w: number; h: number };
  heavy?: boolean;
  metricOptions?: MetricOpt[];     // настраиваемая метрика (⚙ в edit)
  scopable?: boolean;              // поддерживает per-widget override ДЗО
}

// Per-widget override: settings.scope = org_id одного ДЗО → пересчёт rows/agg/eco.
export function scopedView(data: WidgetData, settings?: Record<string, unknown>): {
  rows: DzoRow[]; agg: Agg; eco: Economics | null;
} {
  const org = settings?.scope as string | undefined;
  if (org) {
    const r = data.allRows.find((x) => x.org_id === org);
    if (r) return { rows: [r], agg: aggregate([r]), eco: data.ecoByOrg[org] ?? null };
  }
  return { rows: data.rows, agg: data.agg, eco: data.eco };
}

const TYPE_COLORS = [C.blue, C.green, C.amber, C.teal, C.greySoft, "#7d6bd0", "#c46aa5", C.faint2];
const muted = (t: string) => <div style={{ fontSize: 11.5, color: C.faint, padding: "8px 0" }}>{t}</div>;

// ---- KPI-плитка (настраиваемая метрика) ----
function KpiTile({ data, settings }: WidgetProps) {
  const { agg: a, eco } = scopedView(data, settings);
  const scoped = !!settings?.scope;
  const m = (settings?.metric as string) || "potential";
  const map: Record<string, { label: string; value: string; color: string }> = {
    potential: { label: "Потенциал экономии", value: mlnTg(a.potential), color: C.green },
    coi: { label: "COI / год", value: eco ? mlnTg(eco.coi_annual_kzt) : "—", color: C.amber },
    fuelCost: { label: "Стоимость топлива", value: mlnTg(a.fuelCost), color: C.ink },
    cpkm: { label: "₸ / км", value: a.rateOk ? ru(a.cpkm) + " ₸" : "—", color: C.teal },
    episodes: { label: "Превышения", value: ru(scoped ? a.episodes : (data.violDet?.total ?? a.episodes)), color: C.amber },
    sensor: { label: "Связь / ТО", value: Math.round(a.sensorPct * 100) + "% · " + a.overdue, color: C.blue },
    veh: { label: "ТС", value: ru(a.veh), color: C.ink },
  };
  const k = map[m] ?? map.potential;
  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", justifyContent: "center" }}>
      <div style={{ fontSize: 10.5, color: C.muted2, fontWeight: 600, textTransform: "uppercase", letterSpacing: ".03em", marginBottom: 6 }}>{k.label}</div>
      <div className="num" style={{ fontSize: 26, fontWeight: 700, color: k.color, lineHeight: 1 }}>{k.value}</div>
    </div>
  );
}

// ---- Структура потерь (economics buckets) ----
function EconomicsW({ data, settings }: WidgetProps) {
  const b = scopedView(data, settings).eco?.buckets ?? [];
  const max = Math.max(1, ...b.map((x) => x.potential_kzt));
  if (!b.length) return muted("Нет данных за период (экономика — холдинг/ДЗО)");
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      {b.map((x) => (
        <div key={x.key}>
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11.5, color: C.muted, marginBottom: 4 }}>
            <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", paddingRight: 8 }}>{x.label}{x.is_estimate ? " ≈" : ""}</span>
            <b className="num" style={{ color: C.ink }}>{compactM(x.potential_kzt)} ₸</b>
          </div>
          <div style={{ height: 9, background: C.track, borderRadius: 2, overflow: "hidden" }}>
            <div style={{ height: "100%", width: `${x.potential_kzt / max * 100}%`, background: x.is_estimate ? C.amber : C.blue }} />
          </div>
        </div>
      ))}
      <Legend items={[{ color: C.blue, label: "измеримо" }, { color: C.amber, label: "≈ оценка" }]} />
    </div>
  );
}

// ---- Бары по ДЗО (настраиваемая метрика) ----
function DzoBars({ data, settings }: WidgetProps) {
  const m = (settings?.metric as string) || "potential";
  const cfg: Record<string, { val: (r: DzoRow) => number; fmt: (r: DzoRow) => string; color: string; ok?: (r: DzoRow) => boolean }> = {
    potential: { val: (r) => r.potential, fmt: (r) => compactM(r.potential), color: C.green },
    cpkm: { val: (r) => r.cpkm, fmt: (r) => ru(r.cpkm) + " ₸", color: C.teal, ok: (r) => r.rateOk },
    l100: { val: (r) => r.l100, fmt: (r) => ru(r.l100, 1) + " л", color: C.blue, ok: (r) => r.rateOk },
    episodes: { val: (r) => r.episodes, fmt: (r) => ru(r.episodes), color: C.amber },
    overdue: { val: (r) => r.overdue, fmt: (r) => String(r.overdue), color: C.red },
  };
  const c = cfg[m] ?? cfg.potential;
  const { rows: srows } = scopedView(data, settings);
  const list = [...srows].filter((r) => (c.ok ? c.ok(r) : c.val(r) > 0)).sort((a, b) => c.val(b) - c.val(a)).slice(0, 8);
  const max = Math.max(1, ...list.map(c.val));
  if (!list.length) return muted("Нет данных");
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
      {list.map((r) => <BarRow key={r.org_id} name={r.name} w={c.val(r) / max * 100} value={c.fmt(r)} color={c.color} onClick={() => data.onSelectDzo(r.org_id)} />)}
    </div>
  );
}

// ---- Парк по ДЗО (donut) ----
function ParkDonut({ data, settings }: WidgetProps) {
  const { rows, agg } = scopedView(data, settings);
  const byVeh = [...rows].sort((a, b) => b.veh - a.veh);
  const top = byVeh.slice(0, 6); const rest = byVeh.slice(6).reduce((a, r) => a + r.veh, 0);
  const total = agg.veh || 1;
  const slices = [
    ...top.map((r, i) => ({ label: r.name, pct: r.veh / total * 100, color: TYPE_COLORS[i % TYPE_COLORS.length] })),
    ...(rest ? [{ label: "Прочие", pct: rest / total * 100, color: C.faint2 }] : []),
  ];
  return <Donut slices={slices} size={92} />;
}

// ---- Sensor Health (gauge + статусы) ----
function SensorW({ data }: WidgetProps) {
  const c = data.sensor?.counts ?? {};
  const total = (c.online ?? 0) + (c.stale ?? 0) + (c.offline ?? 0) || 1;
  const seg = [{ l: "Онлайн", v: c.online ?? 0, color: C.green }, { l: "Молчит", v: c.stale ?? 0, color: C.amber }, { l: "Офлайн", v: c.offline ?? 0, color: C.red }];
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 18 }}>
      <Gauge pct={data.agg.sensorPct} size={96} sub={`${ru(c.online ?? 0)} / ${ru(total)}`} />
      <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 6 }}>
        {seg.map((s, i) => (
          <div key={i} style={{ display: "flex", alignItems: "center", gap: 7, fontSize: 11.5, color: C.muted }}>
            <span style={{ width: 9, height: 9, borderRadius: 2, background: s.color }} /><span style={{ flex: 1 }}>{s.l}</span><b className="num">{ru(s.v)}</b>
          </div>
        ))}
      </div>
    </div>
  );
}

// ---- Контроль ТО ----
function MaintW({ data }: WidgetProps) {
  const c = data.maint?.counts ?? {};
  const byOver = [...data.rows].filter((r) => r.overdue > 0).sort((a, b) => b.overdue - a.overdue).slice(0, 6);
  const max = Math.max(1, ...byOver.map((r) => r.overdue));
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{ display: "flex", gap: 18 }}>
        {[["в норме", c.ok ?? 0, C.green], ["скоро", c["ожидается"] ?? 0, C.amber], ["просрочено", c["просрочено"] ?? 0, C.red]].map(([l, v, col], i) => (
          <div key={i} style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ width: 10, height: 10, borderRadius: "50%", background: col as string }} />
            <div><div className="num" style={{ fontSize: 18, fontWeight: 700 }}>{ru(v as number)}</div><div style={{ fontSize: 10.5, color: C.muted2 }}>{l as string}</div></div>
          </div>
        ))}
      </div>
      {byOver.length ? <div style={{ display: "flex", flexDirection: "column", gap: 7 }}>
        {byOver.map((r) => <BarRow key={r.org_id} name={r.name} w={r.overdue / max * 100} value={String(r.overdue)} color={C.amber} h={12} onClick={() => data.onSelectDzo(r.org_id)} />)}
      </div> : null}
    </div>
  );
}

// ---- Топ нарушителей (recommendations) ----
function RecsW({ data }: WidgetProps) {
  const top = [...data.recs].sort((a, b) => b.episodes - a.episodes).slice(0, 8);
  const max = Math.max(1, ...top.map((r) => r.episodes));
  if (!top.length) return muted("Нет нарушений");
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {top.map((r) => <BarRow key={r.terminal_id} name={r.name || r.terminal_id} w={r.episodes / max * 100} value={ru(r.episodes)} color={r.worst_severity === "грубое" ? C.red : C.amber} h={13} onClick={() => data.onVehicle(r.terminal_id, r.name)} />)}
    </div>
  );
}

// ---- Матрица по ДЗО ----
function MatrixW({ data, settings }: WidgetProps) {
  const rows = [...scopedView(data, settings).rows].sort((a, b) => b.veh - a.veh);
  return tableWrap(<>
    <thead><tr style={theadStyle}><Th>ДЗО</Th><Th right>ТС</Th><Th right>Потенциал ₸</Th><Th right>₸/км</Th><Th right>Превышения</Th><Th right>Связь</Th><Th right>ТО</Th></tr></thead>
    <tbody>
      {rows.map((r) => (
        <tr key={r.org_id} style={{ ...trRule, cursor: "pointer" }} onClick={() => data.onSelectDzo(r.org_id)}>
          <Td bold>{r.name}</Td><Td right color={C.muted}>{ru(r.veh)}</Td>
          <Td right color={C.green}>{r.potential ? compactM(r.potential) : "—"}</Td>
          <Td right color={r.rateOk ? undefined : C.faint2}>{r.rateOk ? ru(r.cpkm) : "—"}</Td>
          <Td right>{ru(r.episodes)}</Td>
          <Td right color={r.sensorPct < 0.8 ? C.amber : C.green}><b>{Math.round(r.sensorPct * 100)}%</b></Td>
          <Td right color={r.overdue > 0 ? C.red : C.muted}>{r.overdue}</Td>
        </tr>
      ))}
    </tbody>
  </>);
}

// ---- Нарушения (детальная, серверные агрегаты — без BUG-1) ----
function ViolationsW({ data }: WidgetProps) {
  if (data.violDetLoading || !data.violDet) return muted(data.violDetLoading ? "Загрузка…" : "Нет данных");
  const rows = data.violDet.rows.slice(0, 60);
  const dt = (ts: number) => ts ? new Date(ts * 1000).toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }) : "—";
  return tableWrap(<>
    <thead><tr style={theadStyle}><Th>Дата</Th><Th>ТС</Th><Th>Локация</Th><Th right>Макс</Th><Th right>Лимит</Th><Th right>Штраф ₸</Th></tr></thead>
    <tbody>
      {rows.map((r, i) => (
        <tr key={i} style={{ ...trRule, cursor: "pointer" }} onClick={() => data.onVehicle(r.vehicleId, r.vehicle, r.start_ts)}>
          <Td color={C.muted}>{dt(r.start_ts)}</Td><Td bold>{r.vehicle || r.vehicleId}</Td>
          <Td color={C.muted}>{r.geozone}</Td><Td right color={C.red} bold>{ru(r.max_speed_kmh, 1)}</Td>
          <Td right color={C.muted}>{r.limit_kmh}</Td><Td right>{r.fine_kzt ? ru(r.fine_kzt) : "—"}</Td>
        </tr>
      ))}
    </tbody>
  </>);
}

// ---- Топливо (детальная) ----
function FuelW({ data }: WidgetProps) {
  if (data.fuelDetLoading || !data.fuelDet) return muted(data.fuelDetLoading ? "Загрузка…" : "Нет данных");
  const rows = data.fuelDet.rows.slice(0, 60);
  const fact = (r: typeof rows[number]) => r.mode === "mh" ? (r.fact_lmh != null ? ru(r.fact_lmh, 1) + " л/мч" : "—") : (r.fact_l100 != null ? ru(r.fact_l100, 1) + " л/100" : "—");
  return tableWrap(<>
    <thead><tr style={theadStyle}><Th>ТС</Th><Th right>Пробег</Th><Th right>Расход л</Th><Th right>Факт</Th><Th right>Перерасход ₸</Th></tr></thead>
    <tbody>
      {rows.map((r) => (
        <tr key={r.vehicleId} style={{ ...trRule, cursor: "pointer" }} onClick={() => data.onVehicle(r.vehicleId, r.vehicle)}>
          <Td bold>{r.vehicle || r.vehicleId}</Td><Td right color={C.muted}>{ru(r.mileage_km)}</Td>
          <Td right bold>{ru(r.fuel_l)}</Td><Td right color={fact(r) === "—" ? C.faint2 : undefined}>{fact(r)}</Td>
          <Td right color={r.over_l == null ? C.faint2 : r.over_l > 0 ? C.red : C.green} bold={!!r.over_l}>{r.over_l == null ? "—" : (r.over_l > 0 ? "+" : "−") + compactM(Math.abs(r.over_l) * data.fuelPrice)}</Td>
        </tr>
      ))}
    </tbody>
  </>);
}

// ---- Повторяемость (хитмап ТС×месяц, эпизоды) ----
function SpeedTrendW({ data }: WidgetProps) {
  const t = data.trend;
  if (data.trendLoading || !t) return muted(data.trendLoading ? "Считаем матрицу…" : "Нет данных");
  const months = t.months;
  const rows = [...t.rows].sort((a, b) => b.all - a.all).slice(0, 40);
  const maxCell = Math.max(1, ...rows.flatMap((r) => months.map((m) => r.byMonth[m] ?? 0)));
  const MR = ["янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"];
  const ml = (m: string) => { const [y, mm] = m.split("-"); return `${MR[+mm - 1] ?? mm} ${y.slice(2)}`; };
  const heat = (v: number) => {
    if (!v) return { bg: C.track, ink: C.faint2 };
    const x = v / maxCell, g = [228, 243, 234], a = [247, 232, 200], r = [212, 69, 59];
    const mix = (p: number[], q: number[], k: number) => p.map((c, i) => Math.round(c + (q[i] - c) * k));
    const rgb = x < 0.5 ? mix(g, a, x / 0.5) : mix(a, r, (x - 0.5) / 0.5);
    return { bg: `rgb(${rgb.join(",")})`, ink: x > 0.62 ? "#fff" : C.ink };
  };
  return (
    <div style={{ overflowX: "auto" }}>
      <div style={{ minWidth: 520 }}>
        <div style={{ display: "flex", borderBottom: `1px solid ${C.line}`, paddingBottom: 5 }}>
          <div style={{ width: 180, flexShrink: 0, fontSize: 10.5, color: C.muted2, textTransform: "uppercase" }}>ТС</div>
          {months.map((m) => <div key={m} style={{ flex: 1, textAlign: "center", fontSize: 10, color: C.muted2 }}>{ml(m)}</div>)}
        </div>
        {rows.map((r) => (
          <div key={r.vehicleId} onClick={() => data.onVehicle(r.vehicleId, r.name)} style={{ display: "flex", alignItems: "center", padding: "2px 0", cursor: "pointer" }}>
            <div style={{ width: 180, flexShrink: 0, fontSize: 11, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", paddingRight: 6 }}>{r.name}</div>
            {months.map((m) => { const v = r.byMonth[m] ?? 0; const h = heat(v); return <div key={m} className="num" style={{ flex: 1, margin: "0 2px", height: 20, borderRadius: 3, background: h.bg, color: h.ink, fontSize: 10, fontWeight: 600, display: "flex", alignItems: "center", justifyContent: "center" }}>{v || ""}</div>; })}
          </div>
        ))}
      </div>
    </div>
  );
}

const KPI_METRICS: MetricOpt[] = [
  { value: "potential", label: "Потенциал экономии" }, { value: "coi", label: "COI / год" },
  { value: "fuelCost", label: "Стоимость топлива" }, { value: "cpkm", label: "₸ / км" },
  { value: "episodes", label: "Превышения" }, { value: "sensor", label: "Связь / ТО" },
  { value: "veh", label: "ТС" },
];
const BAR_METRICS: MetricOpt[] = [
  { value: "potential", label: "Потенциал ₸" }, { value: "cpkm", label: "₸ / км" },
  { value: "l100", label: "л/100" }, { value: "episodes", label: "Превышения" }, { value: "overdue", label: "Просрочено ТО" },
];

export const WIDGETS: Record<WidgetType, WidgetMeta> = {
  kpiTile: { type: "kpiTile", title: "KPI-плитка", dataKey: "dashboard", component: KpiTile, defaultSize: { w: 3, h: 1 }, minSize: { w: 2, h: 1 }, metricOptions: KPI_METRICS, scopable: true },
  economics: { type: "economics", title: "Структура потерь", dataKey: "economics", component: EconomicsW, defaultSize: { w: 4, h: 2 }, minSize: { w: 3, h: 2 }, scopable: true },
  dzoBars: { type: "dzoBars", title: "Бары по ДЗО", dataKey: "dashboard", component: DzoBars, defaultSize: { w: 5, h: 2 }, minSize: { w: 3, h: 2 }, metricOptions: BAR_METRICS, scopable: true },
  parkDonut: { type: "parkDonut", title: "Парк по ДЗО", dataKey: "dashboard", component: ParkDonut, defaultSize: { w: 4, h: 2 }, minSize: { w: 3, h: 2 }, scopable: true },
  sensorHealth: { type: "sensorHealth", title: "Качество данных", dataKey: "sensor_health", component: SensorW, defaultSize: { w: 4, h: 2 }, minSize: { w: 3, h: 2 } },
  maintenance: { type: "maintenance", title: "Контроль ТО", dataKey: "maintenance", component: MaintW, defaultSize: { w: 5, h: 3 }, minSize: { w: 4, h: 2 } },
  recommendations: { type: "recommendations", title: "Топ нарушителей", dataKey: "recommendations", component: RecsW, defaultSize: { w: 5, h: 3 }, minSize: { w: 3, h: 2 } },
  matrix: { type: "matrix", title: "Матрица по ДЗО", dataKey: "dashboard", component: MatrixW, defaultSize: { w: 12, h: 3 }, minSize: { w: 6, h: 2 }, scopable: true },
  violations: { type: "violations", title: "Нарушения (детально)", dataKey: "violations", component: ViolationsW, defaultSize: { w: 7, h: 4 }, minSize: { w: 5, h: 3 } },
  fuel: { type: "fuel", title: "Топливо (детально)", dataKey: "fuel", component: FuelW, defaultSize: { w: 7, h: 4 }, minSize: { w: 5, h: 3 } },
  speedTrend: { type: "speedTrend", title: "Повторяемость", dataKey: "speed_trend", component: SpeedTrendW, defaultSize: { w: 12, h: 4 }, minSize: { w: 6, h: 3 } },
};

export const WIDGET_LIST: WidgetMeta[] = Object.values(WIDGETS);
