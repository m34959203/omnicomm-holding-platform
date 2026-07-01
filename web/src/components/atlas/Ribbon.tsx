"use client";
import { useEffect, useState } from "react";
import { C, FONT } from "@/lib/atlas";

export interface Period { key: string; name: string; active: boolean; disabled: boolean; onClick: () => void }

export default function Ribbon({ title, subtitle, snapshot, periods, excelHref, onSync, syncing, refreshing, onRange, periodKey, user, scope, onLogout, accountsHref }: {
  title: string; subtitle: string; snapshot: string;
  periods: Period[]; excelHref: string; onSync: () => void; syncing: boolean;
  refreshing?: boolean; onRange?: (key: string) => void; periodKey?: string;
  user?: string; scope?: string | null; onLogout?: () => void; accountsHref?: string;
}) {
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  // Автоподстановка дат календаря из активного диапазона (быстрый фильтр/снимок).
  useEffect(() => {
    const m = /^(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})$/.exec(periodKey || "");
    if (m) { setFrom(m[1]); setTo(m[2]); }
  }, [periodKey]);
  const today = new Date().toISOString().slice(0, 10);
  const showRange = () => { if (from && to && from <= to && onRange) onRange(`${from}_${to}`); };
  const dateInput: React.CSSProperties = {
    border: `1px solid ${C.line2}`, borderRadius: 5, background: "#fff",
    color: C.ink, font: `600 10.5px/1 ${FONT}`, padding: "4px 5px", width: 116,
  };
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
          <span style={{ width: 6, height: 6, borderRadius: "50%", background: (syncing || refreshing) ? C.amber : C.green }} />
          {refreshing ? "сборка…" : `снимок ${snapshot}`}
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
        {onRange && (
          <div style={{ display: "flex", alignItems: "center", gap: 4 }} title="Произвольный диапазон — собирается из архива мгновенно">
            <input type="date" value={from} max={to || today} onChange={(e) => setFrom(e.target.value)} style={dateInput} />
            <span style={{ color: C.faint, fontSize: 11 }}>—</span>
            <input type="date" value={to} min={from || undefined} max={today} onChange={(e) => setTo(e.target.value)} style={dateInput} />
            <button onClick={showRange} disabled={!from || !to || from > to}
              style={{ padding: "5px 9px", border: `1px solid ${C.blue}`, borderRadius: 5, background: "transparent",
                color: C.blue, font: `600 11px/1 ${FONT}`, cursor: (!from || !to) ? "not-allowed" : "pointer", opacity: (!from || !to) ? 0.4 : 1 }}>
              показать
            </button>
          </div>
        )}
        <button onClick={onSync} disabled={syncing}
          style={{ display: "flex", alignItems: "center", gap: 6, padding: "6px 11px", background: "#eef4fd", border: `1px solid #cfe0f7`, borderRadius: 6, color: C.blue, fontSize: 11.5, fontWeight: 600, cursor: syncing ? "wait" : "pointer", fontFamily: FONT }}>
          {syncing ? "синхр…" : "↻ обновить"}
        </button>
        <a href={excelHref} style={{ textDecoration: "none", display: "flex", alignItems: "center", gap: 6, padding: "6px 11px", background: C.excel, borderRadius: 6, color: "#fff", fontSize: 11.5, fontWeight: 600 }}>↓ Excel</a>
        {accountsHref && (
          <a href={accountsHref} title="Excel со всеми учётками ДЗО (админ/КАП)"
            style={{ textDecoration: "none", display: "flex", alignItems: "center", gap: 6, padding: "6px 11px", background: "#fff", border: `1px solid ${C.line2}`, borderRadius: 6, color: C.muted, fontSize: 11.5, fontWeight: 600 }}>↓ Учётки</a>
        )}
        {user && (
          <>
            <span style={{ width: 1, height: 22, background: C.line2 }} />
            <span style={{ fontSize: 11, color: C.muted, whiteSpace: "nowrap", maxWidth: 180, overflow: "hidden", textOverflow: "ellipsis" }} title={scope ? `${user} · ${scope}` : user}>
              <b style={{ color: C.ink }}>{user}</b>{scope ? ` · ${scope}` : " · КАП"}
            </span>
            <button onClick={onLogout}
              style={{ padding: "6px 11px", background: "#fff", border: `1px solid ${C.line2}`, borderRadius: 6, color: C.muted, fontSize: 11.5, fontWeight: 600, cursor: "pointer", fontFamily: FONT }}>Выйти</button>
          </>
        )}
      </div>
    </div>
  );
}
