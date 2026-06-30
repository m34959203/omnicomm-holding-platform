"use client";
import { useState } from "react";
import { ViolationsDetail } from "@/lib/api";
import { C, ru } from "@/lib/atlas";
import { Panel, Td, Th, tableWrap, theadStyle, trRule } from "./ui";

const PAGE = 200;

function dtfmt(ts: number): string {
  if (!ts) return "—";
  const d = new Date(ts * 1000);
  return d.toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}
function durfmt(s: number): string {
  if (s < 60) return `${s} с`;
  const m = Math.floor(s / 60), ss = s % 60;
  return ss ? `${m} м ${ss} с` : `${m} м`;
}

export default function Violations({ data, loading, inScope, onVehicle }: {
  data: ViolationsDetail | null; loading: boolean;
  inScope: (vehicleId: string) => boolean;
  onVehicle: (id: string, name?: string) => void;
}) {
  const [shown, setShown] = useState(PAGE);

  if (loading || !data) {
    return <div style={{ display: "grid", gridTemplateColumns: "repeat(12,1fr)", gap: 12 }}>
      <Panel span={12} title="Таблица нарушений · по средней скорости">
        <div style={{ fontSize: 12, color: C.faint, padding: "20px 0" }}>{loading ? "Считаем нарушения из архива…" : "Нет данных"}</div>
      </Panel>
    </div>;
  }

  const scoped = data.rows.filter((r) => inScope(r.vehicleId));
  const view = scoped.slice(0, shown);
  const note = `${data.from} — ${data.to} · найдено ${ru(scoped.length)}`
    + (data.capped ? ` · показ top-${ru(data.returned)} из ${ru(data.total)} по парку` : "");

  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(12,1fr)", gap: 12 }}>
      <Panel span={12} title="Таблица нарушений · сортировка по средней скорости" right={note}>
        {tableWrap(<>
          <thead><tr style={theadStyle}>
            <Th>Дата и время</Th><Th>ТС</Th><Th>Локация (геозона)</Th>
            <Th right>Длит.</Th><Th right>Ср. км/ч</Th><Th right>Макс</Th>
            <Th right>Лимит</Th><Th right>Превыш.</Th><Th>Дорога</Th><Th right>Штраф ₸</Th>
          </tr></thead>
          <tbody>
            {view.length ? view.map((r, i) => (
              <tr key={i} style={{ ...trRule, cursor: "pointer" }} onClick={() => onVehicle(r.vehicleId, r.vehicle)}>
                <Td color={C.muted}>{dtfmt(r.start_ts)}</Td>
                <Td bold>{r.vehicle || r.vehicleId}</Td>
                <Td color={C.muted}>{r.geozone}</Td>
                <Td right color={C.muted}>{durfmt(r.duration_s)}</Td>
                <Td right>{r.avg_speed_kmh != null ? ru(r.avg_speed_kmh, 1) : "—"}</Td>
                <Td right color={C.red} bold>{ru(r.max_speed_kmh, 1)}</Td>
                <Td right color={C.muted}>{r.limit_kmh}</Td>
                <Td right color={r.excess_kmh >= 40 ? C.red : r.excess_kmh >= 20 ? C.amber : C.blue} bold>+{ru(r.excess_kmh, 1)}</Td>
                <Td><span style={{ fontSize: 10.5, fontWeight: 600, padding: "1px 7px", borderRadius: 10, background: r.public_road ? "#fae5e3" : "#eef1f5", color: r.public_road ? C.red : C.muted2 }}>{r.public_road ? "общего польз." : "технодорога"}</span></Td>
                <Td right color={r.fine_kzt ? C.ink : C.faint2} bold={!!r.fine_kzt}>{r.fine_kzt ? ru(r.fine_kzt) : "—"}</Td>
              </tr>
            )) : <tr><Td color={C.faint}>Нет нарушений за период в выбранном скоупе</Td></tr>}
          </tbody>
        </>)}
        {scoped.length > shown && (
          <div style={{ padding: "10px 13px 4px" }}>
            <button onClick={() => setShown((s) => s + PAGE)}
              style={{ padding: "6px 14px", border: `1px solid ${C.line}`, borderRadius: 6, background: "#fff", color: C.blue, fontSize: 11.5, fontWeight: 600, cursor: "pointer" }}>
              Показать ещё {ru(Math.min(PAGE, scoped.length - shown))} · из {ru(scoped.length)}
            </button>
          </div>
        )}
        <div style={{ fontSize: 10.5, color: C.faint, padding: "8px 13px 2px", lineHeight: 1.5 }}>
          Средняя скорость — из визит-агрегата Omnicomm; «—» где данных нет или они некорректны (avg&gt;max). Штраф ₸ — только дороги общего пользования (КоАП ст.592).
        </div>
      </Panel>
    </div>
  );
}
