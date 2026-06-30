// Клиент FastAPI-моста. Чтения берут готовый снапшот из кэша (мгновенно),
// синк запускается фоном и стримит прогресс по SSE.

// Пусто (прод) → относительные пути той же origin, проксируются на FastAPI
// через реверс-прокси :8535 (без CORS). Dev задаёт абсолютный URL в .env.local.
export const API = process.env.NEXT_PUBLIC_API_URL ?? "";

// ---- Типы контракта ----
export interface Kpi {
  vehicles_total: number;
  vehicles_with_data: number;
  total_mileage_km: number;
  total_fuel_l: number;
  weighted_fuel_per_100km: number;
  fuel_idle_share: number;
  idle_hours_share: number;
  max_speed_kmh: number;
  total_fuel_cost: number;
  idle_fuel_cost: number;
  potential_savings: number;
  fuel_price_kzt: number;
  [k: string]: number | boolean;
}

export interface OrgNode {
  org_id: string;
  name: string;
  parent_id: string | null;
  level: string | null;
  type: string | null;
  vehicle_count: number;
  direct_vehicle_count: number;
  kpi: Kpi;
  children: OrgNode[];
}

export interface Bucket {
  key: string;
  label: string;
  existing_kzt: number;
  potential_kzt: number;
  is_estimate: boolean;
  note: string;
}
export interface Economics {
  period_days: number;
  buckets: Bucket[];
  total_existing_kzt: number;
  total_potential_kzt: number;
  coi_monthly_kzt: number;
  coi_annual_kzt: number;
  worst_vehicles: [string, number][];
}

export interface Recommendation {
  terminal_id: string;
  name: string;
  episodes: number;
  max_excess: number;
  worst_severity: string;
  public_episodes: number;
  tech_episodes: number;
  worst_article: string | null;
  statutory_rate_kzt?: number | null;
  risk_note?: string;
  action?: string;
  text: string;
}

export interface GeoFeature {
  name: string;
  kind: "polygon" | "line";
  path: [number, number][];
  color: [number, number, number];
  limit: number | null;
  width: number;
  tooltip: string;
}

export interface TerminalHealth {
  terminal_id: string;
  name: string | null;
  status: "online" | "stale" | "offline" | "unknown";
  last_seen: number | null;
  age_seconds: number | null;
  receive_data: boolean | null;
}
export interface MissingCap {
  terminal_id: string;
  name: string | null;
  missing: string[];
  voltage?: number | null;
  power?: "ok" | "low" | "critical" | "unknown";
  power_verdict?: string;
}
export interface SensorHealth {
  terminals: TerminalHealth[];
  counts: Record<string, number>;
  missing_capabilities: MissingCap[];
  power?: Record<string, number>;
  level: string;
}

export interface MaintenanceItem {
  terminal_id: string;
  name: string | null;
  status: string;
  mh_since: number;
  km_since: number;
  mh_left: number | null;
  km_left: number | null;
  reason: string;
}
export interface Maintenance {
  counts: Record<string, number>;
  items: MaintenanceItem[];
  note: string;
}

// ---- Отчётные формы паритета (kb-14) ----
export interface VisitRow {
  vehicle_id: string; vehicle: string; geozone: string;
  enter_ts: number | null; exit_ts: number | null; duration_s: number;
  max_speed_kmh: number | null; mileage_km: number | null; speeding_km: number | null;
}
export interface GeozoneSummary { geozone: string; visits: number; vehicles: number; total_hours: number }
export interface GeozoneVisits { count: number; rows: VisitRow[]; by_geozone: GeozoneSummary[] }

export interface FleetRow {
  vehicle_id: string; vehicle: string; org_id: string | null;
  mileage_km: number | null; fuel_l: number | null; fuel_per_100km: number | null;
  fuel_idle_l: number | null; engine_hours: number | null; engine_idle_hours: number | null;
  max_speed_kmh: number | null; speeding_count: number | null; speeding_mileage_km: number | null;
  has_data: boolean;
}
export interface FleetTable { count: number; rows: FleetRow[] }

export interface ViolationRow {
  vehicle_id: string; vehicle: string; type: string; geozone: string | null;
  limit_kmh: number | null; max_speed_kmh: number | null; excess_kmh: number | null;
  start_ts: number | null; severity: string | null; koap_article: string | null;
  fine_kzt: number | null; detail?: string;
}
export interface ViolationsForm { count: number; rows: ViolationRow[]; by_type: Record<string, number> }

