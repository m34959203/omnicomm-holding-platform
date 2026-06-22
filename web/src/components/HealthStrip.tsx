"use client";

import { Kpi } from "@/lib/api";
import { moneyShort, num, pct } from "@/lib/format";
import { useLang } from "@/lib/i18n";
import TileKPI from "./TileKPI";

// Tier-0 «командный мостик»: 6 health-KPI выбранного scope.
// Цвет дисциплинирован: lime только у «потенциала экономии» (апсайд),
// red/amber — только когда нужно действие; норма нейтральна.
export default function HealthStrip({
  kpi, vehicleCount, sensorCounts, maintCounts, recsCount,
}: {
  kpi: Kpi;
  vehicleCount: number;
  sensorCounts: Record<string, number>;
  maintCounts: Record<string, number>;
  recsCount: number;
}) {
  const { t } = useLang();

  const online = sensorCounts.online ?? 0;
  const totalSensor =
    (sensorCounts.online ?? 0) + (sensorCounts.stale ?? 0) +
    (sensorCounts.offline ?? 0) + (sensorCounts.unknown ?? 0);
  const onlineShare = totalSensor ? online / totalSensor : 0;

  const overdue = maintCounts["просрочено"] ?? 0;
  const due = maintCounts["ожидается"] ?? 0;
  const speedShare = vehicleCount ? recsCount / vehicleCount : 0;
  const idle = kpi.idle_hours_share ?? 0;

  return (
    <section>
      <span className="eyebrow">{t("health.title")}</span>
      <div className="mt-3 grid grid-cols-2 gap-x-8 gap-y-1 sm:grid-cols-3 lg:grid-cols-6">
        <TileKPI
          label={t("health.online")}
          value={`${num(online)} / ${num(totalSensor)}`}
          sub={pct(onlineShare, 0)}
          tone={onlineShare < 0.6 ? "danger" : onlineShare < 0.8 ? "warn" : "neutral"}
          share={onlineShare}
        />
        <TileKPI
          label={t("health.savings")}
          value={moneyShort(kpi.potential_savings)}
          sub={t("sec.money.kicker")}
          tone="accent"
        />
        <TileKPI
          label={t("health.losses")}
          value={moneyShort(kpi.idle_fuel_cost)}
          tone={kpi.idle_fuel_cost > 0 ? "warn" : "neutral"}
        />
        <TileKPI
          label={t("health.speeding")}
          value={num(recsCount)}
          sub={`/ ${num(vehicleCount)} ${t("scope.vehicles")}`}
          tone={speedShare > 0.15 ? "danger" : speedShare > 0.05 ? "warn" : "neutral"}
          share={speedShare}
        />
        <TileKPI
          label={t("health.overdue")}
          value={num(overdue)}
          sub={due ? `+${num(due)} ${t("mt.due")}` : undefined}
          tone={overdue > 0 ? "danger" : due > 0 ? "warn" : "neutral"}
        />
        <TileKPI
          label={t("health.idle")}
          value={pct(idle, 0)}
          tone={idle > 0.4 ? "danger" : idle > 0.25 ? "warn" : "neutral"}
          share={idle}
        />
      </div>
    </section>
  );
}
