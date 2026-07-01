"use client";
import { useState } from "react";
import { FuelDetail } from "@/lib/api";
import { C, compactM, ru } from "@/lib/atlas";
import { Kpi, Panel, Td, Th, tableWrap, theadStyle, trRule } from "./ui";

const PAGE = 200;

export default function Fuel({ data, loading, inScope, dzoOf, fuelPrice, onVehicle }: {
  data: FuelDetail | null; loading: boolean;
  inScope: (vehicleId: string) => boolean;
  dzoOf: (vehicleId: string) => string;
  fuelPrice: number;
  onVehicle: (id: string, name?: string) => void;
}) {
  const [shown, setShown] = useState(PAGE);
  const [dzoSel, setDzoSel] = useState<string | null>(null);

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

  // ₸-перерасход/экономия из скоупа (норма × цена ГСМ)
  let overL = 0, econL = 0, withNorm = 0;
  for (const r of scoped) {
    if (r.norm_l100 != null) withNorm++;
    if (r.over_l == null) continue;
    if (r.over_l > 0) overL += r.over_l;
    else econL += -r.over_l;
  }

  // Расход по ДЗО, разбитый на 2 группы: подвижные (л/100) и спецтехника (л/мч).
  const avg = (a: number[]) => a.length ? a.reduce((x, y) => x + y, 0) / a.length : null;
  const dzoMap = new Map<string, { mob: number[]; spc: number[] }>();
  for (const r of scoped) {
    const d = dzoOf(r.vehicleId);
    const e = dzoMap.get(d) ?? { mob: [], spc: [] };
    if (r.mode === "km" && r.fact_l100 != null) e.mob.push(r.fact_l100);
    else if (r.mode === "mh" && r.fact_lmh != null) e.spc.push(r.fact_lmh);
    dzoMap.set(d, e);
  }
  const dzoCons = [...dzoMap.entries()]
    .map(([name, e]) => ({ name, mob: avg(e.mob), spc: avg(e.spc), mobN: e.mob.length, spcN: e.spc.length }))
    .filter((d) => d.mobN + d.spcN > 0)
    .sort((a, b) => (b.mob ?? b.spc ?? 0) - (a.mob ?? a.spc ?? 0));

  // Дрилл выбранного ДЗО: его ТС по расходу от большего к меньшему, в 2 группах.
  const drill = dzoSel ? scoped.filter((r) => dzoOf(r.vehicleId) === dzoSel) : [];
  const drillMob = drill.filter((r) => r.mode === "km" && r.fact_l100 != null)
    .sort((a, b) => (b.fact_l100 as number) - (a.fact_l100 as number));
  const drillSpc = drill.filter((r) => r.mode === "mh" && r.fact_lmh != null)
    .sort((a, b) => (b.fact_lmh as number) - (a.fact_lmh as number));

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

      {dzoSel && (
        <Panel span={12} title={`Расход ТС · ${dzoSel} — от большего к меньшему`}
          right={<span>{ru(drillMob.length)} подвижных · {ru(drillSpc.length)} спец · <span style={{ cursor: "pointer", color: C.blue }} onClick={() => setDzoSel(null)}>закрыть ✕</span></span>}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
            {[{ ttl: "Подвижные · л/100 км", list: drillMob, unit: "л/100", fld: "fact_l100" as const },
              { ttl: "Спецтехника · л/моточас", list: drillSpc, unit: "л/мч", fld: "fact_lmh" as const }].map((g) => (
              <div key={g.ttl}>
                <div style={{ fontSize: 11, fontWeight: 700, color: C.muted, margin: "0 0 6px" }}>{g.ttl} · {ru(g.list.length)} ТС</div>
                {tableWrap(<>
                  <thead><tr style={theadStyle}><Th>#</Th><Th>ТС</Th><Th right>Расход</Th><Th right>{g.fld === "fact_l100" ? "Пробег" : "Моточасы"}</Th><Th right>Перерасход ₸</Th></tr></thead>
                  <tbody>
                    {g.list.length ? g.list.map((r, i) => (
                      <tr key={r.vehicleId} style={{ ...trRule, cursor: "pointer" }} onClick={() => onVehicle(r.vehicleId, r.vehicle)}>
                        <Td color={C.faint}>{i + 1}</Td>
                        <Td bold>{r.vehicle || r.vehicleId}</Td>
                        <Td right color={C.red} bold>{ru(r[g.fld] as number, 1)} {g.unit}</Td>
                        <Td right color={C.muted}>{g.fld === "fact_l100" ? ru(r.mileage_km) : ru(r.moto_h, 1)}</Td>
                        <Td right color={r.over_l == null ? C.faint2 : r.over_l > 0 ? C.red : C.green}>
                          {r.over_l == null ? "—" : (r.over_l > 0 ? "+" : "−") + compactM(Math.abs(r.over_l) * price)}
                        </Td>
                      </tr>
                    )) : <tr><Td color={C.faint}>Нет ТС в группе</Td></tr>}
                  </tbody>
                </>)}
              </div>
            ))}
          </div>
        </Panel>
      )}

      <Panel span={5} title="Расход по ДЗО · подвижные / спец" right="клик — рейтинг ТС">
        {tableWrap(<>
          <thead><tr style={theadStyle}>
            <Th>ДЗО</Th><Th right>Ср. л/100</Th><Th right>Ср. л/мч</Th><Th right>ТС</Th>
          </tr></thead>
          <tbody>
            {dzoCons.length ? dzoCons.map((d) => (
              <tr key={d.name} style={{ ...trRule, cursor: "pointer", background: dzoSel === d.name ? "#eef4fd" : undefined }} onClick={() => setDzoSel(dzoSel === d.name ? null : d.name)}>
                <Td bold>{d.name}</Td>
                <Td right color={d.mob != null ? undefined : C.faint2}>{d.mob != null ? ru(d.mob, 1) : "—"}</Td>
                <Td right color={d.spc != null ? undefined : C.faint2}>{d.spc != null ? ru(d.spc, 1) : "—"}</Td>
                <Td right color={C.muted}>{ru(d.mobN + d.spcN)}</Td>
              </tr>
            )) : <tr><Td color={C.faint}>Нет данных по расходу в скоупе</Td></tr>}
          </tbody>
        </>)}
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
