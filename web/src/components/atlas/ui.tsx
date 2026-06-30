"use client";
// Atlas BI — переиспользуемые примитивы (панель, KPI-карта, бары, donut, gauge).
// Стиль 1:1 с дизайном: белые панели, тонкие линии, табличные цифры.

import { CSSProperties, ReactNode } from "react";
import { C, FONT } from "@/lib/atlas";

export const panelStyle: CSSProperties = {
  background: C.panel, border: `1px solid ${C.line}`, borderRadius: 6,
  boxShadow: "0 1px 2px rgba(20,30,50,.05)",
};

export function Panel({ title, right, span, children, pad = true }: {
  title?: string; right?: ReactNode; span: number; children: ReactNode; pad?: boolean;
}) {
  return (
    <div style={{ ...panelStyle, gridColumn: `span ${span}`, minWidth: 0 }}>
      {title && (
        <div style={{
          padding: "9px 13px", fontSize: 12, fontWeight: 600, color: C.ink2,
          borderBottom: `1px solid ${C.headRule}`, display: "flex",
          justifyContent: "space-between", alignItems: "center", gap: 8,
        }}>
          <span>{title}</span>
          {right && <span style={{ fontWeight: 400, color: C.faint, fontSize: 10.5 }}>{right}</span>}
        </div>
      )}
      <div style={pad ? { padding: 13 } : undefined}>{children}</div>
    </div>
  );
}

// KPI-карта с большим числом и (опц.) спарклайном.
export function Kpi({ label, value, color = C.ink, sub, sparkPts, span = 2, onClick }: {
  label: string; value: string; color?: string; sub?: string; sparkPts?: string; span?: number; onClick?: () => void;
}) {
  return (
    <div onClick={onClick} title={onClick ? "перейти к разделу" : undefined}
      style={{ ...panelStyle, gridColumn: `span ${span}`, padding: "11px 13px", minWidth: 0, cursor: onClick ? "pointer" : "default" }}>
      <div style={{
        fontSize: 10.5, color: C.muted2, fontWeight: 600, textTransform: "uppercase",
        letterSpacing: ".03em", marginBottom: 7, whiteSpace: "nowrap",
        overflow: "hidden", textOverflow: "ellipsis",
      }}>{label}</div>
      <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", gap: 6 }}>
        <div className="num" style={{ fontSize: 21, fontWeight: 700, color, lineHeight: 1 }}>{value}</div>
        {sparkPts && (
          <svg viewBox="0 0 70 24" preserveAspectRatio="none" style={{ width: 56, height: 24, flexShrink: 0 }}>
            <polyline points={sparkPts} fill="none" stroke={color} strokeWidth={2} />
          </svg>
        )}
      </div>
      {sub && <div style={{ fontSize: 10.5, color: C.faint, marginTop: 5 }}>{sub}</div>}
    </div>
  );
}

