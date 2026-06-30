"use client";
import { useState } from "react";
import { FuelDetail } from "@/lib/api";
import { C, ru } from "@/lib/atlas";
import { Panel, Td, Th, tableWrap, theadStyle, trRule } from "./ui";

const PAGE = 200;

export default function Fuel({ data, loading, inScope, dzoOf, onVehicle }: {
  data: FuelDetail | null; loading: boolean;
  inScope: (vehicleId: string) => boolean;
  dzoOf: (vehicleId: string) => string;
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

  const scoped = data.rows.filter((r) => inScope(r.vehicleId));
  const view = scoped.slice(0, shown);
  const note = `${data.from} — ${data.to} · ${ru(scoped.length)} ТС · норма Omnicomm у ${ru(data.with_norm)}`
    + (data.capped ? ` · top-${ru(data.returned)} из ${ru(data.total)} по пробегу` : "");

  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(12,1fr)", gap: 12, alignContent: "start" }}>
      <Panel span={12} title="Работа группы по ТС · топливо" right={note}>
        {tableWrap(<>
          <thead><tr style={theadStyle}>
            <Th>ТС</Th><Th>ДЗО</Th><Th right>Пробег км</Th><Th right>Моточасы</Th>
            <Th right>Расход л</Th><Th right>л/100</Th><Th right>Норма*</Th>
            <Th right>Заправки л</Th><Th right>Сливы л</Th><Th right>Выдача л</Th>
          </tr></thead>
          <tbody>
            {view.length ? view.map((r) => (
              <tr key={r.vehicleId} style={{ ...trRule, cursor: "pointer" }} onClick={() => onVehicle(r.vehicleId, r.vehicle)}>
                <Td bold>{r.vehicle || r.vehicleId}</Td>
                <Td color={C.muted}>{dzoOf(r.vehicleId)}</Td>
                <Td right color={C.muted}>{ru(r.mileage_km)}</Td>
                <Td right color={C.muted}>{ru(r.moto_h, 1)}</Td>
                <Td right bold>{ru(r.fuel_l)}</Td>
                <Td right color={r.fact_l100 == null ? C.faint2 : undefined}>{r.fact_l100 != null ? ru(r.fact_l100, 1) : "—"}</Td>
                <Td right color={C.faint2}>{r.norm_l100 != null ? ru(r.norm_l100, 1) : "—"}</Td>
                <Td right color={r.refuel_l ? C.green : C.faint2}>{r.refuel_l ? ru(r.refuel_l) : "—"}</Td>
                <Td right color={r.drain_l ? C.red : C.faint2}>{r.drain_l ? ru(r.drain_l) : "—"}</Td>
                <Td right color={r.delivery_l ? C.ink : C.faint2}>{r.delivery_l ? ru(r.delivery_l) : "—"}</Td>
              </tr>
            )) : <tr><Td color={C.faint}>Нет данных по топливу в выбранном скоупе</Td></tr>}
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
          л/100 — только для транспорта с пробегом ≥ 100 км (у не-ТС и моточасной техники «—»).
          *Норма — из Omnicomm, <b>неутверждённая</b>: вердикт перерасхода не выводится до согласования норм.
          Посменный разрез требует графика смен заказчика.
        </div>
      </Panel>
    </div>
  );
}
