"use client";

import { useCallback, useEffect, useState } from "react";
import {
  Dashboard,
  GeoFeature,
  Maintenance,
  Recommendation,
  SensorHealth,
  getDashboard,
  getGeozones,
  getMaintenance,
  getRecommendations,
  getSensorHealth,
  getSnapshots,
} from "@/lib/api";
import { num } from "@/lib/format";
import { useLang } from "@/lib/i18n";
import SyncBar from "@/components/SyncBar";
import OrgExplorer from "@/components/OrgExplorer";
import EconomicsPanel from "@/components/EconomicsPanel";
import GeozoneMap from "@/components/GeozoneMap";
import Recommendations from "@/components/Recommendations";
import SensorHealthPanel from "@/components/SensorHealthPanel";
import MaintenancePanel from "@/components/MaintenancePanel";
import Toolbar from "@/components/Toolbar";

function Section({ no, title, kicker, children, delay = 0 }: {
  no: string; title: string; kicker?: string; children: React.ReactNode; delay?: number;
}) {
  return (
    <section className="rise border-t border-line-strong pt-8" style={{ animationDelay: `${delay}ms` }}>
      <header className="mb-8 flex flex-wrap items-baseline gap-4">
        <span className="numeral">{no}</span>
        <h2 className="display text-2xl sm:text-3xl">{title}</h2>
        {kicker && <span className="data w-full text-xs text-ink-faint sm:ml-auto sm:w-auto">{kicker}</span>}
      </header>
      {children}
    </section>
  );
}

export default function Page() {
  const { t } = useLang();
  const [dash, setDash] = useState<Dashboard | null>(null);
  const [geos, setGeos] = useState<GeoFeature[]>([]);
  const [recs, setRecs] = useState<Recommendation[]>([]);
  const [sensor, setSensor] = useState<SensorHealth | null>(null);
  const [maint, setMaint] = useState<Maintenance | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "empty" | "down">("loading");

  const load = useCallback(async () => {
    try {
      const snaps = await getSnapshots();
      if (!snaps.length) {
        setState("empty");
        return;
      }
      const d = await getDashboard();
      const [g, r, sh, mt] = await Promise.all([
        getGeozones(), getRecommendations(), getSensorHealth(), getMaintenance(),
      ]);
      setDash(d);
      setGeos(g.geozones ?? []);
      setRecs(r.recommendations ?? []);
      setSensor(sh.sensor_health ?? null);
      setMaint(mt.maintenance ?? null);
      setState("ready");
    } catch {
      setState("down");
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const meta = dash?.meta ?? null;

  return (
    <main className="mx-auto max-w-6xl px-6 py-10 sm:px-10 lg:py-16">
      {/* масткед */}
      <header className="rise mb-10">
        <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-2">
          <span className="eyebrow">{t("mast.eyebrow")}</span>
          <span className="eyebrow">{dash?.period?.label ?? "—"}</span>
        </div>
        <h1 className="display mt-3 text-5xl sm:text-7xl">
          {t("mast.title_a")} <span className="text-accent">{t("mast.title_b")}</span>
        </h1>
        <p className="mt-4 max-w-2xl text-sm leading-relaxed text-ink-dim">
          {t("mast.lead")}
        </p>
        <div className="mt-5">
          <Toolbar periodKey={meta?.period_key} />
        </div>
      </header>

      <div className="rise rule mb-6" style={{ animationDelay: "80ms" }} />
      <div className="rise mb-14" style={{ animationDelay: "120ms" }}>
        <SyncBar
          syncedAt={meta?.synced_at ?? null}
          periodLabel={dash?.period?.label ?? null}
          onDone={load}
        />
      </div>

      {state === "loading" && <Skeleton />}
      {state === "down" && (
        <Empty title="API недоступен"
          body="Бэкенд-мост не отвечает. Запустите его: uvicorn api.main:app --port 8800" />
      )}
      {state === "empty" && (
        <Empty title="Снимок ещё не собран"
          body="Нажмите «Синхронизировать» вверху — синк соберёт снапшот в фоне и покажет живой прогресс." />
      )}

      {state === "ready" && dash && (
        <div className="flex flex-col gap-16">
          <Section no="01" title={t("sec.hierarchy")}
            kicker={dash.fleet ? `${num(dash.fleet.vehicles)} ${t("sec.hierarchy.kicker")} ${num(dash.fleet.with_data)}` : undefined}>
            <OrgExplorer orgs={dash.orgs} />
          </Section>

          {dash.economics && (
            <Section no="02" title={t("sec.money")} kicker={t("sec.money.kicker")} delay={60}>
              <EconomicsPanel eco={dash.economics} />
            </Section>
          )}

          <Section no="03" title={t("sec.speeding")}
            kicker={t("sec.speeding.kicker")} delay={120}>
            <Recommendations recs={recs} />
          </Section>

          <Section no="04" title={t("sec.geozones")} kicker={t("sec.geozones.kicker")} delay={180}>
            <GeozoneMap features={geos} />
          </Section>

          {sensor && (
            <Section no="05" title={t("sec.sensor")} kicker={t("sec.sensor.kicker")} delay={240}>
              <SensorHealthPanel sh={sensor} />
            </Section>
          )}

          {maint && (
            <Section no="06" title={t("sec.maint")} kicker={t("sec.maint.kicker")} delay={300}>
              <MaintenancePanel mt={maint} />
            </Section>
          )}
        </div>
      )}

      <footer className="rule mt-20 pt-6">
        <p className="eyebrow">{t("footer")}</p>
      </footer>
    </main>
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
