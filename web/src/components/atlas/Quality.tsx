"use client";
import { SensorHealth } from "@/lib/api";
import { C, DzoRow, ru } from "@/lib/atlas";
import { BarRow, Gauge, Panel, Td, Th, tableWrap, theadStyle, trRule } from "./ui";
import { ago } from "@/lib/format";

const STATUS_LABEL: Record<string, string> = {
  online: "Данные < 30 мин",
  stale: "Данные 30 мин – 24 ч",
  offline: "Нет данных > 24 ч",
  unknown: "Нет данных в программе",
};
const STATUS_COLOR: Record<string, string> = {
  online: C.green, stale: C.amber, offline: C.red, unknown: C.faint2,
};

export default function Quality({ rows, sensor, onSelectDzo, onVehicle }: {
  rows: DzoRow[]; sensor: SensorHealth | null;
  onSelectDzo: (orgId: string) => void; onVehicle: (id: string, name?: string) => void;
}) {
  const counts = sensor?.counts ?? {};
  const total = (counts.online ?? 0) + (counts.stale ?? 0) + (counts.offline ?? 0) + (counts.unknown ?? 0) || 1;
  const okPct = (counts.online ?? 0) / total;

  const dist = ["online", "stale", "offline", "unknown"]
    .filter((k) => (counts[k] ?? 0) > 0)
    .map((k) => ({ label: STATUS_LABEL[k], v: counts[k] ?? 0, color: STATUS_COLOR[k] }));

  const byOrg = [...rows].filter((r) => r.sensorTotal > 0).sort((a, b) => a.sensorPct - b.sensorPct).slice(0, 10);

  const checkStatus = (m: { power?: string | null; missing: string[] }) => {
    if (m.power === "critical") return { label: "нет питания", color: C.red };
    if (m.power === "low") return { label: "низкое напр.", color: C.amber };
    if (m.missing?.length) return { label: "проверить", color: C.amber };
    return { label: "ок", color: C.green };
  };
  const terms = (sensor?.missing_capabilities ?? []).slice(0, 14);
  const lastSeenById = new Map((sensor?.terminals ?? []).map((t) => [t.terminal_id, t]));

  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(12,1fr)", gap: 12, alignContent: "start" }}>
      <Panel span={4} title="Качество данных" right="% ТС с данными < 30 мин">
        <div style={{ padding: "14px 0 6px" }}>
          <Gauge pct={okPct} size={120} sub={`${ru(counts.online ?? 0)} из ${ru(total)} с данными < 30 мин`} />
        </div>
      </Panel>

      <Panel span={4} title="Распределение статусов">
        <div style={{ display: "flex", height: 20, borderRadius: 3, overflow: "hidden", marginBottom: 13 }}>
          {dist.map((s, i) => <div key={i} style={{ width: `${s.v / total * 100}%`, background: s.color }} />)}
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {dist.map((s, i) => (
            <div key={i} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", fontSize: 11.5, color: C.muted }}>
              <span style={{ display: "flex", alignItems: "center", gap: 7 }}>
                <span style={{ width: 9, height: 9, borderRadius: 2, background: s.color }} />{s.label}
              </span>
              <b className="num">{ru(s.v)}</b>
            </div>
          ))}
        </div>
      </Panel>

      <Panel span={4} title="Связь % по ДЗО" right="клик — фильтр">
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {byOrg.map((r) => (
            <BarRow key={r.org_id} name={r.name} w={r.sensorPct * 100} value={Math.round(r.sensorPct * 100) + "%"}
              color={r.sensorPct < 0.8 ? C.amber : C.green} h={11} onClick={() => onSelectDzo(r.org_id)} />
          ))}
        </div>
      </Panel>

      <Panel span={12} title="Терминалы · требует проверки">
        {tableWrap(<>
          <thead><tr style={theadStyle}>
            <Th>ТС</Th><Th>Последний сигнал</Th><Th>Нет данных</Th><Th right>Напряжение</Th><Th right>Статус</Th>
          </tr></thead>
          <tbody>
            {terms.length ? terms.map((m) => {
              const st = checkStatus(m);
              const seen = lastSeenById.get(m.terminal_id);
              return (
                <tr key={m.terminal_id} style={{ ...trRule, cursor: "pointer" }} onClick={() => onVehicle(m.terminal_id, m.name ?? undefined)}>
                  <Td bold>{m.name || m.terminal_id}</Td>
                  <Td color={C.muted}>{seen?.last_seen ? ago(seen.last_seen) : "—"}</Td>
                  <Td color={C.muted}>{m.missing?.length ? m.missing.join(", ") : "—"}</Td>
                  <Td right color={C.muted}>{m.voltage != null ? ru(m.voltage, 1) + " В" : "—"}</Td>
                  <Td right color={st.color} bold>{st.label}</Td>
                </tr>
              );
            }) : <tr><Td color={C.faint}>Нет терминалов, требующих проверки</Td></tr>}
          </tbody>
        </>)}
      </Panel>
    </div>
  );
}
