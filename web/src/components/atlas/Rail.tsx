"use client";
import { SpeedThresholds } from "@/lib/api";
import { C, DzoRow, ru } from "@/lib/atlas";

const label: React.CSSProperties = {
  fontSize: 10.5, fontWeight: 700, color: C.muted2, textTransform: "uppercase",
  letterSpacing: ".05em", marginBottom: 8,
};
const inputStyle: React.CSSProperties = {
  width: "100%", padding: "5px 7px", fontSize: 11.5, color: C.ink, background: "#fff",
  border: `1px solid ${C.railLine}`, borderRadius: 5, fontVariantNumeric: "tabular-nums",
};

export default function Rail({ dzo, selected, onToggle, onClear, summary, geoCount, thresholds, onThreshold, activeCount, totalCount }: {
  dzo: DzoRow[]; selected: Set<string>; onToggle: (id: string) => void;
  onClear: () => void; summary: string; geoCount: number;
  thresholds: SpeedThresholds; onThreshold: (k: keyof SpeedThresholds, v: number) => void;
  activeCount: number; totalCount: number;
}) {
  const numInput = (k: keyof SpeedThresholds, val: number, placeholder: string) => (
    <input type="number" min={0} value={val || ""} placeholder={placeholder} style={inputStyle}
      onChange={(e) => onThreshold(k, Math.max(0, +e.target.value || 0))} />
  );
  return (
    <aside style={{
      width: 204, flexShrink: 0, background: C.railBg, borderRight: `1px solid ${C.railLine}`,
      overflowY: "auto", padding: "13px 11px", display: "flex", flexDirection: "column", gap: 15,
    }}>
      <div>
        <div style={label}>Фильтры</div>
        <div style={{ fontSize: 11, color: C.muted, lineHeight: 1.5, background: C.panel, border: `1px solid ${C.railLine}`, borderRadius: 6, padding: "8px 10px" }}>
          {summary}
          <div style={{ marginTop: 6, paddingTop: 6, borderTop: `1px solid ${C.headRule}`, display: "flex", alignItems: "center", gap: 6 }}>
            <span style={{ width: 6, height: 6, borderRadius: "50%", background: C.green }} />
            Активные за 7 дней: <b className="num" style={{ color: C.ink }}>{ru(activeCount)}</b> / {ru(totalCount)}
          </div>
        </div>
      </div>

      <div>
        <div style={label}>Пороги превышения</div>
        <div style={{ display: "flex", flexDirection: "column", gap: 7 }}>
          <div>
            <div style={{ fontSize: 10.5, color: C.muted, marginBottom: 3 }}>Длительность визита ≥ сек</div>
            {numInput("minDurationSec", thresholds.minDurationSec, "0")}
          </div>
          <div style={{ display: "flex", gap: 6 }}>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 10.5, color: C.muted, marginBottom: 3 }}>Превыш. от</div>
              {numInput("minExcess", thresholds.minExcess, "0")}
            </div>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 10.5, color: C.muted, marginBottom: 3 }}>до км/ч</div>
              {numInput("maxExcess", thresholds.maxExcess >= 999 ? 0 : thresholds.maxExcess, "∞")}
            </div>
          </div>
          <div style={{ fontSize: 10, color: C.faint2, lineHeight: 1.4 }}>Применяется к «Повторяемости» и «Скоростному режиму».</div>
        </div>
      </div>

      <div>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
          <span style={{ ...label, marginBottom: 0 }}>ДЗО</span>
          {selected.size > 0 && (
            <span onClick={onClear} style={{ fontSize: 10, color: C.blue, cursor: "pointer", fontWeight: 600 }}>сбросить</span>
          )}
        </div>
        <div style={{ background: C.panel, border: `1px solid ${C.railLine}`, borderRadius: 6, overflow: "hidden" }}>
          {dzo.map((d, i) => {
            const on = selected.has(d.org_id);
            return (
              <div key={d.org_id} onClick={() => onToggle(d.org_id)}
                style={{ display: "flex", alignItems: "center", gap: 8, padding: "6px 9px", cursor: "pointer", borderTop: i ? "1px solid #f0f3f7" : "none", fontSize: 11.5 }}>
                <span style={{
                  width: 14, height: 14, borderRadius: 3, display: "flex", alignItems: "center", justifyContent: "center",
                  fontSize: 10, fontWeight: 700, flexShrink: 0,
                  ...(on ? { background: C.blue, color: "#fff" } : { background: "#fff", border: "1.5px solid #c4ccd8", color: "transparent" }),
                }}>{on ? "✓" : ""}</span>
                <span style={{ flex: 1, color: "#2b3a4d", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{d.name}</span>
                <span className="num" style={{ color: C.faint2, fontSize: 10 }}>{ru(d.veh)}</span>
              </div>
            );
          })}
        </div>
      </div>

      <div>
        <div style={label}>Геозона</div>
        <div style={{ background: C.panel, border: `1px solid ${C.railLine}`, borderRadius: 6, padding: "7px 10px", fontSize: 11.5, color: C.muted, display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          Все зоны ({ru(geoCount)})
        </div>
      </div>
    </aside>
  );
}
