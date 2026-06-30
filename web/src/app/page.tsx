"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Dashboard, FuelForm, GeoFeature, Maintenance, Meta, Recommendation,
  FuelDetail, SensorHealth, SpeedThresholds, SpeedTrend, ViolationsDetail, ViolationsForm,
  excelUrl, getDashboard, getFuel, getFuelDetail, getGeozones, getJob, getMaintenance,
  getRecommendations, getSensorHealth, getSnapshots, getSpeedTrend, getViolationsDetail,
  getViolationsForm, startSync,
} from "@/lib/api";
import {
  Agg, C, DzoRow, FONT, aggregate, buildDzoRows, dzoNodes,
} from "@/lib/atlas";
import { indexOrgs, makeInScope, scopeMaint, scopeRecs, scopeSensor, subtreeOrgIds } from "@/lib/scope";
import Ribbon, { Period } from "@/components/atlas/Ribbon";
import Rail from "@/components/atlas/Rail";
import Overview from "@/components/atlas/Overview";
import Money from "@/components/atlas/Money";
import Speed from "@/components/atlas/Speed";
import Violations from "@/components/atlas/Violations";
import Trend, { TrendMetric } from "@/components/atlas/Trend";
import Fuel from "@/components/atlas/Fuel";
import Quality from "@/components/atlas/Quality";
import Maint from "@/components/atlas/Maint";
import VehicleCard from "@/components/VehicleCard";

type PageKey = "overview" | "money" | "fuel" | "speed" | "violations" | "trend" | "quality" | "maint";
const PAGES: [PageKey, string][] = [
  ["overview", "Обзор"], ["money", "Деньги"], ["fuel", "Топливо"],
  ["speed", "Скоростной режим"], ["violations", "Нарушения"], ["trend", "Повторяемость"],
  ["quality", "Качество данных"], ["maint", "Контроль ТО"],
];
const ACTIVE_WINDOW_S = 7 * 86400;

// Разбивка снимков на пилюли периода по длительности.
function snapDays(key: string): number {
  const [a, b] = key.split("_");
  const da = Date.parse(a), db = Date.parse(b);
  if (isNaN(da) || isNaN(db)) return 30;
  return Math.max(1, Math.round((db - da) / 86400000));
}
function bucketOf(days: number): string {
  if (days <= 1.5) return "Сутки";
  if (days <= 10) return "Неделя";
  if (days <= 45) return "Месяц";
  return "Квартал";
}