export interface FuelRow {
  vehicle_id: string; vehicle: string;
  refuel_l: number | null; drain_l: number | null; delivery_l: number | null;
  fuel_l: number | null; vol_start_l: number | null; vol_end_l: number | null;
  vol_min_l: number | null; vol_max_l: number | null;
}
export interface FuelForm {
  count: number; rows: FuelRow[];
  totals: { refuel_l: number; delivery_l: number };
}

export interface TrackPoint { lat: number; lon: number; speed: number; ts: number; sat?: number }
export interface VehicleDetail {
  terminal_id: string;
  name: string | null;
  period: { start_ts: number; end_ts: number };
  track: TrackPoint[];
  speed_series: { ts: number; speed: number }[];
  last: TrackPoint | null;
  track_points: number;
  track_max_speed: number;
  state: {
    voltage?: number | null;
    address?: string | null;
    ignition?: boolean | null;
    current_speed?: number | null;
    current_fuel?: number | null;
    last_data_ts?: number | null;
    sat?: number | null;
  };
  telemetry: Record<string, number | null>;
}

export interface Meta {
  period_key: string;
  synced_at: number;
  label: string;
}
export interface Dashboard {
  period: { start_ts: number; end_ts: number; label: string } | null;
  fleet: { vehicles: number; with_data: number } | null;
  orgs: OrgNode[];
  economics: Economics | null;
  meta: Meta | null;
}

export interface Job {
  id: string;
  status: "pending" | "running" | "done" | "error";
  pct: number;
  message: string;
  error: string | null;
  result: Record<string, unknown> | null;
  elapsed_s: number;
  already_running?: boolean;
}

// ---- HTTP ----
async function get<T>(path: string): Promise<T> {
  const r = await fetch(`${API}${path}`, { cache: "no-store" });
  if (!r.ok) throw new Error(`${path} → ${r.status}`);
  return r.json();
}

export const getDashboard = (key?: string) =>
  get<Dashboard>(`/api/dashboard${key ? `?period_key=${key}` : ""}`);
export const getGeozones = (key?: string) =>
  get<{ geozones: GeoFeature[]; meta: Meta | null }>(
    `/api/geozones${key ? `?period_key=${key}` : ""}`,
  );
export const getRecommendations = (key?: string) =>
  get<{ recommendations: Recommendation[]; vehicle_org: Record<string, string>; meta: Meta | null }>(
    `/api/recommendations${key ? `?period_key=${key}` : ""}`,
  );
export const getSensorHealth = (key?: string) =>
  get<{ sensor_health: SensorHealth | null; meta: Meta | null }>(
    `/api/sensor-health${key ? `?period_key=${key}` : ""}`,
  );
export const getMaintenance = (key?: string) =>
  get<{ maintenance: Maintenance | null; meta: Meta | null }>(
    `/api/maintenance${key ? `?period_key=${key}` : ""}`,
  );
export const getGeozoneVisits = (key?: string) =>
  get<{ geozone_visits: GeozoneVisits | null; vehicle_org: Record<string, string>; meta: Meta | null }>(
    `/api/geozone-visits${key ? `?period_key=${key}` : ""}`,
  );
export const getFleetTable = (key?: string) =>
  get<{ fleet_table: FleetTable | null; vehicle_org: Record<string, string>; meta: Meta | null }>(
    `/api/fleet-table${key ? `?period_key=${key}` : ""}`,
  );
export const getViolationsForm = (key?: string) =>
  get<{ violations: ViolationsForm | null; vehicle_org: Record<string, string>; meta: Meta | null }>(
    `/api/violations${key ? `?period_key=${key}` : ""}`,
  );
export const getFuel = (key?: string) =>
  get<{ fuel: FuelForm | null; vehicle_org: Record<string, string>; meta: Meta | null }>(
    `/api/fuel${key ? `?period_key=${key}` : ""}`,
  );
// Прямая ссылка на Excel-выгрузку (скачивание браузером).
export const excelUrl = (key?: string) =>
  `${API}/api/dashboard.xlsx${key ? `?period_key=${key}` : ""}`;

export const getVehicle = (id: string, range?: { start_ts: number; end_ts: number }) =>
  get<VehicleDetail>(
    `/api/vehicle/${id}${range ? `?start_ts=${range.start_ts}&end_ts=${range.end_ts}` : ""}`,
  );
