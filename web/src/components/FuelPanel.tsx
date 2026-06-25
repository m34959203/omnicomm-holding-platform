"use client";

import { FuelForm } from "@/lib/api";
import { num } from "@/lib/format";
import { useLang } from "@/lib/i18n";

const L = (v: number | null, frac = 1) => (v != null ? num(v, frac) : "—");

// Форма «Топливо»: заправки/сливы/выдача + объём бака по ТС (kb-14).
export default function FuelPanel({
  data, inScope, onOpenVehicle,
}: {
  data: FuelForm;
  inScope?: (id: string) => boolean;
  onOpenVehicle?: (id: string, name?: string) => void;
}) {
  const { t } = useLang();
  const rows = (inScope ? data.rows.filter((r) => inScope(r.vehicle_id)) : data.rows).slice(0, 400);
  if (!data.rows.length) return <p className="data text-sm text-ink-faint">{t("rep.empty")}</p>;

  return (
    <div>
      <div className="mb-6 flex flex-wrap gap-2">
        <span className="data rounded border border-line px-2 py-1 text-xs text-ink-dim">
          {t("rep.refuel")} · <span className="text-ink">{num(data.totals.refuel_l)}</span>
        </span>
        <span className="data rounded border border-line px-2 py-1 text-xs text-ink-dim">
          {t("rep.delivery")} · <span className="text-ink">{num(data.totals.delivery_l)}</span>
        </span>
        {data.totals.drain_l > 0 && (
          <span className="data rounded border border-line px-2 py-1 text-xs text-warn">
            {t("rep.drain")} · {num(data.totals.drain_l)}
          </span>
        )}
      </div>

      <div className="overflow-x-auto border-t border-line-strong">
        <table className="w-full min-w-[48rem] text-sm">
          <thead>
            <tr className="eyebrow text-left text-ink-faint">
              <th className="py-2 pr-4">{t("mt.vehicle")}</th>
              <th className="py-2 pr-4 text-right">{t("rep.refuel")}</th>
              <th className="py-2 pr-4 text-right">{t("rep.drain")}</th>
              <th className="py-2 pr-4 text-right">{t("rep.delivery")}</th>
              <th className="py-2 text-right">{t("rep.volume")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.vehicle_id}
                onClick={() => onOpenVehicle?.(r.vehicle_id, r.vehicle)}
                className="cursor-pointer border-t border-line hover:bg-surface">
                <td className="truncate py-2 pr-4 text-ink">{r.vehicle}</td>
                <td className="data py-2 pr-4 text-right text-xs text-ink-dim">{L(r.refuel_l)}</td>
                <td className={`data py-2 pr-4 text-right text-xs ${(r.drain_l ?? 0) > 0 ? "text-warn" : "text-ink-faint"}`}>
                  {L(r.drain_l)}
                </td>
                <td className="data py-2 pr-4 text-right text-xs text-ink-dim">{L(r.delivery_l)}</td>
                <td className="data py-2 text-right text-xs text-ink-faint">
                  {r.vol_end_l != null ? `${L(r.vol_start_l, 0)} → ${L(r.vol_end_l, 0)}` : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="data mt-3 text-xs text-ink-faint">{num(rows.length)} / {num(data.count)}</p>
    </div>
  );
}
