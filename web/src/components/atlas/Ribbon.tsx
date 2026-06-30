"use client";
import { C, FONT } from "@/lib/atlas";

export interface Period { key: string; name: string; active: boolean; disabled: boolean; onClick: () => void }

export default function Ribbon({ title, subtitle, snapshot, periods, excelHref, onSync, syncing }: {
  title: string; subtitle: string; snapshot: string;
  periods: Period[]; excelHref: string; onSync: () => void; syncing: boolean;
}) {
  return (
    <div style={{
      flexShrink: 0, display: "flex", alignItems: "center", justifyContent: "space-between",
      gap: 14, padding: "0 16px", height: 48, background: C.panel, borderBottom: `1px solid ${C.line2}`,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 11, minWidth: 0 }}>
        <div style={{ width: 10, height: 10, borderRadius: 2, background: C.blue, transform: "rotate(45deg)", flexShrink: 0 }} />
        <span style={{ fontSize: 14, fontWeight: 700, letterSpacing: "-0.01em", whiteSpace: "nowrap" }}>{title}</span>
        <span style={{ fontSize: 11, color: C.faint, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{subtitle}</span>
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexShrink: 0 }}>
        <span style={{ fontSize: 11, color: C.muted, display: "flex", alignItems: "center", gap: 6, whiteSpace: "nowrap" }}>
          <span style={{ width: 6, height: 6, borderRadius: "50%", background: syncing ? C.amber : C.green }} />
          снимок {snapshot}
        </span>
        <div style={{ display: "flex", gap: 2, background: C.bg, borderRadius: 6, padding: 2 }}>
          {periods.map((p) => (
            <button key={p.key} onClick={p.onClick} disabled={p.disabled} title={p.disabled ? "нет снимка такого периода" : undefined}
              style={{
                padding: "5px 10px", border: "none", borderRadius: 5, cursor: p.disabled ? "not-allowed" : "pointer",
                font: `600 11px/1 ${FONT}`, opacity: p.disabled ? 0.4 : 1,
                ...(p.active ? { background: C.blue, color: "#fff" } : { background: "transparent", color: C.muted }),
              }}>{p.name}</button>
          ))}
        </div>
        <button onClick={onSync} disabled={syncing}
          style={{ display: "flex", alignItems: "center", gap: 6, padding: "6px 11px", background: "#eef4fd", border: `1px solid #cfe0f7`, borderRadius: 6, color: C.blue, fontSize: 11.5, fontWeight: 600, cursor: syncing ? "wait" : "pointer", fontFamily: FONT }}>
          {syncing ? "синхр…" : "↻ обновить"}
        </button>
        <a href={excelHref} style={{ textDecoration: "none", display: "flex", alignItems: "center", gap: 6, padding: "6px 11px", background: C.excel, borderRadius: 6, color: "#fff", fontSize: 11.5, fontWeight: 600 }}>↓ Excel</a>
      </div>
    </div>
  );
}
