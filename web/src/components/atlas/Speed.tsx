"use client";
import { Recommendation, ViolationRow } from "@/lib/api";
import { Agg, C, DzoRow, ru, severityBuckets, zonesFromViol } from "@/lib/atlas";
import { BarRow, Kpi, Panel, Td, Th, tableWrap, theadStyle, trRule } from "./ui";

export default function Speed({ rows, agg, recs, violRows, onVehicle }: {
  rows: DzoRow[]; agg: Agg; recs: Recommendation[]; violRows: ViolationRow[];
  onVehicle: (id: string, name?: string) => void;
}) {
  const sev = severityBuckets(violRows);
  const kpis = [
    { label: "Всего событий", value: ru(violRows.length || agg.episodes), color: C.ink },
    { label: "6–20 км/ч", value: ru(sev.s6), color: C.blue },
    { label: "20–40 км/ч", value: ru(sev.s20), color: C.amber },
    { label: "40+ км/ч", value: ru(sev.s40), color: C.red },
  ];

  const byViol = [...rows].filter((r) => r.episodes > 0).sort((a, b) => b.episodes - a.episodes).slice(0, 8);
  const maxViol = Math.max(1, ...byViol.map((r) => r.episodes));

  const maxSev = Math.max(1, sev.s6, sev.s20, sev.s40);
  const sevBars = [
    { label: "6–20", val: sev.s6, h: sev.s6 / maxSev * 100, color: C.blue },
    { label: "20–40", val: sev.s20, h: sev.s20 / maxSev * 100, color: C.amber },
    { label: "40+", val: sev.s40, h: sev.s40 / maxSev * 100, color: C.red },
  ];

  const topViolators = [...recs].sort((a, b) => b.episodes - a.episodes).slice(0, 8);
  const maxEp = Math.max(1, ...topViolators.map((r) => r.episodes));

  const zones = zonesFromViol(violRows).slice(0, 8);

  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(12,1fr)", gap: 12, alignContent: "start" }}>
      {kpis.map((k, i) => <Kpi key={i} {...k} span={3} />)}

      <Panel span={6} title="Превышения по ДЗО" right="общ. дороги · технодороги">
        <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
          {byViol.map((r) => {
            const t = r.pubEp + r.techEp || 1;
            return (
              <div key={r.org_id} style={{ display: "flex", alignItems: "center", gap: 10 }}>
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
          })}
        </div>
      </Panel>

      <Panel span={3} title="Тяжесть">
        <div style={{ display: "flex", gap: 12, alignItems: "flex-end", height: 150 }}>
          {sevBars.map((s, i) => (
            <div key={i} style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", gap: 6, height: "100%" }}>
              <div className="num" style={{ fontSize: 13, fontWeight: 700 }}>{ru(s.val)}</div>
              <div style={{ width: "100%", flex: 1, display: "flex", alignItems: "flex-end" }}>
                <div style={{ width: "100%", height: `${Math.min(100, s.h)}%`, background: s.color, borderRadius: "2px 2px 0 0" }} />
              </div>
              <div style={{ fontSize: 10, color: C.faint }}>{s.label}</div>
            </div>
          ))}
        </div>
      </Panel>

      <Panel span={3} title="КоАП ст.592">
        <div style={{ fontSize: 11, color: C.muted, lineHeight: 1.55 }}>
          МРП 2026 = 4 325 ₸ · шкала 5/10/20/40 МРП. Штраф — дороги общего пользования;
          технодороги — дисциплинарная ответственность СТ КАП.
        </div>
      </Panel>

      <Panel span={7} title="Топ ТС по превышениям">
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {topViolators.length ? topViolators.map((r) => (
            <BarRow key={r.terminal_id} name={r.name || r.terminal_id} w={r.episodes / maxEp * 100}
              value={ru(r.episodes)} color={r.worst_severity === "грубое" ? C.red : C.amber} h={13}
              onClick={() => onVehicle(r.terminal_id, r.name)} />
          )) : <div style={{ fontSize: 11.5, color: C.faint }}>Нет данных</div>}
        </div>
      </Panel>

      <Panel span={5} title="Зоны с превышениями">
        {tableWrap(<>
          <thead><tr style={theadStyle}>
            <Th>Геозона</Th><Th>Лимит</Th><Th right>Макс</Th><Th right>Событий</Th>
          </tr></thead>
          <tbody>
            {zones.length ? zones.map((z, i) => (
              <tr key={i} style={trRule}>
                <Td bold>{z.name}</Td>
                <Td color={C.muted}>{z.limit}</Td>
                <Td right color={C.red} bold>+{z.max}</Td>
                <Td right>{ru(z.events)}</Td>
              </tr>
            )) : <tr><Td color={C.faint}>Нет геозонных превышений за период</Td></tr>}
          </tbody>
        </>)}
      </Panel>
    </div>
  );
}
