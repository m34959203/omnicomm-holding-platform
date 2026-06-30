"use client";
import { Maintenance } from "@/lib/api";
import { C, DzoRow, ru } from "@/lib/atlas";
import { BarRow, Panel, Td, Th, tableWrap, theadStyle, trRule } from "./ui";

const BADGE: Record<string, { bg: string; color: string; label: string }> = {
  "просрочено": { bg: "#fae5e3", color: C.red, label: "просрочено" },
  "ожидается": { bg: "#f7eed8", color: "#bd8413", label: "скоро" },
  "ok": { bg: "#e4f3ea", color: C.green, label: "в норме" },
};

export default function Maint({ rows, maint, onVehicle }: {
  rows: DzoRow[]; maint: Maintenance | null; onVehicle: (id: string, name?: string) => void;
}) {
  const counts = maint?.counts ?? {};
  const kpis = [
    { label: "в норме", value: ru(counts.ok ?? 0), color: C.green },
    { label: "скоро ТО", value: ru(counts["ожидается"] ?? 0), color: C.amber },
    { label: "просрочено", value: ru(counts["просрочено"] ?? 0), color: C.red },
  ];

  const byOverdue = [...rows].filter((r) => r.overdue > 0).sort((a, b) => b.overdue - a.overdue).slice(0, 8);
  const maxOver = Math.max(1, ...byOverdue.map((r) => r.overdue));

  const prio: Record<string, number> = { "просрочено": 0, "ожидается": 1, "ok": 2 };
  const items = [...(maint?.items ?? [])]
    .sort((a, b) => (prio[a.status] ?? 9) - (prio[b.status] ?? 9) || b.mh_since - a.mh_since)
    .slice(0, 12);

  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(12,1fr)", gap: 12, alignContent: "start" }}>
      {kpis.map((k, i) => (
        <div key={i} style={{ background: C.panel, border: `1px solid ${C.line}`, borderRadius: 6, boxShadow: "0 1px 2px rgba(20,30,50,.05)", gridColumn: "span 4", padding: 14, display: "flex", alignItems: "center", gap: 13 }}>
          <span style={{ width: 12, height: 12, borderRadius: "50%", background: k.color }} />
          <div>
            <div className="num" style={{ fontSize: 24, fontWeight: 700 }}>{k.value}</div>
            <div style={{ fontSize: 11.5, color: C.muted2 }}>{k.label}</div>
          </div>
        </div>
      ))}

      <Panel span={5} title="Просрочено ТО по ДЗО">
        <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
          {byOverdue.length ? byOverdue.map((r) => (
            <BarRow key={r.org_id} name={r.name} w={r.overdue / maxOver * 100} value={String(r.overdue)} color={C.amber} h={14} />
          )) : <div style={{ fontSize: 11.5, color: C.faint }}>Просроченных ТО нет</div>}
        </div>
      </Panel>

      <Panel span={7} title="Наработка и план">
        {tableWrap(<>
          <thead><tr style={theadStyle}>
            <Th>ТС</Th><Th right>Наработка</Th><Th right>Пробег</Th><Th>Причина</Th><Th right>Статус</Th>
          </tr></thead>
          <tbody>
            {items.length ? items.map((it) => {
              const b = BADGE[it.status] ?? { bg: C.track, color: C.muted, label: it.status };
              return (
                <tr key={it.terminal_id} style={{ ...trRule, cursor: "pointer" }} onClick={() => onVehicle(it.terminal_id, it.name ?? undefined)}>
                  <Td bold>{it.name || it.terminal_id}</Td>
                  <Td right>{ru(it.mh_since)} мч</Td>
                  <Td right color={C.muted}>{ru(it.km_since)} км</Td>
                  <Td color={C.muted}>{it.reason}</Td>
                  <Td right>
                    <span style={{ fontSize: 11, fontWeight: 600, padding: "2px 8px", borderRadius: 12, background: b.bg, color: b.color }}>{b.label}</span>
                  </Td>
                </tr>
              );
            }) : <tr><Td color={C.faint}>Нет данных по наработке</Td></tr>}
          </tbody>
        </>)}
      </Panel>

      {maint?.note && (
        <Panel span={12}>
          <div style={{ fontSize: 11, color: C.faint, lineHeight: 1.5 }}>{maint.note}</div>
        </Panel>
      )}
    </div>
  );
}
