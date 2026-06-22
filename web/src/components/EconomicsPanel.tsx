"use client";

import { Economics } from "@/lib/api";
import { moneyShort, num } from "@/lib/format";

export default function EconomicsPanel({ eco }: { eco: Economics }) {
  const buckets = [...eco.buckets].sort((a, b) => b.existing_kzt - a.existing_kzt);
  const max = Math.max(1, ...buckets.map((b) => b.existing_kzt));

  return (
    <div className="grid gap-10 lg:grid-cols-[1fr_minmax(0,20rem)]">
      <div>
        <span className="eyebrow">Адресуемые потери · за период</span>
        <ul className="mt-4">
          {buckets.map((b) => (
            <li key={b.key} className="border-t border-line py-4">
              <div className="flex items-baseline justify-between gap-4">
                <span className="text-sm text-ink">
                  {b.label}
                  {b.is_estimate && (
                    <span className="data ml-2 text-[0.65rem] text-ink-faint">≈ оценка</span>
                  )}
                </span>
                <span className="data shrink-0 text-lg text-ink">
                  {moneyShort(b.existing_kzt)}
                </span>
              </div>
              <div className="mt-2 h-px bg-line-strong">
                <div
                  className="h-px bg-accent"
                  style={{ width: `${(b.existing_kzt / max) * 100}%` }}
                />
              </div>
              {b.note && (
                <p className="data mt-2 text-xs text-ink-faint">{b.note}</p>
              )}
            </li>
          ))}
        </ul>
      </div>

      <aside className="flex flex-col justify-start gap-8 border-l-0 lg:border-l lg:border-line lg:pl-10">
        <div>
          <span className="eyebrow">Стоимость бездействия</span>
          <p className="display mt-2 text-5xl text-accent">
            {moneyShort(eco.coi_annual_kzt)}
          </p>
          <p className="data mt-1 text-xs text-ink-faint">в год · ≈ {moneyShort(eco.coi_monthly_kzt)} в месяц</p>
        </div>
        {eco.worst_vehicles?.length > 0 && (
          <div>
            <span className="eyebrow">Первоочередные ТС</span>
            <ul className="mt-3">
              {eco.worst_vehicles.slice(0, 5).map(([name, v], i) => (
                <li key={i} className="flex items-baseline justify-between gap-3 border-t border-line py-2">
                  <span className="data text-[0.65rem] text-ink-faint">
                    {String(i + 1).padStart(2, "0")}
                  </span>
                  <span className="flex-1 truncate text-xs text-ink">{name}</span>
                  <span className="data text-xs text-warn">{num(v, 1)}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </aside>
    </div>
  );
}
