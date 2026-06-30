"use client";
import { SpeedTrend } from "@/lib/api";
import { C, DzoRow, ru } from "@/lib/atlas";
import { Panel } from "./ui";

export type TrendMetric = "episodes" | "perVehicle" | "share";

const MONTHS_RU = ["янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"];
function monthLabel(m: string): string {
  const [y, mm] = m.split("-");
  return `${MONTHS_RU[+mm - 1] ?? mm} ${y.slice(2)}`;
}

// Зелёный→жёлтый→красный по интенсивности t∈[0,1].
function mix(a: number[], b: number[], t: number) {
  return a.map((v, i) => Math.round(v + (b[i] - v) * t));
}
function heatColor(t: number): { bg: string; ink: string } {
  if (t <= 0) return { bg: C.track, ink: C.faint2 };
  const green = [228, 243, 234], amber = [247, 232, 200], red = [212, 69, 59];
  const rgb = t < 0.5 ? mix(green, amber, t / 0.5) : mix(amber, red, (t - 0.5) / 0.5);
  return { bg: `rgb(${rgb.join(",")})`, ink: t > 0.62 ? "#fff" : C.ink };
}

const ROW_CAP = 60;

export default function Trend({ trend, loading, metric, onMetric, dzoRows, vehTopDzo, inScope, onVehicle }: {
  trend: SpeedTrend | null; loading: boolean;
  metric: TrendMetric; onMetric: (m: TrendMetric) => void;
  dzoRows: DzoRow[]; vehTopDzo: Record<string, string>;
  inScope: (vehicleId: string) => boolean;
  onVehicle: (id: string, name?: string) => void;
}) {
  if (loading || !trend) {
    return <div style={{ display: "grid", gridTemplateColumns: "repeat(12,1fr)", gap: 12 }}>
      <Panel span={12} title="Повторяемость превышений · ТС × месяц">
        <div style={{ fontSize: 12, color: C.faint, padding: "20px 0" }}>{loading ? "Считаем матрицу из архива…" : "Нет данных"}</div>
      </Panel>
    </div>;
  }

  const months = trend.months;
  const scopedRows = trend.rows.filter((r) => inScope(r.vehicleId));

  // Строки матрицы + значения ячеек по выбранной метрике.
  type Cell = { raw: number; disp: string };
  interface MRow { id: string; name: string; cells: Record<string, Cell>; total: Cell; clickId?: string }
  let rows: MRow[] = [];
  let totalRow: Record<string, number> = {};
  let unit = "эп.";

  if (metric === "episodes") {
    unit = "эпизодов";
    rows = scopedRows.map((r) => {
      const cells: Record<string, Cell> = {};
      for (const m of months) { const v = r.byMonth[m] ?? 0; cells[m] = { raw: v, disp: v ? ru(v) : "" }; }
      return { id: r.vehicleId, name: r.name, cells, total: { raw: r.all, disp: ru(r.all) }, clickId: r.vehicleId };
    });
    for (const m of months) totalRow[m] = scopedRows.reduce((a, r) => a + (r.byMonth[m] ?? 0), 0);
  } else {
    // агрегируем по ДЗО
    const vehCount = new Map(dzoRows.map((d) => [d.org_id, d.veh]));
    const names = new Map(dzoRows.map((d) => [d.org_id, d.name]));
    const epByOrg = new Map<string, Record<string, number>>();   // org → month → episodes
    const offByOrg = new Map<string, Record<string, Set<string>>>(); // org → month → distinct veh
    for (const r of scopedRows) {
      const org = vehTopDzo[r.vehicleId];
      if (!org) continue;
      const em = epByOrg.get(org) ?? {}; const om = offByOrg.get(org) ?? {};
      for (const m of months) {
        const v = r.byMonth[m] ?? 0;
        em[m] = (em[m] ?? 0) + v;
        if (v > 0) { (om[m] = om[m] ?? new Set()).add(r.vehicleId); }
      }
      epByOrg.set(org, em); offByOrg.set(org, om);
    }
    const orgIds = [...new Set([...epByOrg.keys()])];
    rows = orgIds.map((org) => {
      const veh = vehCount.get(org) || 0;
      const cells: Record<string, Cell> = {};
      let totRaw = 0;
      for (const m of months) {
        if (metric === "perVehicle") {
          const ep = epByOrg.get(org)?.[m] ?? 0;
          const v = veh ? ep / veh : 0; totRaw += ep;
          cells[m] = { raw: v, disp: v ? v.toFixed(1) : "" };
        } else { // share
          const off = offByOrg.get(org)?.[m]?.size ?? 0;
          const v = veh ? off / veh : 0;
          cells[m] = { raw: v, disp: v ? Math.round(v * 100) + "%" : "" };
        }
      }
      const totVal = metric === "perVehicle"
        ? (veh ? totRaw / veh : 0)
        : 0;
      const totDisp = metric === "perVehicle" ? (veh ? (totRaw / veh).toFixed(1) : "—") : `${veh} ТС`;
      return { id: org, name: names.get(org) || org, cells, total: { raw: totVal, disp: totDisp } };
    });
    unit = metric === "perVehicle" ? "эпизодов / ТС" : "доля нарушителей";
    for (const m of months) totalRow[m] = orgIds.reduce((a, o) => a + (epByOrg.get(o)?.[m] ?? 0), 0);
  }

  rows.sort((a, b) => b.total.raw - a.total.raw);
  const shown = rows.slice(0, ROW_CAP);
  const hidden = rows.length - shown.length;

  // максимум ячейки для нормировки заливки
  const maxCell = Math.max(1e-9, ...rows.flatMap((r) => months.map((m) => r.cells[m].raw)));

  const tabs: [TrendMetric, string][] = [["episodes", "Эпизоды"], ["perVehicle", "На ТС"], ["share", "Доля нарушителей"]];
  const colW = 64;

  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(12,1fr)", gap: 12 }}>
      <Panel span={12}
        title={`Повторяемость превышений · ${metric === "episodes" ? "ТС" : "ДЗО"} × месяц`}
        right={`${trend.from} — ${trend.to} · ${ru(trend.episodes)} эпизодов · порог дл.≥${trend.params.minDurationSec}с · превыш. ${trend.params.minExcess}–${trend.params.maxExcess === 999 ? "∞" : trend.params.maxExcess} км/ч`}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 10, marginBottom: 12 }}>
          <div style={{ display: "flex", gap: 2, background: C.bg, borderRadius: 6, padding: 2, width: "fit-content" }}>
            {tabs.map(([k, l]) => (
              <button key={k} onClick={() => onMetric(k)}
                style={{ padding: "5px 12px", border: "none", borderRadius: 5, cursor: "pointer", font: "600 11px/1 'Segoe UI',Roboto,sans-serif",
                  ...(k === metric ? { background: C.blue, color: "#fff" } : { background: "transparent", color: C.muted }) }}>{l}</button>
            ))}
          </div>
          {/* цветовая шкала хитмапа */}
          <div style={{ display: "flex", alignItems: "center", gap: 7, fontSize: 10.5, color: C.muted }}>
            <span>меньше</span>
            <div style={{ width: 120, height: 10, borderRadius: 3, background: "linear-gradient(90deg, rgb(228,243,234), rgb(247,232,200), rgb(212,69,59))" }} />
            <span>больше</span>
            <span style={{ color: C.faint2 }}>· {metric === "episodes" ? "эпизодов/мес" : metric === "perVehicle" ? "эпизодов на ТС" : "доля нарушителей"}</span>
          </div>
        </div>

        <div style={{ overflowX: "auto" }}>
          <div style={{ minWidth: 768 }}>
            {/* header */}
            <div style={{ display: "flex", alignItems: "center", borderBottom: `1px solid ${C.line}`, paddingBottom: 6, marginBottom: 2 }}>
              <div style={{ width: 220, flexShrink: 0, fontSize: 10.5, color: C.muted2, textTransform: "uppercase", letterSpacing: ".03em" }}>
                {metric === "episodes" ? "ТС" : "ДЗО"}
              </div>
              {months.map((m) => (
                <div key={m} style={{ width: colW, flexShrink: 0, textAlign: "center", fontSize: 10.5, color: C.muted2, textTransform: "capitalize" }}>{monthLabel(m)}</div>
              ))}
              <div style={{ width: colW, flexShrink: 0, textAlign: "right", fontSize: 10.5, color: C.muted2, textTransform: "uppercase", fontWeight: 700 }}>Всего</div>
            </div>

            {/* rows */}
            {shown.map((r) => (
              <div key={r.id} onClick={() => r.clickId && onVehicle(r.clickId, r.name)}
                style={{ display: "flex", alignItems: "center", gap: 0, padding: "2px 0", cursor: r.clickId ? "pointer" : "default" }}>
                <div style={{ width: 220, flexShrink: 0, fontSize: 11.5, color: C.ink, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", paddingRight: 8 }}>{r.name}</div>
                {months.map((m) => {
                  const c = r.cells[m]; const hc = heatColor(c.raw / maxCell);
                  return <div key={m} className="num" style={{ width: colW, flexShrink: 0, margin: "0 2px", height: 22, borderRadius: 3, background: hc.bg, color: hc.ink, fontSize: 10.5, fontWeight: 600, display: "flex", alignItems: "center", justifyContent: "center" }}>{c.disp}</div>;
                })}
                <div className="num" style={{ width: colW, flexShrink: 0, textAlign: "right", fontSize: 11.5, fontWeight: 700, paddingLeft: 6 }}>{r.total.disp}</div>
              </div>
            ))}

            {/* ИТОГО */}
            <div style={{ display: "flex", alignItems: "center", borderTop: `2px solid ${C.line}`, marginTop: 4, paddingTop: 6, fontWeight: 700 }}>
              <div style={{ width: 220, flexShrink: 0, fontSize: 11.5 }}>ИТОГО эпизодов</div>
              {months.map((m) => (
                <div key={m} className="num" style={{ width: colW, flexShrink: 0, textAlign: "center", fontSize: 11 }}>{ru(totalRow[m] ?? 0)}</div>
              ))}
              <div className="num" style={{ width: colW, flexShrink: 0, textAlign: "right", fontSize: 11.5, paddingLeft: 6 }}>{ru(trend.episodes)}</div>
            </div>
          </div>
        </div>

        {hidden > 0 && (
          <div style={{ fontSize: 10.5, color: C.faint, marginTop: 8 }}>
            Показаны топ-{ROW_CAP} из {ru(rows.length)} {metric === "episodes" ? "ТС" : "ДЗО"} по сумме · ячейка = {unit} · заливка по интенсивности
          </div>
        )}
      </Panel>
    </div>
  );
}
