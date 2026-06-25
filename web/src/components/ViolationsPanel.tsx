"use client";

import { ViolationsForm } from "@/lib/api";
import { money, num } from "@/lib/format";
import { useLang } from "@/lib/i18n";

const SEV: Record<string, string> = {
  "грубое": "text-danger",
  "значительное": "text-warn",
  "незначительное": "text-ink-dim",
};

// Форма «Нарушения»: единая таблица (геозон-превышения + агрегатный флаг) (kb-14).
export default function ViolationsPanel({
  data, inScope, onOpenVehicle,
}: {
  data: ViolationsForm;
  inScope?: (id: string) => boolean;
  onOpenVehicle?: (id: string, name?: string) => void;
}) {
  const { t } = useLang();
  const rows = (inScope ? data.rows.filter((r) => inScope(r.vehicle_id)) : data.rows).slice(0, 400);
  if (!data.rows.length) return <p className="data text-sm text-ink-faint">{t("rep.empty")}</p>;

  return (
    <div>
      <div className="mb-6 flex flex-wrap gap-2">
        {Object.entries(data.by_type).map(([type, n]) => (
          <span key={type}
            className="data rounded border border-line px-2 py-1 text-xs text-ink-dim">
            {type} · <span className="text-ink">{num(n)}</span>
          </span>
        ))}
      </div>

      <div className="overflow-x-auto border-t border-line-strong">
        <table className="w-full min-w-[48rem] text-sm">
          <thead>
            <tr className="eyebrow text-left text-ink-faint">
              <th className="py-2 pr-4">{t("mt.vehicle")}</th>
              <th className="py-2 pr-4">{t("rep.type")}</th>
              <th className="py-2 pr-4">{t("rep.geozone")}</th>
              <th className="py-2 pr-4 text-right">{t("rep.maxspeed")}</th>
              <th className="py-2 text-right">{t("rep.fine")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={`${r.vehicle_id}-${r.start_ts}-${i}`}
                onClick={() => onOpenVehicle?.(r.vehicle_id, r.vehicle)}
                className="cursor-pointer border-t border-line hover:bg-surface">
                <td className="truncate py-2 pr-4 text-ink">{r.vehicle}</td>
                <td className={`py-2 pr-4 text-xs ${r.severity ? SEV[r.severity] ?? "text-ink-dim" : "text-ink-dim"}`}>
                  {r.type}
                  {r.koap_article ? <span className="text-ink-faint"> · {r.koap_article}</span> : null}
                </td>
                <td className="truncate py-2 pr-4 text-xs text-ink-dim">
                  {r.geozone || r.detail || "—"}
                </td>
                <td className="data py-2 pr-4 text-right text-xs text-ink-dim">
                  {r.max_speed_kmh != null ? num(r.max_speed_kmh) : "—"}
                  {r.limit_kmh != null ? <span className="text-ink-faint">/{num(r.limit_kmh)}</span> : null}
                </td>
                <td className="data py-2 text-right text-xs text-ink-dim">
                  {r.fine_kzt ? money(r.fine_kzt) : "—"}
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
