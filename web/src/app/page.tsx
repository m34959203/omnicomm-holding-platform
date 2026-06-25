"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Dashboard,
  FleetTable,
  GeoFeature,
  GeozoneVisits,
  Maintenance,
  Meta,
  Recommendation,
  SensorHealth,
  ViolationsForm,
  getDashboard,
  getFleetTable,
  getGeozoneVisits,
  getGeozones,
  getMaintenance,
  getRecommendations,
  getSensorHealth,
  getSnapshots,
  getViolationsForm,
} from "@/lib/api";
import { num } from "@/lib/format";
import { useLang } from "@/lib/i18n";
import {
  TABS, TabKey, buildSignals, indexOrgs, makeInScope, scopeMaint,
  scopeRecs, scopeSensor, subtreeOrgIds,
} from "@/lib/scope";
import SyncBar from "@/components/SyncBar";
import Toolbar from "@/components/Toolbar";
import ScopeRail from "@/components/ScopeRail";
import HealthStrip from "@/components/HealthStrip";
import AttentionFeed from "@/components/AttentionFeed";
import Overview from "@/components/Overview";
import DomainTabs from "@/components/DomainTabs";
import VehicleCard from "@/components/VehicleCard";

export default function Page() {
  const { t } = useLang();
  const [dash, setDash] = useState<Dashboard | null>(null);
  const [geos, setGeos] = useState<GeoFeature[]>([]);
  const [recs, setRecs] = useState<Recommendation[]>([]);
  const [sensor, setSensor] = useState<SensorHealth | null>(null);
  const [maint, setMaint] = useState<Maintenance | null>(null);
  const [visits, setVisits] = useState<GeozoneVisits | null>(null);
  const [fleet, setFleet] = useState<FleetTable | null>(null);
  const [violForm, setViolForm] = useState<ViolationsForm | null>(null);
  const [vehicleOrg, setVehicleOrg] = useState<Record<string, string>>({});
  const [snaps, setSnaps] = useState<Meta[]>([]);
  const [periodKey, setPeriodKey] = useState<string>("");
  const [state, setState] = useState<"loading" | "ready" | "empty" | "down">("loading");

  const [scope, setScope] = useState<string>("");
  const [tab, setTab] = useState<TabKey>("money");
  const [focus, setFocus] = useState<string | null>(null);
  const [drawer, setDrawer] = useState(false);
  const [vehCard, setVehCard] = useState<{ id: string; name?: string } | null>(null);

  // Грузим конкретный снимок (по period_key) — выбор снимка/шаблона.
  const load = useCallback(async (key?: string) => {
    try {
      const list = await getSnapshots();
      setSnaps(list);
      if (!list.length) { setState("empty"); return; }
      const k = (key ?? periodKey) || undefined;
      const d = await getDashboard(k);
      const [g, r, sh, mt, gv, ft, vf] = await Promise.all([
        getGeozones(k), getRecommendations(k), getSensorHealth(k), getMaintenance(k),
        getGeozoneVisits(k), getFleetTable(k), getViolationsForm(k),
      ]);
      setDash(d);
      setGeos(g.geozones ?? []);
      setRecs(r.recommendations ?? []);
      setVehicleOrg(r.vehicle_org ?? {});
      setSensor(sh.sensor_health ?? null);
      setMaint(mt.maintenance ?? null);
      setVisits(gv.geozone_visits ?? null);
      setFleet(ft.fleet_table ?? null);
      setViolForm(vf.violations ?? null);
      if (d.meta?.period_key) setPeriodKey(d.meta.period_key);
      setState("ready");
    } catch {
      setState("down");
    }
  }, [periodKey]);

  useEffect(() => { load(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, []);

  const selectSnapshot = (k: string) => { setPeriodKey(k); load(k); };
  const onJump = (t: TabKey, entityId?: string) => { setTab(t); setFocus(entityId ?? null); };

  // deep-link: читать ?tab/?scope при маунте, писать при изменении (без перезагрузки).
  useEffect(() => {
    const p = new URLSearchParams(window.location.search);
    const tk = p.get("tab");
    if (tk && (TABS as readonly string[]).includes(tk)) setTab(tk as TabKey);
    const sc = p.get("scope");
    if (sc) setScope(sc);
  }, []);
  useEffect(() => {
    if (state !== "ready") return;
    const p = new URLSearchParams(window.location.search);
    p.set("tab", tab);
    scope ? p.set("scope", scope) : p.delete("scope");
    window.history.replaceState(null, "", `?${p.toString()}`);
  }, [tab, scope, state]);

  const meta = dash?.meta ?? null;
  const orgs = dash?.orgs ?? [];
  const byId = useMemo(() => indexOrgs(orgs), [orgs]);
  const root = orgs[0];
  const node = (scope && byId.get(scope)) || root;
  const scopeIds = useMemo(
    () => (scope ? subtreeOrgIds(byId, scope) : null), [scope, byId],
  );
  const inScope = useMemo(() => makeInScope(scopeIds, vehicleOrg), [scopeIds, vehicleOrg]);

  const recsS = useMemo(() => scopeRecs(recs, inScope), [recs, inScope]);
  const sensorS = useMemo(() => scopeSensor(sensor, inScope), [sensor, inScope]);
  const maintS = useMemo(() => scopeMaint(maint, inScope), [maint, inScope]);
  const scoped = scope !== "";
  const allSignals = useMemo(
    () => buildSignals(recsS, sensorS, maintS, dash?.economics ?? null, scoped, 999),
    [recsS, sensorS, maintS, dash, scoped],
  );
  const signals = allSignals.slice(0, 6);

  // Топ организаций по эпизодам превышений (terminal → org → имя), для графика Speed.
  const speedByOrg = useMemo(() => {
    const m = new Map<string, number>();
    for (const r of recsS) {
      const name = byId.get(vehicleOrg[r.terminal_id])?.name;
      if (!name) continue;
      m.set(name, (m.get(name) ?? 0) + r.episodes);
    }
    return [...m.entries()]
      .map(([label, value]) => ({ label, value }))
      .sort((a, b) => b.value - a.value)
      .slice(0, 6);
  }, [recsS, vehicleOrg, byId]);

  const onScope = (id: string) => { setScope(id); setDrawer(false); };

  return (
    <div className="mx-auto grid max-w-7xl grid-cols-1 gap-x-10 px-5 sm:px-8
                    lg:grid-cols-[17rem_minmax(0,1fr)]">
      {/* SCOPE RAIL — слева (десктоп), drawer (мобайл) */}
      {state === "ready" && (
        <>
          <aside className="hidden lg:sticky lg:top-0 lg:block lg:max-h-dvh lg:overflow-y-auto
                            lg:border-r lg:border-line lg:py-8 lg:pr-6">
            <ScopeRail orgs={orgs} scope={scope} onScope={onScope} />
          </aside>
          {drawer && (
            <div className="fixed inset-0 z-50 overflow-y-auto p-6 lg:hidden"
              style={{ background: "var(--paper)" }}>
              <button onClick={() => setDrawer(false)}
                className="eyebrow mb-4 text-accent">← {t("scope.title")}</button>
              <ScopeRail orgs={orgs} scope={scope} onScope={onScope} />
            </div>
          )}
        </>
      )}

      <main className="min-w-0 py-8 lg:py-12">
        {/* КОМПАКТНЫЙ ХЕДЕР */}
        <header className="rise">
          <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1">
            <span className="eyebrow">{t("mast.eyebrow")} · КАП</span>
            <span className="eyebrow">{dash?.period?.label ?? "—"}</span>
          </div>
          <div className="mt-2 flex flex-wrap items-end justify-between gap-4">
            <h1 className="display text-3xl sm:text-4xl">
              {node ? node.name : <span className="text-accent">{t("scope.holding")}</span>}
            </h1>
            <Toolbar periodKey={meta?.period_key} />
          </div>
          {state === "ready" && node && (
            <button
              onClick={() => setDrawer(true)}
              className="data mt-2 text-xs text-ink-faint lg:pointer-events-none"
            >
              {num(node.vehicle_count)} {t("scope.vehicles")}
              {` · данные у ${num(node.kpi.vehicles_with_data ?? 0)}`}
              <span className="lg:hidden"> · {t("scope.title")} ▾</span>
            </button>
          )}
        </header>

        <div className="rise rule my-5" style={{ animationDelay: "60ms" }} />
        <div className="rise mb-10" style={{ animationDelay: "100ms" }}>
          <SyncBar
            syncedAt={meta?.synced_at ?? null}
            periodLabel={dash?.period?.label ?? null}
            onDone={() => load(periodKey)}
            snapshots={snaps}
            periodKey={periodKey}
            onSelectSnapshot={selectSnapshot}
          />
        </div>

        {state === "loading" && <Skeleton />}
        {state === "down" && (
          <Empty title="API недоступен"
            body="Бэкенд-мост не отвечает. Запустите его: uvicorn api.main:app --port 8800" />
        )}
        {state === "empty" && (
          <Empty title="Снимок ещё не собран"
            body="Нажмите «Синхронизировать» вверху — синк соберёт снапшот в фоне." />
        )}

        {state === "ready" && node && (
          <div className="flex flex-col gap-12">
            <div className="rise"><HealthStrip
              kpi={node.kpi}
              vehicleCount={node.vehicle_count}
              sensorCounts={sensorS?.counts ?? {}}
              maintCounts={maintS?.counts ?? {}}
              recsCount={recsS.length}
            /></div>

            <div className="rise" style={{ animationDelay: "60ms" }}>
              <AttentionFeed signals={signals} total={allSignals.length} onJump={onJump} />
            </div>

            <div className="rise" style={{ animationDelay: "120ms" }}>
              <Overview
                kpi={node.kpi}
                eco={scoped ? null : dash?.economics ?? null}
                recsCount={recsS.length}
                sensor={sensorS}
                maint={maintS}
                onOpen={(tk) => onJump(tk)}
              />
            </div>

            <div className="rise" style={{ animationDelay: "180ms" }}>
              <DomainTabs
                tab={tab} onTab={(tk) => onJump(tk)}
                eco={dash?.economics ?? null}
                recs={recsS} sensor={sensorS} maint={maintS}
                geos={geos} scoped={scoped} speedByOrg={speedByOrg}
                focusId={focus}
                onOpenVehicle={(id, name) => setVehCard({ id, name })}
                visits={visits} fleet={fleet} violationsForm={violForm}
                inScope={inScope}
              />
            </div>
          </div>
        )}

        <footer className="rule mt-16 pt-6">
          <p className="eyebrow">{t("footer")}</p>
        </footer>
      </main>

      {vehCard && (
        <VehicleCard terminalId={vehCard.id} name={vehCard.name}
          onClose={() => setVehCard(null)} />
      )}
    </div>
  );
}

function Empty({ title, body }: { title: string; body: string }) {
  return (
    <div className="flex flex-col items-start gap-2 border-t border-line py-16">
      <h2 className="display text-3xl text-ink">{title}</h2>
      <p className="data max-w-xl text-sm text-ink-dim">{body}</p>
    </div>
  );
}

function Skeleton() {
  return (
    <div className="flex flex-col gap-4">
      {[0, 1, 2].map((i) => (
        <div key={i} className="sweep h-24 border-t border-line bg-surface/30" />
      ))}
    </div>
  );
}
