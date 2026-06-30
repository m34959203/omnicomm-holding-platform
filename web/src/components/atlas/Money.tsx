"use client";
import { Economics } from "@/lib/api";
import { Agg, C, DzoRow, compactM, mlnTg, ru } from "@/lib/atlas";
import { BarRow, Donut, Kpi, Legend, Panel } from "./ui";

const TYPE_COLORS = [C.blue, C.green, C.amber, C.teal, C.greySoft, "#7d6bd0", "#c46aa5", C.faint2];

export default function Money({ rows, agg, eco, overrunKzt, overrunProvisional, onSelectDzo, onJump }: {
  rows: DzoRow[]; agg: Agg; eco: Economics | null;
  overrunKzt: number; overrunProvisional: boolean;
  onSelectDzo: (orgId: string) => void; onJump: (page: string) => void;
}) {
  const kpis = [
    { label: "Потенциал экономии", value: mlnTg(agg.potential), color: C.green, sub: "холостой ход + износ", jump: "fuel" },
    { label: "Перерасход к норме", value: overrunKzt > 0 ? mlnTg(overrunKzt) : "—", color: C.red, sub: overrunProvisional ? "предв. · детали в «Топливо»" : "детали в «Топливо»", jump: "fuel" },
    { label: "COI / месяц", value: eco ? mlnTg(eco.coi_monthly_kzt) : "—", color: C.amber, sub: "стоимость простоя", jump: "maint" },
    { label: "COI / год", value: eco ? mlnTg(eco.coi_annual_kzt) : "—", color: C.amber, sub: "≈ оценка", jump: "maint" },
    { label: "Стоимость топлива", value: mlnTg(agg.fuelCost), color: C.ink, sub: "за период", jump: "fuel" },
    { label: "₸ / км", value: agg.rateOk ? ru(agg.cpkm) + " ₸" : "—", color: C.teal, sub: "по движущимся ТС", jump: "fuel" },
  ];

  const byPot = [...rows].filter((r) => r.potential > 0).sort((a, b) => b.potential - a.potential).slice(0, 8);
  const maxPot = Math.max(1, ...byPot.map((r) => r.potential));

  const buckets = eco?.buckets ?? [];
  const maxBucket = Math.max(1, ...buckets.map((b) => b.potential_kzt));

  const byVeh = [...rows].sort((a, b) => b.veh - a.veh);
  const top = byVeh.slice(0, 6);
  const restVeh = byVeh.slice(6).reduce((a, r) => a + r.veh, 0);
  const totalVeh = agg.veh || 1;
  const parkSlices = [
    ...top.map((r, i) => ({ label: r.name, pct: r.veh / totalVeh * 100, color: TYPE_COLORS[i % TYPE_COLORS.length] })),
    ...(restVeh ? [{ label: "Прочие", pct: restVeh / totalVeh * 100, color: C.faint2 }] : []),
  ];

  const cpkm = [...rows].filter((r) => r.rateOk).sort((a, b) => b.cpkm - a.cpkm).slice(0, 8);
  const maxCpkm = Math.max(1, ...cpkm.map((r) => r.cpkm));

  const lkm = [...rows].filter((r) => r.rateOk).sort((a, b) => b.l100 - a.l100).slice(0, 8);
  const maxL = Math.max(1, ...lkm.map((r) => r.l100));

  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(12,1fr)", gap: 12, alignContent: "start" }}>
      {kpis.map((k, i) => <Kpi key={i} label={k.label} value={k.value} color={k.color} sub={k.sub} onClick={() => onJump(k.jump)} />)}

      <Panel span={5} title="Потенциал экономии по ДЗО · млн ₸" right="клик — фильтр по ДЗО">
        <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
          {byPot.map((r) => <BarRow key={r.org_id} name={r.name} w={r.potential / maxPot * 100} value={compactM(r.potential)} color={C.green} onClick={() => onSelectDzo(r.org_id)} />)}
        </div>
      </Panel>

      <Panel span={4} title="Структура потерь · по статьям" right="холдинг">
        <div style={{ display: "flex", flexDirection: "column", gap: 11, paddingTop: 2 }}>
          {buckets.map((b) => (
            <div key={b.key}>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11.5, color: C.muted, marginBottom: 5 }}>
                <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", paddingRight: 8 }}>{b.label}{b.is_estimate ? " ≈" : ""}</span>
                <b className="num" style={{ color: C.ink }}>{compactM(b.potential_kzt)} ₸</b>
              </div>
              <div style={{ height: 9, background: C.track, borderRadius: 2, overflow: "hidden" }}>
                <div style={{ height: "100%", width: `${b.potential_kzt / maxBucket * 100}%`, background: b.is_estimate ? C.amber : C.blue }} />
              </div>
            </div>
          ))}
        </div>
        <Legend items={[{ color: C.blue, label: "измеримо" }, { color: C.amber, label: "≈ оценка" }]} />
      </Panel>

      <Panel span={3} title="Парк по ДЗО">
        <Donut slices={parkSlices} size={84} hole={18} />
      </Panel>

      <Panel span={6} title="Стоимость 1 км по ДЗО · ₸" right="клик — фильтр по ДЗО">
        <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
          {cpkm.map((r) => <BarRow key={r.org_id} name={r.name} w={r.cpkm / maxCpkm * 100} value={ru(r.cpkm) + " ₸"} color={C.teal} h={13} onClick={() => onSelectDzo(r.org_id)} />)}
        </div>
      </Panel>

      <Panel span={6} title="Расход л/100 км по ДЗО · факт" right="клик — фильтр · норма в «Топливо»">
        <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
          {lkm.map((r) => <BarRow key={r.org_id} name={r.name} w={r.l100 / maxL * 100} value={ru(r.l100, 1) + " л"} color={C.blue} h={13} onClick={() => onSelectDzo(r.org_id)} />)}
        </div>
      </Panel>
    </div>
  );
}
