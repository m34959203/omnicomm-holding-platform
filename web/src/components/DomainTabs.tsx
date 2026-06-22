"use client";

import {
  Economics, GeoFeature, Maintenance, Recommendation, SensorHealth,
} from "@/lib/api";
import { useLang } from "@/lib/i18n";
import { TABS, TabKey } from "@/lib/scope";
import EconomicsPanel from "./EconomicsPanel";
import Recommendations from "./Recommendations";
import SensorHealthPanel from "./SensorHealthPanel";
import MaintenancePanel from "./MaintenancePanel";
import GeozoneMap from "./GeozoneMap";

// Домен-табы: глубина по доменам, контент по активному табу. Карта монтируется
// только когда её таб активен (Яндекс тяжёлый). EconomicsPanel/GeozoneMap —
// холдингового уровня (клиентски не скоупятся) → бейдж при выбранном scope.
export default function DomainTabs({
  tab, onTab, eco, recs, sensor, maint, geos, scoped,
}: {
  tab: TabKey;
  onTab: (t: TabKey) => void;
  eco: Economics | null;
  recs: Recommendation[];
  sensor: SensorHealth | null;
  maint: Maintenance | null;
  geos: GeoFeature[];
  scoped: boolean;
}) {
  const { t } = useLang();

  return (
    <section>
      <nav className="flex flex-wrap gap-x-6 gap-y-2 border-t border-line-strong pt-4">
        {TABS.map((k) => (
          <button
            key={k}
            onClick={() => onTab(k)}
            className={`eyebrow py-1 transition-colors ${
              tab === k ? "text-accent" : "text-ink-faint hover:text-ink"
            }`}
          >
            {t(`tab.${k}`)}
          </button>
        ))}
      </nav>

      <div key={tab} className="rise mt-8">
        {tab === "money" && (
          eco ? (
            <>
              {scoped && (
                <p className="data mb-4 text-xs text-warn">
                  ⚠ {t("common.holdingOnly")}
                </p>
              )}
              <EconomicsPanel eco={eco} />
            </>
          ) : <Empty t={t} />
        )}
        {tab === "speed" && <Recommendations recs={recs} />}
        {tab === "quality" && (sensor ? <SensorHealthPanel sh={sensor} /> : <Empty t={t} />)}
        {tab === "maint" && (maint ? <MaintenancePanel mt={maint} /> : <Empty t={t} />)}
        {tab === "map" && (
          <>
            {scoped && (
              <p className="data mb-4 text-xs text-warn">⚠ {t("common.holdingOnly")}</p>
            )}
            <GeozoneMap features={geos} />
          </>
        )}
      </div>
    </section>
  );
}

function Empty({ t }: { t: (k: string) => string }) {
  return <p className="data text-sm text-ink-faint">{t("attn.none")}</p>;
}
