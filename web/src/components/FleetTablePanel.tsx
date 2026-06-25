"use client";

import { FleetTable } from "@/lib/api";
import { num } from "@/lib/format";
import { useLang } from "@/lib/i18n";

// Форма «Сводный / Работа группы»: посуточный итог по ТС, все метрики агрегата (kb-14).
export default function FleetTablePanel({
  data, inScope, onOpenVehicle,
}: {
  data: FleetTable;
  inScope?: (id: string) => boolean;
  onOpenVehicle?: (id: string, name?: string) => void;
}) {
  const { t } = useLang();
  const rows = (inScope ? data.rows.filter((r) => inScope(r.vehicle_id)) : data.rows).slice(0, 400);
  if (!data.rows.length) return <p className="data text-sm text-ink-faint">{t("rep.empty")}</p>;

  return (
    <div>
      <div className="overflow-x-auto border-t border-line-strong">
        <table className="w-full min-w-[52rem] text-sm">
          <thead>
            <tr className="eyebrow text-left text-ink-faint">
              <th className="py-2 pr-4">{t("mt.vehicle")}</th>
              <th className="py-2 pr-4 text-right">{t("rep.mileage")}</th>
              <th className="py-2 pr-4 text-right">{t("rep.fuel")}</th>
              <th className="py-2 pr-4 text-right">л/100</th>
              <th className="py-2 pr-4 text-right">{t("rep.moto")}</th>
              <th className="py-2 pr-4 text-right">{t("rep.maxspeed")}</th>
              <th className="py-2 text-right">{t("tab.violations")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.vehicle_id}
                onClick={() => onOpenVehicle?.(r.vehicle_id, r.vehicle)}
                className="cursor-pointer border-t border-line hover:bg-surface">
                <td className="truncate py-2 pr-4 text-ink">{r.vehicle}</td>
                <td className="data py-2 pr-4 text-right text-xs text-ink-dim">
                  {r.mileage_km != null ? num(r.mileage_km, 1) : "—"}
                </td>
                <td className="data py-2 pr-4 text-right text-xs text-ink-dim">
                  {r.fuel_l != null ? num(r.fuel_l, 1) : "—"}
                </td>
                <td className="data py-2 pr-4 text-right text-xs text-ink-dim">
                  {r.fuel_per_100km != null ? num(r.fuel_per_100km, 1) : "—"}
                </td>
                <td className="data py-2 pr-4 text-right text-xs text-ink-dim">
                  {r.engine_hours != null ? num(r.engine_hours, 1) : "—"}
                </td>
                <td className="data py-2 pr-4 text-right text-xs text-ink-dim">
                  {r.max_speed_kmh != null ? num(r.max_speed_kmh) : "—"}
                </td>
                <td className={`data py-2 text-right text-xs ${(r.speeding_count ?? 0) > 0 ? "text-warn" : "text-ink-faint"}`}>
                  {r.speeding_count ? num(r.speeding_count) : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="data mt-3 text-xs text-ink-faint">{num(rows.length)} / {num(data.count)} {t("scope.vehicles")}</p>
    </div>
  );
}