export default function Page() {
  const [dash, setDash] = useState<Dashboard | null>(null);
  const [geos, setGeos] = useState<GeoFeature[]>([]);
  const [recs, setRecs] = useState<Recommendation[]>([]);
  const [sensor, setSensor] = useState<SensorHealth | null>(null);
  const [maint, setMaint] = useState<Maintenance | null>(null);
  const [violForm, setViolForm] = useState<ViolationsForm | null>(null);
  const [, setFuel] = useState<FuelForm | null>(null);
  const [vehicleOrg, setVehicleOrg] = useState<Record<string, string>>({});
  const [snaps, setSnaps] = useState<Meta[]>([]);
  const [periodKey, setPeriodKey] = useState<string>("");
  const [state, setState] = useState<"loading" | "ready" | "empty" | "down">("loading");

  const [page, setPage] = useState<PageKey>("overview");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [vehCard, setVehCard] = useState<{ id: string; name?: string; ts?: number } | null>(null);
  const [syncing, setSyncing] = useState(false);

  // Пороги превышения (P1.2): влияют на «Повторяемость» (запрос) и «Скоростной режим» (клиент).
  const [thr, setThr] = useState<SpeedThresholds>({ minDurationSec: 0, minExcess: 0, maxExcess: 999 });
  const [trend, setTrend] = useState<SpeedTrend | null>(null);
  const [trendLoading, setTrendLoading] = useState(false);
  const [metric, setMetric] = useState<TrendMetric>("episodes");
  const [violDet, setViolDet] = useState<ViolationsDetail | null>(null);
  const [violDetLoading, setViolDetLoading] = useState(false);
  const [fuelDet, setFuelDet] = useState<FuelDetail | null>(null);
  const [fuelDetLoading, setFuelDetLoading] = useState(false);

  const load = useCallback(async (key?: string) => {
    try {
      const list = await getSnapshots();
      setSnaps(list);
      if (!list.length) { setState("empty"); return; }
      const k = (key ?? periodKey) || undefined;
      const d = await getDashboard(k);
      const [g, r, sh, mt, vf, fu] = await Promise.all([
        getGeozones(k), getRecommendations(k), getSensorHealth(k),
        getMaintenance(k), getViolationsForm(k), getFuel(k),
      ]);
      setDash(d); setGeos(g.geozones ?? []);
      setRecs(r.recommendations ?? []); setVehicleOrg(r.vehicle_org ?? {});
      setSensor(sh.sensor_health ?? null); setMaint(mt.maintenance ?? null);
      setViolForm(vf.violations ?? null); setFuel(fu.fuel ?? null);
      if (d.meta?.period_key) setPeriodKey(d.meta.period_key);
      setState("ready");
    } catch { setState("down"); }
  }, [periodKey]);

  useEffect(() => { load(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, []);

  // Тренд повторяемости — пересчёт при смене порогов (дебаунс), скоуп/метрика на клиенте.
  useEffect(() => {
    if (state !== "ready") return;
    let alive = true;
    setTrendLoading(true);
    const t = setTimeout(async () => {
      try {
        const data = await getSpeedTrend(thr);
        if (alive) setTrend(data);
      } catch { if (alive) setTrend(null); }
      finally { if (alive) setTrendLoading(false); }
    }, 350);
    return () => { alive = false; clearTimeout(t); };
  }, [thr, state]);

  const setThreshold = (k: keyof SpeedThresholds, v: number) =>
    setThr((s) => ({ ...s, [k]: k === "maxExcess" && v === 0 ? 999 : v }));

  // Детальная таблица нарушений — за период ВЫБРАННОГО снимка + пороги.
  const periodIso = useMemo(() => {
    const p = dash?.period;
    if (!p) return null;
    const iso = (ts: number) => new Date(ts * 1000).toISOString().slice(0, 10);
    return { from: iso(p.start_ts), to: iso(p.end_ts) };
  }, [dash]);
  useEffect(() => {
    if (state !== "ready" || !periodIso) return;
    let alive = true;
    setViolDetLoading(true);
    const t = setTimeout(async () => {
      try {
        const data = await getViolationsDetail({ ...thr, from: periodIso.from, to: periodIso.to });
        if (alive) setViolDet(data);
      } catch { if (alive) setViolDet(null); }
      finally { if (alive) setViolDetLoading(false); }
    }, 350);
    return () => { alive = false; clearTimeout(t); };
  }, [thr, periodIso, state]);

  // Топливо «Работа группы по ТС» — за период выбранного снимка.
  useEffect(() => {
    if (state !== "ready" || !periodIso) return;
    let alive = true;
    setFuelDetLoading(true);
    (async () => {
      try {
        const data = await getFuelDetail({ from: periodIso.from, to: periodIso.to });
        if (alive) setFuelDet(data);
      } catch { if (alive) setFuelDet(null); }
      finally { if (alive) setFuelDetLoading(false); }
    })();
    return () => { alive = false; };
  }, [periodIso, state]);

  const onSync = async () => {
    if (syncing) return;
    setSyncing(true);
    try {
      const job = await startSync(false);
      let st = job;
      for (let i = 0; i < 600 && st.status !== "done" && st.status !== "error"; i++) {
        await new Promise((res) => setTimeout(res, 2000));
        st = await getJob(job.id);
      }
      await load(periodKey);
    } catch { /* no-op */ } finally { setSyncing(false); }
  };

  // ---- модель ----
  const orgs = dash?.orgs ?? [];
  const allRows = useMemo(
    () => buildDzoRows(orgs, recs, sensor, maint, vehicleOrg),
    [orgs, recs, sensor, maint, vehicleOrg],
  );
  const byId = useMemo(() => indexOrgs(orgs), [orgs]);
  const scopeIds = useMemo(() => {
    if (!selected.size) return null;
    const s = new Set<string>();
    for (const id of selected) for (const x of subtreeOrgIds(byId, id)) s.add(x);
    return s;
  }, [selected, byId]);
  const inScope = useMemo(() => makeInScope(scopeIds, vehicleOrg), [scopeIds, vehicleOrg]);

  const rows: DzoRow[] = useMemo(
    () => (selected.size ? allRows.filter((r) => selected.has(r.org_id)) : allRows),
    [allRows, selected],
  );
  const agg: Agg = useMemo(() => aggregate(rows), [rows]);

  const recsS = useMemo(() => scopeRecs(recs, inScope), [recs, inScope]);
  const sensorS = useMemo(() => scopeSensor(sensor, inScope), [sensor, inScope]);
  const maintS = useMemo(() => scopeMaint(maint, inScope), [maint, inScope]);
  const violRowsS = useMemo(
    () => (violForm?.rows ?? []).filter((v) => inScope(v.vehicle_id))
      .filter((v) => {
        const e = v.excess_kmh ?? 0;
        return e >= thr.minExcess && e <= thr.maxExcess;
      }),
    [violForm, inScope, thr],
  );

  // vehicleId → org_id ВЕРХНЕЙ ДЗО (для группировки тренда «На ТС / Доля»).
  const vehTopDzo = useMemo(() => {
    const map: Record<string, string> = {};
    const tops = dzoNodes(orgs);
    const leafToTop = new Map<string, string>();
    for (const top of tops) for (const oid of subtreeOrgIds(byId, top.org_id)) leafToTop.set(oid, top.org_id);
    for (const [tid, oid] of Object.entries(vehicleOrg)) {
      const top = leafToTop.get(oid);
      if (top) map[tid] = top;
    }
    return map;
  }, [orgs, byId, vehicleOrg]);

  const dzoNameById = useMemo(() => new Map(dzoNodes(orgs).map((n) => [n.org_id, n.name])), [orgs]);
  const dzoOf = (vid: string) => dzoNameById.get(vehTopDzo[vid]) ?? "—";

  // Активные за 7 дней (P1.5) — по последнему сигналу терминала в скоупе.
  const activeCount = useMemo(
    () => (sensorS?.terminals ?? []).filter((t) => t.age_seconds != null && t.age_seconds < ACTIVE_WINDOW_S).length,
    [sensorS],
  );
  const totalCount = sensorS?.terminals.length ?? 0;

  // пилюли периода
  const periods: Period[] = useMemo(() => {
    const order = ["Сутки", "Неделя", "Месяц", "Квартал"];
    const pick: Record<string, string | undefined> = {};
    for (const s of snaps) { const b = bucketOf(snapDays(s.period_key)); if (!pick[b]) pick[b] = s.period_key; }
    return order.map((name) => {
      const key = pick[name];
      return {
        key: name, name, disabled: !key,
        active: !!key && key === periodKey,
        onClick: () => { if (key && key !== periodKey) { setPeriodKey(key); load(key); } },
      };
    });
  }, [snaps, periodKey, load]);

  const toggle = (id: string) => setSelected((s) => {
    const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n;
  });
  const clear = () => setSelected(new Set());

  const dzoForRail = useMemo(
    () => dzoNodes(orgs).map((n) => allRows.find((r) => r.org_id === n.org_id)!).filter(Boolean),
    [orgs, allRows],
  );
  const summary = (selected.size ? `${selected.size} ДЗО` : "Все ДЗО")
    + ` · ${agg.veh} ТС · ${dash?.period?.label ?? "—"}`;

  const onVehicle = (id: string, name?: string, ts?: number) => setVehCard({ id, name, ts });
  // Окно карточки = сутки эпизода (локальный день ts); иначе период отчёта.
  const vehPeriod = (() => {
    if (!vehCard?.ts) return undefined;
    const d = new Date(vehCard.ts * 1000); d.setHours(0, 0, 0, 0);
    const start = Math.floor(d.getTime() / 1000);
    return { start_ts: start, end_ts: start + 86400 };
  })();
  const snapLabel = (dash?.meta?.synced_at
    ? new Date(dash.meta.synced_at * 1000).toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })
    : "—") + " · кэш";

  return (
    <div style={{ height: "100vh", minHeight: 680, display: "flex", flexDirection: "column", background: C.bg, color: C.ink, fontFamily: FONT, overflow: "hidden" }}>
      <Ribbon
        title="Автопарк КАП — аналитика" subtitle="Omnicomm Holding · отчёт"
        snapshot={snapLabel} periods={periods} excelHref={excelUrl(periodKey || undefined)}
        onSync={onSync} syncing={syncing}
      />

      <div style={{ flex: 1, display: "flex", minHeight: 0 }}>
        {state === "ready" && (
          <Rail dzo={dzoForRail} selected={selected} onToggle={toggle} onClear={clear}
            summary={summary} geoCount={geos.length}
            thresholds={thr} onThreshold={setThreshold}
            activeCount={activeCount} totalCount={totalCount} />
        )}

        <main style={{ flex: 1, minWidth: 0, overflowY: "auto", padding: 14 }}>
          {state === "loading" && <Notice title="Загрузка снимка…" body="Читаем кэш-снапшот." />}
          {state === "down" && <Notice title="API недоступен" body="Бэкенд-мост не отвечает." />}
          {state === "empty" && <Notice title="Снимок ещё не собран" body="Нажмите «↻ обновить» вверху — синк соберёт снапшот в фоне." />}
          {state === "ready" && (
            <>
              {page === "overview" && <Overview rows={rows} agg={agg} eco={dash?.economics ?? null} sensorCounts={sensorS?.counts ?? {}} overdueTotal={agg.overdue} />}
              {page === "money" && <Money rows={rows} agg={agg} eco={dash?.economics ?? null} />}
              {page === "fuel" && <Fuel data={fuelDet} loading={fuelDetLoading} inScope={inScope} dzoOf={dzoOf} fuelPrice={Number(orgs[0]?.kpi.fuel_price_kzt ?? 0)} onVehicle={onVehicle} />}
              {page === "speed" && <Speed rows={rows} agg={agg} recs={recsS} violRows={violRowsS} onVehicle={onVehicle} />}
              {page === "violations" && <Violations data={violDet} loading={violDetLoading} inScope={inScope} onVehicle={onVehicle} />}
              {page === "trend" && <Trend trend={trend} loading={trendLoading} metric={metric} onMetric={setMetric} dzoRows={rows} vehTopDzo={vehTopDzo} inScope={inScope} onVehicle={onVehicle} />}
              {page === "quality" && <Quality rows={rows} sensor={sensorS} onVehicle={onVehicle} />}
              {page === "maint" && <Maint rows={rows} maint={maintS} onVehicle={onVehicle} />}
            </>
          )}
        </main>
      </div>

      <div style={{ flexShrink: 0, display: "flex", alignItems: "center", gap: 2, height: 36, padding: "0 12px", background: C.panel, borderTop: `1px solid ${C.line2}` }}>
        <span style={{ fontSize: 10.5, color: C.faint2, marginRight: 8, textTransform: "uppercase", letterSpacing: ".05em" }}>Страницы</span>
        {PAGES.map(([k, l]) => (
          <button key={k} onClick={() => setPage(k)}
            style={{
              padding: "6px 13px", border: "none", cursor: "pointer", font: `600 12px/1 ${FONT}`,
              borderRadius: "5px 5px 0 0",
              ...(k === page ? { background: "#eef4fd", color: C.blue, borderBottom: `2px solid ${C.blue}` } : { background: "transparent", color: C.muted2 }),
            }}>{l}</button>
        ))}
      </div>

      {vehCard && <VehicleCard terminalId={vehCard.id} name={vehCard.name} period={vehPeriod} onClose={() => setVehCard(null)} />}
    </div>
  );
}

function Notice({ title, body }: { title: string; body: string }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6, padding: "60px 8px", maxWidth: 520 }}>
      <h2 style={{ fontSize: 20, fontWeight: 700, margin: 0 }}>{title}</h2>
      <p style={{ fontSize: 13, color: C.muted, margin: 0, lineHeight: 1.5 }}>{body}</p>
    </div>
  );
}