// Горизонтальный бар «имя — полоса — значение».
export function BarRow({ name, w, value, color = C.blue, h = 15, onClick }: {
  name: string; w: number; value: string; color?: string; h?: number; onClick?: () => void;
}) {
  return (
    <div onClick={onClick}
      style={{ display: "flex", alignItems: "center", gap: 10, cursor: onClick ? "pointer" : "default" }}>
      <div style={{ width: 96, fontSize: 11.5, color: C.muted, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{name}</div>
      <div style={{ flex: 1, height: h, background: C.track, borderRadius: 2, overflow: "hidden" }}>
        <div style={{ height: "100%", width: `${w}%`, background: color }} />
      </div>
      <div className="num" style={{ width: 56, textAlign: "right", fontSize: 11.5, fontWeight: 600 }}>{value}</div>
    </div>
  );
}

// Стэк-бар (несколько сегментов в одной полосе).
export function StackRow({ name, w, segs, total }: {
  name: string; w: number; segs: { pct: number; color: string }[]; total: string;
}) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
      <div style={{ width: 96, fontSize: 11.5, color: C.muted, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{name}</div>
      <div style={{ flex: 1, height: 15, background: C.track, borderRadius: 2, overflow: "hidden", display: "flex" }}>
        <div style={{ display: "flex", width: `${w}%`, height: "100%" }}>
          {segs.map((s, i) => <div key={i} style={{ width: `${s.pct}%`, background: s.color }} />)}
        </div>
      </div>
      <div className="num" style={{ width: 40, textAlign: "right", fontSize: 11.5, fontWeight: 600 }}>{total}</div>
    </div>
  );
}

// Кольцевая диаграмма (conic-gradient) + легенда.
export function Donut({ slices, size = 96, hole = 21 }: {
  slices: { label: string; pct: number; color: string }[]; size?: number; hole?: number;
}) {
  let acc = 0;
  const grad = slices.map((s) => { const a = acc; acc += s.pct; return `${s.color} ${a}% ${acc}%`; }).join(",");
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
      <div style={{ position: "relative", width: size, height: size, flexShrink: 0, borderRadius: "50%", background: `conic-gradient(${grad})` }}>
        <div style={{ position: "absolute", inset: hole, borderRadius: "50%", background: C.panel }} />
      </div>
      <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 8 }}>
        {slices.map((l, i) => (
          <div key={i} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 11.5 }}>
            <span style={{ width: 9, height: 9, borderRadius: 2, background: l.color }} />
            <span style={{ flex: 1, color: C.muted, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{l.label}</span>
            <b className="num">{Math.round(l.pct)}%</b>
          </div>
        ))}
      </div>
    </div>
  );
}

// Радиальный gauge (один процент).
export function Gauge({ pct, size = 104, label, sub }: { pct: number; size?: number; label?: string; sub?: string }) {
  const p = Math.round(pct * 100);
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 9 }}>
      <div style={{ position: "relative", width: size, height: size, borderRadius: "50%", background: `conic-gradient(${C.green} 0 ${p}%, #e8ebf0 ${p}% 100%)` }}>
        <div style={{ position: "absolute", inset: size * 0.16, borderRadius: "50%", background: C.panel, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center" }}>
          <div className="num" style={{ fontSize: size * 0.22, fontWeight: 700 }}>{p}%</div>
          {label && <div style={{ fontSize: 10, color: C.faint }}>{label}</div>}
        </div>
      </div>
      {sub && <div style={{ fontSize: 11, color: C.muted, textAlign: "center" }}>{sub}</div>}
    </div>
  );
}

// Легенда: подписи цветов под графиком (что какой цвет значит).
export function Legend({ items }: { items: { color: string; label: string }[] }) {
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: "5px 14px", marginTop: 10, fontSize: 10.5, color: C.muted }}>
      {items.map((it, i) => (
        <span key={i} style={{ display: "flex", alignItems: "center", gap: 5 }}>
          <span style={{ width: 9, height: 9, borderRadius: 2, background: it.color, flexShrink: 0 }} />{it.label}
        </span>
      ))}
    </div>
  );
}

// Заголовок ячейки/строки таблицы.
export const Th = ({ children, right }: { children: ReactNode; right?: boolean }) => (
  <th style={{ textAlign: right ? "right" : "left", padding: "9px 6px", borderBottom: `1px solid ${C.line}` }}>{children}</th>
);
export const Td = ({ children, right, color, bold }: { children: ReactNode; right?: boolean; color?: string; bold?: boolean }) => (
  <td className={right ? "num" : undefined}
    style={{ textAlign: right ? "right" : "left", padding: "8px 6px", color, fontWeight: bold ? 600 : 400 }}>{children}</td>
);

export function tableWrap(children: ReactNode) {
  return (
    <div style={{ padding: "4px 13px 10px", overflowX: "auto" }}>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12, fontFamily: FONT }}>{children}</table>
    </div>
  );
}
export const theadStyle: CSSProperties = { color: C.muted2, fontSize: 10.5, textTransform: "uppercase", letterSpacing: ".03em" };
export const trRule: CSSProperties = { borderBottom: "1px solid #f0f3f7" };
