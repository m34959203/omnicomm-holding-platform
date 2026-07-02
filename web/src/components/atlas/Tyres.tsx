"use client";
import { useState } from "react";
import { Tyres as TyresData, replaceTyres } from "@/lib/api";
import { C, DzoRow, mlnTg, ru } from "@/lib/atlas";
import { Panel, Td, Th, tableWrap, theadStyle, trRule } from "./ui";

const BADGE: Record<string, { bg: string; color: string; label: string }> = {
  "просрочено": { bg: "#fae5e3", color: C.red, label: "просрочено" },
  "пора менять": { bg: "#f7eed8", color: "#bd8413", label: "пора менять" },
  "приближается": { bg: "#eef2da", color: "#7a8a2a", label: "приближается" },
  "ok": { bg: "#e4f3ea", color: C.green, label: "в норме" },
};
const PRIO: Record<string, number> = { "просрочено": 0, "пора менять": 1, "приближается": 2, "ok": 3 };

export default function Tyres({ tyres, onVehicle }: {
  rows: DzoRow[]; tyres: TyresData | null;
  onSelectDzo: (orgId: string) => void; onVehicle: (id: string, name?: string) => void;
}) {
  const [done, setDone] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState<string | null>(null);
  const counts = tyres?.counts ?? {};

  const kpis = [
    { label: "в норме", value: ru(counts.ok ?? 0), color: C.green },
    { label: "приближается", value: ru(counts["приближается"] ?? 0), color: "#7a8a2a" },
    { label: "пора менять", value: ru(counts["пора менять"] ?? 0), color: C.amber },
    { label: "просрочено", value: ru(counts["просрочено"] ?? 0), color: C.red },
  ];

  const items = [...(tyres?.items ?? [])]
    .sort((a, b) => (PRIO[a.status] ?? 9) - (PRIO[b.status] ?? 9) || b.worn_share - a.worn_share)
    .slice(0, 20);

  async function onReplace(id: string) {
    setBusy(id);
    try { await replaceTyres(id); setDone((s) => new Set(s).add(id)); }
    catch { /* остаётся как есть; применится при синке */ }
    finally { setBusy(null); }
  }

  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(12,1fr)", gap: 12, alignContent: "start" }}>
      {kpis.map((k, i) => (
        <div key={i} style={{ background: C.panel, border: `1px solid ${C.line}`, borderRadius: 6, boxShadow: "0 1px 2px rgba(20,30,50,.05)", gridColumn: "span 3", padding: 14, display: "flex", alignItems: "center", gap: 13 }}>
          <span style={{ width: 12, height: 12, borderRadius: "50%", background: k.color }} />
          <div>
            <div className="num" style={{ fontSize: 24, fontWeight: 700 }}>{k.value}</div>
            <div style={{ fontSize: 11.5, color: C.muted2 }}>{k.label}</div>
          </div>
        </div>
      ))}

      <Panel span={12} title="Износ шин в деньгах" right="доля отхоженного ресурса × стоимость комплекта">
        <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
          <div className="num" style={{ fontSize: 30, fontWeight: 700, color: C.ink }}>
            {mlnTg(tyres?.wear_kzt_total ?? 0)}
          </div>
          <div style={{ fontSize: 12, color: C.muted2 }}>накопленный износ комплектов по выборке</div>
        </div>
      </Panel>

      <Panel span={12} title="Комплекты у ресурса (первоочередная замена)" right="клик по строке — карточка ТС">
        {tableWrap(<>
          <thead><tr style={theadStyle}>
            <Th>ТС</Th><Th right>Пробег комплекта</Th><Th right>Ресурс</Th>
            <Th right>Отхожено</Th><Th right>Износ ₸</Th><Th>Статус</Th><Th right>Действие</Th>
          </tr></thead>
          <tbody>
            {items.length ? items.map((it) => {
              const b = BADGE[it.status] ?? { bg: C.track, color: C.muted, label: it.status };
              const replaced = done.has(it.terminal_id);
              const worn = Math.round((it.worn_share ?? 0) * 100);
              return (
                <tr key={it.terminal_id} style={{ ...trRule, opacity: replaced ? 0.5 : 1 }}>
                  <Td bold>
                    <span style={{ cursor: "pointer" }} onClick={() => onVehicle(it.terminal_id, it.name ?? undefined)}>
                      {it.name || it.terminal_id}
                    </span>
                    {it.brand && <span style={{ color: C.faint, fontWeight: 400 }}>{" · " + it.brand}{it.size ? " " + it.size : ""}</span>}
                  </Td>
                  <Td right>{ru(it.km_since)} км</Td>
                  <Td right color={C.muted}>{ru(it.resource_km)} км</Td>
                  <Td right color={worn >= 100 ? C.red : C.muted}>{worn}%</Td>
                  <Td right>{it.wear_kzt ? mlnTg(it.wear_kzt) : "—"}</Td>
                  <Td>
                    <span style={{ fontSize: 11, fontWeight: 600, padding: "2px 8px", borderRadius: 12, background: b.bg, color: b.color }}>
                      {replaced ? "заменены" : b.label}
                    </span>
                  </Td>
                  <Td right>
                    {replaced ? (
                      <span style={{ fontSize: 11, color: C.faint }}>обновится при синке</span>
                    ) : (
                      <button
                        onClick={() => onReplace(it.terminal_id)}
                        disabled={busy === it.terminal_id}
                        style={{ fontSize: 11, fontWeight: 600, padding: "3px 10px", borderRadius: 5, cursor: "pointer", border: `1px solid ${C.line2}`, background: C.track, color: C.ink2 }}>
                        {busy === it.terminal_id ? "…" : "Заменены"}
                      </button>
                    )}
                  </Td>
                </tr>
              );
            }) : <tr><Td color={C.faint}>Нет данных по пробегу шин</Td></tr>}
          </tbody>
        </>)}
      </Panel>

      {tyres?.note && (
        <Panel span={12}>
          <div style={{ fontSize: 11, color: C.faint, lineHeight: 1.5 }}>{tyres.note}</div>
        </Panel>
      )}
    </div>
  );
}
