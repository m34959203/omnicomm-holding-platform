"use client";
// Движок сетки рабочего стола на CSS Grid (без тяжёлых либ). Режимы view/edit:
// drag за заголовок (reorder), угловой resize со снэпом к сетке, удаление с undo.
// Мобайл <768px → 1 колонка, редактирование выключено.

import { useEffect, useRef, useState } from "react";
import { C, FONT } from "@/lib/atlas";
import { DashboardLayout, WidgetInstance } from "./types";
import { WIDGETS, WidgetData } from "./registry";

const ROW = 132;     // высота строки сетки, px
const GAP = 12;

export default function DashboardGrid({ layout, mode, data, onChange }: {
  layout: DashboardLayout; mode: "view" | "edit"; data: WidgetData;
  onChange: (widgets: WidgetInstance[]) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [mobile, setMobile] = useState(false);
  const [dragId, setDragId] = useState<string | null>(null);
  const [cfgId, setCfgId] = useState<string | null>(null);
  const [undo, setUndo] = useState<{ w: WidgetInstance; i: number } | null>(null);
  const undoTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    const mq = window.matchMedia("(max-width: 767px)");
    const on = () => setMobile(mq.matches); on();
    mq.addEventListener("change", on); return () => mq.removeEventListener("change", on);
  }, []);

  const edit = mode === "edit" && !mobile;
  const widgets = layout.widgets;

  const move = (from: string, toId: string) => {
    if (from === toId) return;
    const arr = [...widgets];
    const fi = arr.findIndex((w) => w.id === from), ti = arr.findIndex((w) => w.id === toId);
    if (fi < 0 || ti < 0) return;
    const [m] = arr.splice(fi, 1); arr.splice(ti, 0, m); onChange(arr);
  };

  const setSettings = (id: string, patch: Record<string, unknown>) =>
    onChange(widgets.map((w) => w.id === id ? { ...w, settings: { ...(w.settings || {}), ...patch } } : w));
  const dzoName = (org?: string) => org ? (data.dzoList.find((d) => d.org_id === org)?.name ?? org) : null;

  const remove = (id: string) => {
    const i = widgets.findIndex((w) => w.id === id); if (i < 0) return;
    setUndo({ w: widgets[i], i });
    onChange(widgets.filter((w) => w.id !== id));
    if (undoTimer.current) clearTimeout(undoTimer.current);
    undoTimer.current = setTimeout(() => setUndo(null), 5000);
  };
  const doUndo = () => {
    if (!undo) return;
    const arr = [...widgets]; arr.splice(Math.min(undo.i, arr.length), 0, undo.w);
    onChange(arr); setUndo(null);
  };

  // resize: pointer-drag углового хэндла, снэп к колонкам/строкам
  const startResize = (e: React.PointerEvent, inst: WidgetInstance) => {
    e.preventDefault(); e.stopPropagation();
    const cont = ref.current; if (!cont) return;
    const cellW = (cont.clientWidth - GAP * 11) / 12;
    const sx = e.clientX, sy = e.clientY, sw = inst.w, sh = inst.h;
    const meta = WIDGETS[inst.type];
    const minW = meta.minSize?.w ?? 2, minH = meta.minSize?.h ?? 1;
    const onMove = (ev: PointerEvent) => {
      const dw = Math.round((ev.clientX - sx) / (cellW + GAP));
      const dh = Math.round((ev.clientY - sy) / (ROW + GAP));
      const w = Math.max(minW, Math.min(12, sw + dw));
      const h = Math.max(minH, Math.min(8, sh + dh));
      if (w !== inst.w || h !== inst.h) {
        onChange(widgets.map((x) => x.id === inst.id ? { ...x, w, h } : x));
      }
    };
    const onUp = () => { window.removeEventListener("pointermove", onMove); window.removeEventListener("pointerup", onUp); };
    window.addEventListener("pointermove", onMove); window.addEventListener("pointerup", onUp);
  };

  if (!widgets.length) return null;

  return (
    <>
      <div ref={ref} style={{
        display: "grid", gridTemplateColumns: mobile ? "1fr" : "repeat(12, 1fr)",
        gridAutoRows: `minmax(${ROW}px, auto)`, gridAutoFlow: "dense", gap: GAP,
      }}>
        {widgets.map((inst) => {
          const meta = WIDGETS[inst.type]; if (!meta) return null;
          const Comp = meta.component;
          return (
            <div key={inst.id}
              onDragOver={edit && dragId ? (e) => e.preventDefault() : undefined}
              onDrop={edit && dragId ? () => { move(dragId, inst.id); setDragId(null); } : undefined}
              style={{
                gridColumn: mobile ? "1 / -1" : `span ${Math.min(12, inst.w)}`,
                gridRow: mobile ? "auto" : `span ${inst.h}`,
                position: "relative", background: C.panel, border: `1px solid ${C.line}`,
                borderRadius: 6, boxShadow: "0 1px 2px rgba(20,30,50,.05)", minWidth: 0,
                display: "flex", flexDirection: "column", overflow: "hidden",
                outline: edit && dragId === inst.id ? `2px dashed ${C.blue}` : "none",
              }}>
              {/* заголовок */}
              <div draggable={edit}
                onDragStart={edit ? () => setDragId(inst.id) : undefined}
                onDragEnd={() => setDragId(null)}
                style={{
                  display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8,
                  padding: "8px 11px", borderBottom: `1px solid ${C.headRule}`,
                  cursor: edit ? "grab" : "default", flexShrink: 0,
                }}>
                <span style={{ fontSize: 12, fontWeight: 600, color: C.ink2, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", minWidth: 0 }}>
                  {edit && <span style={{ color: C.faint2, marginRight: 6 }}>⠿</span>}{meta.title}
                  {inst.settings?.scope ? <span title="Закреплён за ДЗО" style={{ marginLeft: 6, fontSize: 10, color: C.blue, background: "#eef4fd", borderRadius: 8, padding: "1px 6px", fontWeight: 600 }}>🔒 {dzoName(inst.settings.scope as string)}</span> : null}
                </span>
                {edit && (
                  <span style={{ display: "flex", gap: 4, flexShrink: 0 }}>
                    {(meta.metricOptions || meta.scopable) && (
                      <button onClick={() => setCfgId(cfgId === inst.id ? null : inst.id)} title="Настройки"
                        style={{ border: "none", background: "transparent", color: cfgId === inst.id ? C.blue : C.faint, cursor: "pointer", fontSize: 13, lineHeight: 1, padding: 2 }}>⚙</button>
                    )}
                    <button onClick={() => remove(inst.id)} title="Удалить"
                      style={{ border: "none", background: "transparent", color: C.faint, cursor: "pointer", fontSize: 14, lineHeight: 1, padding: 2 }}>×</button>
                  </span>
                )}
              </div>
              {/* настройки виджета */}
              {edit && cfgId === inst.id && (
                <div style={{ position: "absolute", top: 38, right: 6, zIndex: 30, background: "#fff", border: `1px solid ${C.line}`, borderRadius: 8, boxShadow: "0 8px 24px rgba(20,30,50,.14)", padding: 10, width: 220, fontFamily: FONT }}>
                  {meta.metricOptions && (
                    <label style={{ display: "block", fontSize: 10.5, color: C.muted2, fontWeight: 600, marginBottom: 10 }}>Метрика
                      <select value={(inst.settings?.metric as string) || meta.metricOptions[0].value}
                        onChange={(e) => setSettings(inst.id, { metric: e.target.value })}
                        style={{ width: "100%", marginTop: 4, padding: "5px 6px", fontSize: 12, border: `1px solid ${C.railLine}`, borderRadius: 5 }}>
                        {meta.metricOptions.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                      </select>
                    </label>
                  )}
                  {meta.scopable && (
                    <label style={{ display: "block", fontSize: 10.5, color: C.muted2, fontWeight: 600 }}>Скоуп (ДЗО)
                      <select value={(inst.settings?.scope as string) || ""}
                        onChange={(e) => setSettings(inst.id, { scope: e.target.value || undefined })}
                        style={{ width: "100%", marginTop: 4, padding: "5px 6px", fontSize: 12, border: `1px solid ${C.railLine}`, borderRadius: 5 }}>
                        <option value="">Весь скоуп (как слайсер)</option>
                        {data.dzoList.map((d) => <option key={d.org_id} value={d.org_id}>{d.name}</option>)}
                      </select>
                    </label>
                  )}
                </div>
              )}
              {/* тело */}
              <div style={{ flex: 1, minHeight: 0, overflow: "auto", padding: 12 }}>
                <Comp id={inst.id} data={data} settings={inst.settings} />
              </div>
              {/* угловой resize */}
              {edit && (
                <div onPointerDown={(e) => startResize(e, inst)} title="Изменить размер"
                  style={{ position: "absolute", right: 2, bottom: 2, width: 16, height: 16, cursor: "nwse-resize",
                    borderRight: `2px solid ${C.faint2}`, borderBottom: `2px solid ${C.faint2}`, borderBottomRightRadius: 5 }} />
              )}
            </div>
          );
        })}
      </div>

      {undo && (
        <div style={{ position: "fixed", left: "50%", bottom: 24, transform: "translateX(-50%)", zIndex: 60,
          background: C.ink, color: "#fff", borderRadius: 8, padding: "10px 14px", fontSize: 12.5, fontFamily: FONT,
          display: "flex", alignItems: "center", gap: 14, boxShadow: "0 6px 24px rgba(0,0,0,.25)" }}>
          Виджет удалён
          <button onClick={doUndo} style={{ border: "none", background: "transparent", color: "#7db4ff", fontWeight: 700, cursor: "pointer", fontSize: 12.5 }}>Отменить</button>
        </div>
      )}
    </>
  );
}