export const getVehicleTelemetry = (id: string) =>
  get<{ terminal_id: string; telemetry: Record<string, number | null> }>(
    `/api/vehicle/${id}/telemetry`,
  );

export const getSnapshots = () => get<Meta[]>(`/api/snapshots`);

// ---- Повторяемость / тренд превышений (вкладка speed-trend) ----
export interface SpeedTrendRow {
  vehicleId: string; name: string; byMonth: Record<string, number>; all: number;
}
export interface SpeedTrend {
  months: string[]; rows: SpeedTrendRow[]; total: Record<string, number>;
  heat: { min: number; p50: number; max: number };
  vehicles: number; episodes: number; from: string; to: string;
  max_all: number; source: string;
  params: { minDurationSec: number; minExcess: number; maxExcess: number };
}
export interface SpeedThresholds { minDurationSec: number; minExcess: number; maxExcess: number }

// ---- Детальная таблица нарушений (per-episode, P1.4 / стр.2 Power BI) ----
export interface ViolationDetailRow {
  vehicleId: string; vehicle: string; geozone: string; limit_kmh: number;
  avg_speed_kmh: number | null; max_speed_kmh: number; excess_kmh: number;
  duration_s: number; start_ts: number; public_road: boolean; severity: string;
  koap_article: string | null; fine_kzt: number | null;
}
export interface ViolationsDetail {
  rows: ViolationDetailRow[]; total: number; returned: number; capped: boolean;
  from: string; to: string; source: string;
  params: { minDurationSec: number; minExcess: number; maxExcess: number };
}
// ---- Топливо «Работа группы по ТС» + норма (справочно, P2.2) ----
export interface FuelDetailRow {
  vehicleId: string; vehicle: string; transport: boolean;
  mileage_km: number; moto_h: number; fuel_l: number;
  fact_l100: number | null; norm_l100: number | null;
  fact_lmh: number | null; norm_lmh: number | null;
  mode: "km" | "mh" | null; norm_src: string; over_l: number | null;
  refuel_l: number; drain_l: number; delivery_l: number;
}
export interface FuelDetail {
  rows: FuelDetailRow[]; total: number; returned: number; capped: boolean;
  with_norm: number; over_l_total: number; economy_l_total: number;
  norms_approved: boolean; norms_version: string;
  from: string; to: string; shifts_available: boolean; source: string;
}
export const getFuelDetail = (q: { from?: string; to?: string } = {}) => {
  const p = new URLSearchParams();
  if (q.from) p.set("from", q.from);
  if (q.to) p.set("to", q.to);
  const qs = p.toString();
  return get<FuelDetail>(`/api/fuel-detail${qs ? `?${qs}` : ""}`);
};

export const getViolationsDetail = (q: Partial<SpeedThresholds> & { from?: string; to?: string } = {}) => {
  const p = new URLSearchParams();
  if (q.from) p.set("from", q.from);
  if (q.to) p.set("to", q.to);
  if (q.minDurationSec) p.set("minDurationSec", String(q.minDurationSec));
  if (q.minExcess) p.set("minExcess", String(q.minExcess));
  if (q.maxExcess != null && q.maxExcess < 999) p.set("maxExcess", String(q.maxExcess));
  const qs = p.toString();
  return get<ViolationsDetail>(`/api/violations-detail${qs ? `?${qs}` : ""}`);
};
export const getSpeedTrend = (q: Partial<SpeedThresholds> & { from?: string; to?: string } = {}) => {
  const p = new URLSearchParams();
  if (q.from) p.set("from", q.from);
  if (q.to) p.set("to", q.to);
  if (q.minDurationSec) p.set("minDurationSec", String(q.minDurationSec));
  if (q.minExcess) p.set("minExcess", String(q.minExcess));
  if (q.maxExcess != null && q.maxExcess < 999) p.set("maxExcess", String(q.maxExcess));
  const qs = p.toString();
  return get<SpeedTrend>(`/api/speed-trend${qs ? `?${qs}` : ""}`);
};

export async function startSync(
  demo = false,
  range?: { start_ts: number; end_ts: number },
): Promise<Job> {
  const r = await fetch(`${API}/api/sync`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ demo, ...(range ?? {}) }),
  });
  if (!r.ok) throw new Error(`sync → ${r.status}`);
  return r.json();
}

export const getJob = (id: string) => get<Job>(`/api/sync/${id}`);
