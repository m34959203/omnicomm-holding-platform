"use client";
import { useState } from "react";
import { FuelDetail } from "@/lib/api";
import { C, compactM, ru } from "@/lib/atlas";
import { BarRow, Kpi, Panel, Td, Th, tableWrap, theadStyle, trRule } from "./ui";

const PAGE = 200;

export default function Fuel({ data, loading, inScope, dzoOf, fuelPrice, onVehicle }: {
  data: FuelDetail | null; loading: boolean;
  inScope: (vehicleId: string) => boolean;
  dzoOf: (vehicleId: string) => string;
  fuelPrice: number;
  onVehicle: (id: string, name?: string) => void;
}) {
  const [shown, setShown] = useState(PAGE);

  if (loading || !data) {
    return <div style={{ display: "grid", gridTemplateColumns: "repeat(12,1fr)", gap: 12 }}>
      <Panel span={12} title="Топливо · работа группы по ТС">
        <div style={{ fontSize: 12, color: C.faint, padding: "20px 0" }}>{loading ? "Считаем топливо из архива…" : "Нет данных"}</div>
      </Panel>
    </div>;
  }

  const price = fuelPrice || 0;
  const scoped = data.rows.filter((r) => inScope(r.vehicleId));
  const view = scoped.slice(0, shown);
  const prov = !data.norms_approved;

  // ₸-перерасход/экономия и rollup по ДЗО — из скоупа (норма × цена ГСМ)
  let overL = 0, econL = 0, withNorm = 0;
  const byDzo = new Map<string, number>();
  for (const r of scoped) {
    if (r.norm_l100 != null) withNorm++;
    if (r.over_l == null) continue;
    if (r.over_l > 0) { overL += r.over_l; byDzo.set(dzoOf(r.vehicleId), (byDzo.get(dzoOf(r.vehicleId)) ?? 0) + r.over_l); }
    else econL += -r.over_l;
  }
  const dzoBars = [...byDzo.entries()].map(([name, l]) => ({ name, kzt: l * price }))
    .sort((a, b) => b.kzt - a.kzt).slice(0, 8);
  const maxDzo = Math.max(1, ...dzoBars.map((d) => d.kzt));

  const note = `${data.from} — ${data.to} · ${ru(scoped.length)} ТС · норма у ${ru(withNorm)}`
    + (data.capped ? ` · top-${ru(data.returned)} из ${ru(data.total)}` : "");

  // факт/норма с единицей по режиму (дорожный л/100 vs моточасный л/мч)
  const U = (v: number | null, unit: string) => v != null ? `${ru(v, 1)} ${unit}` : "—";
  const factCell = (r: typeof view[number]) =>
    r.mode === "mh" ? U(r.fact_lmh, "л/мч")
      : r.fact_l100 != null ? U(r.fact_l100, "л/100")
        : r.fact_lmh != null ? U(r.fact_lmh, "л/мч") : "—";
  const normCell = (r: typeof view[number]) =>
    r.mode === "mh" ? U(r.norm_lmh, "л/мч")
      : r.mode === "km" ? U(r.norm_l100, "л/100") : "—";

  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(12,1fr)", gap: 12, alignContent: "start" }}>
      <Kpi label="Перерасход ₸" value={compactM(overL * price) + " ₸"} color={C.red} sub={prov ? "предв. · по нормам" : "по нормам"} span={4} />
      <Kpi label="Экономия ₸" value={compactM(econL * price) + " ₸"} color={C.green} sub={`${ru(Math.round(overL))} л перер. · ${ru(Math.round(econL))} л эк.`} span={4} />
      <Kpi label="ТС с нормой" value={`${ru(withNorm)} / ${ru(scoped.length)}`} color={C.blue} sub={`справочник v${data.norms_version}`} span={4} />

      {prov && (
        <div style={{ gridColumn: "span 12", background: "#fbf3e2", border: "1px solid #ecd9a8", borderRadius: 6, padding: "8px 12px", fontSize: 11.5, color: "#7a5b12" }}>
          ⚠ Нормы <b>предварительные</b> (отраслевой ориентир по категории + норма Omnicomm), не согласованы → перерасход ориентировочный.
          Замени значения в <code>data/fuel_norms.json</code> на утверждённые и поставь <code>approved: true</code>.
        </div>
      )}

      <Panel span={5} title="Перерасход топлива по ДЗО · ₸ (предв.)">
        <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
          {dzoBars.length ? dzoBars.map((d) => (
            <BarRow key={d.name} name={d.name} w={d.kzt / maxDzo * 100} value={compactM(d.kzt)} color={C.red} />
          )) : <div style={{ fontSize: 11.5, color: C.faint }}>Нет перерасхода в скоупе</div>}
        </div>
      </Panel>

      <Panel span={7} title="Работа группы по ТС · топливо и норма" right={note}>
        {tableWrap(<>
          <thead><tr style={theadStyle}>
            <Th>ТС</Th><Th>ДЗО</Th><Th right>Пробег</Th><Th right>Моточасы</Th>
            <Th right>Факт</Th><Th right>Норма*</Th><Th right>Перерасход ₸</Th><Th right>Заправки</Th><Th right>Сливы</Th>
          </tr></thead>
          <tbody>
            {view.length ? view.map((r) => (
              <tr key={r.vehicleId} style={{ ...trRule, cursor: "pointer" }} onClick={() => onVehicle(r.vehicleId, r.vehicle)}>
                <Td bold>{r.vehicle || r.vehicleId}</Td>
                <Td color={C.muted}>{dzoOf(r.vehicleId)}</Td>
                <Td right color={C.muted}>{ru(r.mileage_km)}</Td>
                <Td right color={C.muted}>{ru(r.moto_h, 1)}</Td>
                <Td right color={factCell(r) === "—" ? C.faint2 : undefined}>{factCell(r)}</Td>
                <Td right color={C.faint2}>{normCell(r)}</Td>
                <Td right color={r.over_l == null ? C.faint2 : r.over_l > 0 ? C.red : C.green} bold={!!r.over_l}>
                  {r.over_l == null ? "—" : (r.over_l > 0 ? "+" : "−") + compactM(Math.abs(r.over_l) * price)}
                </Td>
                <Td right color={r.refuel_l ? C.green : C.faint2}>{r.refuel_l ? ru(r.refuel_l) : "—"}</Td>
                <Td right color={r.drain_l ? C.red : C.faint2}>{r.drain_l ? ru(r.drain_l) : "—"}</Td>
              </tr>
            )) : <tr><Td color={C.faint}>Нет данных по топливу в скоупе</Td></tr>}
          </tbody>
        </>)}
        {scoped.length > shown && (
          <div style={{ padding: "10px 13px 4px" }}>
            <button onClick={() => setShown((s) => s + PAGE)}
              style={{ padding: "6px 14px", border: `1px solid ${C.line}`, borderRadius: 6, background: "#fff", color: C.blue, fontSize: 11.5, fontWeight: 600, cursor: "pointer" }}>
              Показать ещё · из {ru(scoped.length)}
            </button>
          </div>
        )}
        <div style={{ fontSize: 10.5, color: C.faint, padding: "8px 13px 2px", lineHeight: 1.5 }}>
          Факт/норма: дорожная техника — <b>л/100</b> (пробег ≥ 100 км), моточасная — <b>л/мч</b> (моточасы ≥ 20).
          Перерасход — только где расход достоверен (АТЗ/ёмкости/выдача → «—»). *Нормы предварительные
          (<code>data/fuel_norms.json</code>). Цена ГСМ {ru(price)} ₸/л. Смены требуют графика смен.
        </div>
      </Panel>
    </div>
  );
}
