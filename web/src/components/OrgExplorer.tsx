"use client";

import { useMemo, useState } from "react";
import { OrgNode } from "@/lib/api";
import { money, moneyShort, num, pct } from "@/lib/format";

function flatten(nodes: OrgNode[], depth = 0, acc: { n: OrgNode; depth: number }[] = []) {
  for (const n of nodes) {
    acc.push({ n, depth });
    if (n.children?.length) flatten(n.children, depth + 1, acc);
  }
  return acc;
}

function Stat({ label, value, sub, tone }: {
  label: string; value: string; sub?: string; tone?: "accent" | "danger" | "warn";
}) {
  const color =
    tone === "accent" ? "text-accent" : tone === "danger" ? "text-danger"
      : tone === "warn" ? "text-warn" : "text-ink";
  return (
    <div className="flex flex-col gap-1 border-t border-line py-4">
      <span className="eyebrow">{label}</span>
      <span className={`data text-2xl ${color}`}>{value}</span>
      {sub && <span className="data text-xs text-ink-faint">{sub}</span>}
    </div>
  );
}

export default function OrgExplorer({ orgs }: { orgs: OrgNode[] }) {
  const rows = useMemo(() => flatten(orgs), [orgs]);
  const [sel, setSel] = useState<string>(orgs[0]?.org_id ?? "");
  const node = useMemo(
    () => rows.find((r) => r.n.org_id === sel)?.n ?? orgs[0],
    [rows, sel, orgs],
  );
  const maxSave = Math.max(1, ...rows.map((r) => r.n.kpi.potential_savings || 0));
  if (!node) return null;
  const k = node.kpi;

  return (
    <div className="grid gap-10 lg:grid-cols-[minmax(0,22rem)_1fr]">
      {/* индекс организаций */}
      <nav className="flex flex-col">
        <span className="eyebrow mb-3">Индекс · {rows.length} узлов</span>
        <ul>
          {rows.map(({ n, depth }, i) => {
            const active = n.org_id === sel;
            const save = n.kpi.potential_savings || 0;
            return (
              <li key={n.org_id}>
                <button
                  onClick={() => setSel(n.org_id)}
                  className={`group grid w-full grid-cols-[1.6rem_1fr_auto] items-center gap-2
                    border-t border-line py-3 text-left transition-colors
                    ${active ? "text-accent" : "text-ink hover:text-ink-dim"}`}
                  style={{ paddingLeft: depth * 14 }}
                >
                  <span className="data text-[0.65rem] text-ink-faint">
                    {String(i + 1).padStart(2, "0")}
                  </span>
                  <span className="truncate text-sm">{n.name}</span>
                  <span className="data text-[0.65rem] text-ink-faint">
                    {num(n.vehicle_count)} ТС
                  </span>
                  <span className="col-span-3 mt-2 h-px bg-line-strong">
                    <span
                      className={`block h-px ${active ? "bg-accent" : "bg-ink-faint"}`}
                      style={{ width: `${(save / maxSave) * 100}%` }}
                    />
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      </nav>

      {/* KPI выбранного узла */}
      <div>
        <div className="mb-2 flex items-end justify-between gap-4">
          <h3 className="display text-3xl sm:text-4xl">{node.name}</h3>
          <span className="data shrink-0 text-xs text-ink-faint">
            {num(node.vehicle_count)} ТС · данные у {num(k.vehicles_with_data)}
          </span>
        </div>

        <div className="grid grid-cols-2 gap-x-10 md:grid-cols-3">
          <Stat label="Пробег" value={`${num(k.total_mileage_km)} км`} />
          <Stat label="Топливо" value={`${num(k.total_fuel_l)} л`}
            sub={`${num(k.weighted_fuel_per_100km, 1)} л/100км`} />
          <Stat label="Стоимость топлива" value={moneyShort(k.total_fuel_cost)}
            sub={k.fuel_price_kzt ? `${num(k.fuel_price_kzt)} ₸/л` : "цена не задана"} />
          <Stat label="Холостой ход" value={pct(k.idle_hours_share, 0)}
            sub={`топливо на простое ${moneyShort(k.idle_fuel_cost)}`} tone="warn" />
          <Stat label="Потенциал экономии" value={moneyShort(k.potential_savings)}
            sub="на простоях, за период" tone="accent" />
          <Stat label="Макс. скорость" value={`${num(k.max_speed_kmh)} км/ч`}
            tone={k.max_speed_kmh > 90 ? "danger" : undefined} />
        </div>

        {node.children?.length > 0 && (
          <p className="data mt-6 text-xs text-ink-faint">
            {money(k.total_fuel_cost)} топлива агрегировано по{" "}
            {node.children.length} дочерним узлам — выберите ДЗО в индексе для разреза.
          </p>
        )}
      </div>
    </div>
  );
}
