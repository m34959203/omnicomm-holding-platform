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
export interface SensorHealth {
  terminals: TerminalHealth[];
  counts: Record<string, number>;
  missing_capabilities: { terminal_id: string; name: string | null; missing: string[] }[];
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
