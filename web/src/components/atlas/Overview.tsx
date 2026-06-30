"use client";
import { Economics } from "@/lib/api";
import { Agg, C, DzoRow, compactM, mlnTg, ru } from "@/lib/atlas";
import { BarRow, Donut, Gauge, Kpi, Legend, Panel, Td, Th, tableWrap, theadStyle, trRule } from "./ui";

const TYPE_COLORS = [C.blue, C.green, C.amber, C.teal, C.greySoft, "#7d6bd0", "#c46aa5", C.faint2];

export default function Overview({ rows, agg, eco, sensorCounts, overdueTotal, onSelectDzo, onJump }: {
  rows: DzoRow[]; agg: Agg; eco: Economics | null;
  sensorCounts: Record<string, number>; overdueTotal: number;
  onSelectDzo: (orgId: string) => void; onJump: (page: string) => void;
}) {
  const kpis = [
    { label: "Потенциал экономии", value: mlnTg(agg.potential), color: C.green, jump: "money" },
    { label: "COI / год", value: eco ? mlnTg(eco.coi_annual_kzt) : "—", color: C.amber, jump: "money" },
    { label: "Стоимость топлива", value: mlnTg(agg.fuelCost), color: C.ink, jump: "fuel" },
    { label: "₸ / км", value: agg.rateOk ? ru(agg.cpkm) + " ₸" : "—", color: C.teal, jump: "fuel" },
    { label: "Превышения", value: ru(agg.episodes), color: C.amber, jump: "violations" },
    { label: "Связь / просрочено ТО", value: Math.round(agg.sensorPct * 100) + "% · " + overdueTotal, color: C.blue, jump: "quality" },
  ];

  const byPot = [...rows].filter((r) => r.potential > 0).sort((a, b) => b.potential - a.potential).slice(0, 8);
  const maxPot = Math.max(1, ...byPot.map((r) => r.potential));

  const buckets = eco?.buckets ?? [];
  const maxBucket = Math.max(1, ...buckets.map((b) => b.potential_kzt));

  const byVeh = [...rows].sort((a, b) => b.veh - a.veh);
  const top = byVeh.slice(0, 7);
  const restVeh = byVeh.slice(7).reduce((a, r) => a + r.veh, 0);
  const totalVeh = agg.veh || 1;
  const parkSlices = [
    ...top.map((r, i) => ({ label: r.name, pct: r.veh / totalVeh * 100, color: TYPE_COLORS[i % TYPE_COLORS.length] })),
    ...(restVeh ? [{ label: "Прочие", pct: restVeh / totalVeh * 100, color: C.faint2 }] : []),
  ];

  const byViol = [...rows].filter((r) => r.episodes > 0).sort((a, b) => b.episodes - a.episodes).slice(0, 8);
  const maxViol = Math.max(1, ...byViol.map((r) => r.episodes));

  const link = sensorCounts;
  const linkTotal = (link.online ?? 0) + (link.stale ?? 0) + (link.offline ?? 0) || 1;
  const linkSeg = [
    { label: "Онлайн", v: link.online ?? 0, color: C.green },
    { label: "Молчит < сутки", v: link.stale ?? 0, color: C.amber },
    { label: "Офлайн", v: link.offline ?? 0, color: C.red },
  ];

  const matrix = [...rows].sort((a, b) => b.veh - a.veh);

  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(12,1fr)", gap: 12, alignContent: "start" }}>
      {kpis.map((k, i) => <Kpi key={i} label={k.label} value={k.value} color={k.color} onClick={() => onJump(k.jump)} />)}

      <Panel span={5} title="Потенциал экономии по ДЗО · млн ₸" right="клик — фильтр по ДЗО">
        <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
          {byPot.length ? byPot.map((r) => (
            <BarRow key={r.org_id} name={r.name} w={r.potential / maxPot * 100} value={compactM(r.potential)} color={C.green} onClick={() => onSelectDzo(r.org_id)} />
          )) : <Empty />}
        </div>
      </Panel>

      <Panel span={4} title="Структура потерь · по статьям">
        <div style={{ display: "flex", flexDirection: "column", gap: 11, paddingTop: 2 }}>
          {buckets.length ? buckets.map((b) => (
            <div key={b.key}>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11.5, color: C.muted, marginBottom: 5 }}>
                <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", paddingRight: 8 }}>
                  {b.label}{b.is_estimate ? " ≈" : ""}
                </span>
                <b className="num" style={{ color: C.ink }}>{compactM(b.potential_kzt)} ₸</b>
              </div>
              <div style={{ height: 9, background: C.track, borderRadius: 2, overflow: "hidden" }}>
                <div style={{ height: "100%", width: `${b.potential_kzt / maxBucket * 100}%`, background: b.is_estimate ? C.amber : C.blue }} />
              </div>
            </div>
          )) : <Empty />}
        </div>
        <Legend items={[{ color: C.blue, label: "измеримо" }, { color: C.amber, label: "≈ оценка" }]} />
      </Panel>

      <Panel span={3} title="Качество данных">
        <div style={{ padding: "8px 0 6px" }}>
          <Gauge pct={agg.sensorPct} label="связь ок" sub={`${agg.online} из ${agg.sensorTotal} терминалов`} />
        </div>
      </Panel>

      <Panel span={4} title="Парк по ДЗО">
        <Donut slices={parkSlices} />
      </Panel>

      <Panel span={5} title="Превышения по ДЗО" right="клик — фильтр по ДЗО">
        <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
          {byViol.length ? byViol.map((r) => {
            const t = r.pubEp + r.techEp || 1;
            return (
              <div key={r.org_id} onClick={() => onSelectDzo(r.org_id)} style={{ display: "flex", alignItems: "center", gap: 10, cursor: "pointer" }}>
                <div style={{ width: 96, fontSize: 11.5, color: C.muted, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{r.name}</div>
                <div style={{ flex: 1, height: 15, background: C.track, borderRadius: 2, overflow: "hidden", display: "flex" }}>
                  <div style={{ display: "flex", width: `${r.episodes / maxViol * 100}%`, height: "100%" }}>
                    <div style={{ width: `${r.pubEp / t * 100}%`, background: C.red }} />
                    <div style={{ width: `${r.techEp / t * 100}%`, background: C.blueSoft }} />
                  </div>
                </div>
                <div className="num" style={{ width: 40, textAlign: "right", fontSize: 11.5, fontWeight: 600 }}>{ru(r.episodes)}</div>
              </div>
            );
          }) : <Empty />}
        </div>
        <Legend items={[{ color: C.red, label: "дороги общего пользования (КоАП)" }, { color: C.blueSoft, label: "технодороги (СТ КАП)" }]} />
      </Panel>

      <Panel span={3} title="Связь терминалов">
        <div style={{ display: "flex", height: 18, borderRadius: 3, overflow: "hidden", marginBottom: 11 }}>
          {linkSeg.map((s, i) => <div key={i} style={{ width: `${s.v / linkTotal * 100}%`, background: s.color }} />)}
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {linkSeg.map((s, i) => (
            <div key={i} style={{ display: "flex", alignItems: "center", gap: 7, fontSize: 11, color: C.muted }}>
              <span style={{ width: 8, height: 8, borderRadius: 2, background: s.color }} />
              <span style={{ flex: 1 }}>{s.label}</span>
              <b className="num">{ru(s.v)}</b>
            </div>
          ))}
        </div>
      </Panel>

      <Panel span={12} title="Матрица по ДЗО" right="клик по строке — фильтр по ДЗО">
        {tableWrap(<>
          <thead><tr style={theadStyle}>
            <Th>ДЗО</Th><Th right>ТС</Th><Th right>Потенциал ₸</Th><Th right>Топливо ₸</Th>
            <Th right>₸/км</Th><Th right>л/100</Th><Th right>Превышения</Th><Th right>Связь</Th><Th right>ТО</Th>
          </tr></thead>
          <tbody>
            {matrix.map((r) => (
              <tr key={r.org_id} style={{ ...trRule, cursor: "pointer" }} onClick={() => onSelectDzo(r.org_id)}>
                <Td bold>{r.name}</Td>
                <Td right color={C.muted}>{ru(r.veh)}</Td>
                <Td right color={C.green}>{r.potential ? compactM(r.potential) : "—"}</Td>
                <Td right>{compactM(r.fuelCost)}</Td>
                <Td right color={r.rateOk ? undefined : C.faint2}>{r.rateOk ? ru(r.cpkm) : "—"}</Td>
                <Td right color={!r.rateOk ? C.faint2 : r.l100 > 60 ? C.amber : undefined}>{r.rateOk ? ru(r.l100, 1) : "—"}</Td>
                <Td right>{ru(r.episodes)}</Td>
                <Td right color={r.sensorPct < 0.8 ? C.amber : C.green}><b>{Math.round(r.sensorPct * 100)}%</b></Td>
                <Td right color={r.overdue > 0 ? C.red : C.muted}>{r.overdue}</Td>
              </tr>
            ))}
            <tr style={{ borderTop: `2px solid ${C.line}`, fontWeight: 700 }}>
              <Td>Итого ({rows.length} ДЗО)</Td>
              <Td right>{ru(agg.veh)}</Td>
              <Td right color={C.green}>{compactM(agg.potential)}</Td>
              <Td right>{compactM(agg.fuelCost)}</Td>
              <Td right>{agg.rateOk ? ru(agg.cpkm) : "—"}</Td>
              <Td right>{agg.rateOk ? ru(agg.l100, 1) : "—"}</Td>
              <Td right>{ru(agg.episodes)}</Td>
              <Td right>{Math.round(agg.sensorPct * 100)}%</Td>
              <Td right>{overdueTotal}</Td>
            </tr>
          </tbody>
        </>)}
      </Panel>
    </div>
  );
}

function Empty() {
  return <div style={{ fontSize: 11.5, color: C.faint, padding: "6px 0" }}>Нет данных за период</div>;
}
