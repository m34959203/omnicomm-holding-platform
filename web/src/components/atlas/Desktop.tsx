"use client";
// Вкладка «Рабочий стол»: настраиваемая виджет-сетка (Фаза 1, localStorage).
import { useEffect, useState } from "react";
import { C, FONT } from "@/lib/atlas";
import DashboardGrid from "@/widgets/DashboardGrid";
import { WIDGET_LIST, WidgetData } from "@/widgets/registry";
import { TEMPLATES, Template, instantiate, emptyLayout } from "@/widgets/templates";
import { loadLayout, saveLayout } from "@/widgets/storage";
import { DashboardLayout, WidgetInstance, WidgetType } from "@/widgets/types";

const TAB = "main";
let seq = 0;
const uid = () => `w${Date.now().toString(36)}${(seq++).toString(36)}`;

const btn = (active = false): React.CSSProperties => ({
  padding: "6px 12px", borderRadius: 6, border: `1px solid ${active ? C.blue : C.line2}`,
  background: active ? "#eef4fd" : "#fff", color: active ? C.blue : C.muted,
  fontSize: 12, fontWeight: 600, cursor: "pointer", fontFamily: FONT,
});

export default function Desktop({ data }: { data: WidgetData }) {
  const [layout, setLayout] = useState<DashboardLayout | null>(null);
  const [mode, setMode] = useState<"view" | "edit">("view");
  const [gallery, setGallery] = useState(false);
  const [addOpen, setAddOpen] = useState(false);

  useEffect(() => {
    const l = loadLayout(TAB);
    if (l && l.widgets.length) setLayout(l); else setGallery(true);
  }, []);

  const persist = (l: DashboardLayout) => { setLayout(l); saveLayout(TAB, l); };
  const onChange = (widgets: WidgetInstance[]) => { if (layout) persist({ ...layout, widgets }); };
  const applyTpl = (t: Template) => { persist(instantiate(t)); setGallery(false); setMode("edit"); };
  const addWidget = (type: WidgetType) => {
    if (!layout) return;
    const meta = WIDGET_LIST.find((w) => w.type === type)!;
    persist({ ...layout, widgets: [...layout.widgets, { id: uid(), type, w: meta.defaultSize.w, h: meta.defaultSize.h }] });
    setAddOpen(false);
  };

  return (
    <div>
      {/* тулбар стола */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, marginBottom: 12, flexWrap: "wrap" }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: C.ink }}>{layout?.name ?? "Рабочий стол"}</div>
        <div style={{ display: "flex", gap: 6, position: "relative" }}>
          <button style={btn(mode === "view")} onClick={() => setMode("view")}>Просмотр</button>
          <button style={btn(mode === "edit")} onClick={() => setMode("edit")}>Изменить</button>
          {mode === "edit" && layout && (
            <button style={btn()} onClick={() => setAddOpen((v) => !v)}>+ Виджет</button>
          )}
          <button style={btn()} onClick={() => setGallery(true)}>Шаблоны</button>
          {addOpen && (
            <div style={{ position: "absolute", top: 38, right: 0, zIndex: 40, background: "#fff", border: `1px solid ${C.line}`, borderRadius: 8, boxShadow: "0 8px 24px rgba(20,30,50,.12)", padding: 6, width: 230, maxHeight: 320, overflow: "auto" }}>
              {WIDGET_LIST.map((w) => (
                <div key={w.type} onClick={() => addWidget(w.type)}
                  style={{ padding: "7px 9px", fontSize: 12, color: C.ink, borderRadius: 5, cursor: "pointer" }}
                  onMouseEnter={(e) => (e.currentTarget.style.background = C.bg)}
                  onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}>{w.title}</div>
              ))}
            </div>
          )}
        </div>
      </div>

      {layout && layout.widgets.length
        ? <DashboardGrid layout={layout} mode={mode} data={data} onChange={onChange} />
        : <Empty onPick={() => setGallery(true)} />}

      {gallery && <Gallery onApply={applyTpl} onBlank={() => { persist(emptyLayout()); setGallery(false); setMode("edit"); }} onClose={() => setGallery(false)} hasLayout={!!layout?.widgets.length} />}
    </div>
  );
}

function Empty({ onPick }: { onPick: () => void }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 12, padding: "60px 16px", color: C.muted }}>
      <div style={{ fontSize: 16, fontWeight: 700, color: C.ink }}>Начните с шаблона</div>
      <div style={{ fontSize: 13 }}>Соберите свой рабочий стол из виджетов или возьмите готовый шаблон роли.</div>
      <button style={{ ...btn(true), padding: "9px 16px", fontSize: 13 }} onClick={onPick}>Выбрать шаблон</button>
    </div>
  );
}

function Gallery({ onApply, onBlank, onClose, hasLayout }: {
  onApply: (t: Template) => void; onBlank: () => void; onClose: () => void; hasLayout: boolean;
}) {
  return (
    <div onClick={onClose} style={{ position: "fixed", inset: 0, zIndex: 50, background: "rgba(20,30,50,.35)", display: "flex", alignItems: "center", justifyContent: "center", padding: 20 }}>
      <div onClick={(e) => e.stopPropagation()} style={{ background: C.bg, borderRadius: 12, padding: 20, width: "min(900px, 96vw)", maxHeight: "88vh", overflow: "auto", fontFamily: FONT }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
          <div style={{ fontSize: 16, fontWeight: 700, color: C.ink }}>Шаблоны рабочего стола</div>
          <button onClick={onClose} style={{ border: "none", background: "transparent", color: C.muted, fontSize: 13, cursor: "pointer", fontWeight: 600 }}>закрыть ✕</button>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(250px,1fr))", gap: 12 }}>
          <div onClick={onBlank} style={{ border: `1.5px dashed ${C.railLine}`, borderRadius: 10, padding: 16, cursor: "pointer", display: "flex", flexDirection: "column", justifyContent: "center", alignItems: "center", color: C.muted, minHeight: 120 }}>
            <div style={{ fontSize: 26, color: C.blue }}>+</div><div style={{ fontSize: 13, fontWeight: 600 }}>Пустой стол</div>
          </div>
          {TEMPLATES.map((t) => (
            <div key={t.id} style={{ background: "#fff", border: `1px solid ${C.line}`, borderRadius: 10, padding: 14, display: "flex", flexDirection: "column", gap: 8 }}>
              <span style={{ alignSelf: "flex-start", fontSize: 10, fontWeight: 700, color: C.blue, background: "#eef4fd", borderRadius: 10, padding: "2px 8px" }}>{t.role}</span>
              <div style={{ fontSize: 13.5, fontWeight: 700, color: C.ink }}>{t.name}</div>
              <div style={{ fontSize: 11.5, color: C.muted, lineHeight: 1.45, flex: 1 }}>{t.description}</div>
              <div style={{ fontSize: 10.5, color: C.faint2 }}>{t.widgets.length} виджетов</div>
              <button onClick={() => onApply(t)} style={{ ...btn(true), marginTop: 2 }}>{hasLayout ? "Заменить столом" : "Использовать"}</button>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
