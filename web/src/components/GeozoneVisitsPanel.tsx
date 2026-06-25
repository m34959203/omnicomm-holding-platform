"use client";

import { GeozoneVisits } from "@/lib/api";
import { num } from "@/lib/format";
import { useLang } from "@/lib/i18n";

const dt = (ts: number | null) =>
  ts
    ? new Date(ts * 1000).toLocaleString("ru-RU", {
        day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit",
      })
    : "—";
const dur = (s: number) => {
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return h ? `${h} ч ${m} м` : `${m} м`;
};

// Форма «Посещение геозон»: сводка по геозонам + таблица визитов (kb-14).
export default function GeozoneVisitsPanel({
  data, inScope, onOpenVehicle,
}: {
  data: GeozoneVisits;
  inScope?: (id: string) => boolean;
  onOpenVehicle?: (id: string, name?: string) => void;
}) {
  const { t } = useLang();
  const rows = (inScope ? data.rows.filter((r) => inScope(r.vehicle_id)) : data.rows).slice(0, 300);
  if (!data.rows.length) return <p className="data text-sm text-ink-faint">{t("rep.empty")}</p>;

  return (
    <div>
      <div className="mb-6 flex flex-wrap gap-2">
        {data.by_geozone.slice(0, 8).map((g) => (
          <span key={g.geozone}
            className="data rounded border border-line px-2 py-1 text-xs text-ink-dim">
            {g.geozone} · <span className="text-ink">{num(g.visits)}</span> {t("rep.visits")}
            {` · ${num(g.vehicles)} ${t("scope.vehicles")}`}
          </span>
        ))}
      </div>

      <div className="overflow-x-auto border-t border-line-strong">
        <table className="w-full min-w-[44rem] text-sm">
          <thead>
            <tr className="eyebrow text-left text-ink-faint">
              <th className="py-2 pr-4">{t("mt.vehicle")}</th>
              <th className="py-2 pr-4">{t("rep.geozone")}</th>
              <th className="py-2 pr-4">{t("rep.enter")}</th>
              <th className="py-2 pr-4 text-right">{t("rep.duration")}</th>
              <th className="py-2 pr-4 text-right">{t("rep.maxspeed")}</th>
              <th className="py-2 text-right">{t("rep.mileage")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={`${r.vehicle_id}-${r.enter_ts}-${i}`}
                onClick={() => onOpenVehicle?.(r.vehicle_id, r.vehicle)}
                className="cursor-pointer border-t border-line hover:bg-surface">
                <td className="truncate py-2 pr-4 text-ink">{r.vehicle}</td>
                <td className="truncate py-2 pr-4 text-ink-dim">{r.geozone || "—"}</td>
                <td className="data py-2 pr-4 text-xs text-ink-faint">{dt(r.enter_ts)}</td>
                <td className="data py-2 pr-4 text-right text-xs text-ink-dim">{dur(r.duration_s)}</td>
                <td className={`data py-2 pr-4 text-right text-xs ${(r.speeding_km ?? 0) > 0 ? "text-warn" : "text-ink-dim"}`}>
                  {r.max_speed_kmh != null ? num(r.max_speed_kmh) : "—"}
                </td>
                <td className="data py-2 text-right text-xs text-ink-dim">
                  {r.mileage_km != null ? num(r.mileage_km, 1) : "—"}
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
