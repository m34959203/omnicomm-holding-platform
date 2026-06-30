"use client";
// Вкладка «Рабочий стол» (Фаза 2): серверное хранение столов и шаблонов,
// несколько столов, row-level на сервере. Виджеты — из Atlas-данных.
import { useEffect, useRef, useState } from "react";
import {
  ServerLayout, ServerTemplate, applyTemplate, createLayout, deleteLayout,
  getDefaultLayout, getLayouts, getTemplates, saveAsTemplate, updateLayout,
} from "@/lib/api";
import { C, FONT } from "@/lib/atlas";
import DashboardGrid from "@/widgets/DashboardGrid";
import { WIDGET_LIST, WidgetData } from "@/widgets/registry";
import { DashboardLayout, WidgetInstance, WidgetType } from "@/widgets/types";

let seq = 0;
const uid = () => `w${Date.now().toString(36)}${(seq++).toString(36)}`;
const btn = (active = false): React.CSSProperties => ({
  padding: "6px 12px", borderRadius: 6, border: `1px solid ${active ? C.blue : C.line2}`,
  background: active ? "#eef4fd" : "#fff", color: active ? C.blue : C.muted,
  fontSize: 12, fontWeight: 600, cursor: "pointer", fontFamily: FONT,
});
const widgetsOf = (l: ServerLayout): WidgetInstance[] =>
  ((l.layout?.widgets as WidgetInstance[]) || []).map((w) => w.id ? w : { ...w, id: uid() });

export default function Desktop({ data, canTemplate }: { data: WidgetData; canTemplate?: boolean }) {
  const [layouts, setLayouts] = useState<ServerLayout[]>([]);
  const [cur, setCur] = useState<ServerLayout | null>(null);
  const [widgets, setWidgets] = useState<WidgetInstance[]>([]);
  const [tpls, setTpls] = useState<ServerTemplate[]>([]);
  const [mode, setMode] = useState<"view" | "edit">("view");
  const [gallery, setGallery] = useState(false);
  const [addOpen, setAddOpen] = useState(false);
  const [menu, setMenu] = useState(false);
  const saveT = useRef<ReturnType<typeof setTimeout> | null>(null);

  const refreshList = () => getLayouts().then((r) => setLayouts(r.layouts)).catch(() => {});

  useEffect(() => {
    (async () => {
      try {
        const [d, t] = await Promise.all([getDefaultLayout(), getTemplates()]);
        setTpls(t.templates);
        if (d.layout) { setCur(d.layout); setWidgets(widgetsOf(d.layout)); }
        else setGallery(true);
        refreshList();
      } catch { setGallery(true); }
    })();
  }, []);

  const open = (l: ServerLayout) => { setCur(l); setWidgets(widgetsOf(l)); setMenu(false); };

  const save = (next: WidgetInstance[]) => {
    setWidgets(next);
    if (!cur) return;
    if (saveT.current) clearTimeout(saveT.current);
    saveT.current = setTimeout(() => {
      updateLayout(cur.id, cur.name, { schemaVersion: 1, name: cur.name, widgets: next, columns: 12 })
        .then((r) => setCur(r.layout)).catch(() => {});
    }, 500);
  };

  const applyTpl = async (t: ServerTemplate) => {
    try {
      const r = await applyTemplate(t.id);
      setCur(r.layout); setWidgets(widgetsOf(r.layout)); setGallery(false); setMode("edit"); refreshList();
    } catch { /* no-op */ }
  };
  const newBlank = async () => {
    try {
      const r = await createLayout("Мой стол", { schemaVersion: 1, name: "Мой стол", widgets: [], columns: 12 });
      setCur(r.layout); setWidgets([]); setGallery(false); setMode("edit"); refreshList();
    } catch { /* no-op */ }
  };
  const addWidget = (type: WidgetType) => {
    const meta = WIDGET_LIST.find((w) => w.type === type)!;
    save([...widgets, { id: uid(), type, w: meta.defaultSize.w, h: meta.defaultSize.h }]);
    setAddOpen(false);
  };
  const removeCurrent = async () => {
    if (!cur) return;
    await deleteLayout(cur.id).catch(() => {});
    setCur(null); setWidgets([]); await refreshList(); setGallery(true);
  };

  const gridLayout: DashboardLayout | null = cur
    ? { schemaVersion: 1, id: cur.id, name: cur.name, widgets, columns: 12, updatedAt: cur.updated_at }
    : null;

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, marginBottom: 12, flexWrap: "wrap" }}>
        <div style={{ position: "relative" }}>
          <button style={{ ...btn(), fontSize: 14, fontWeight: 700, color: C.ink }} onClick={() => setMenu((v) => !v)}>
            {cur?.name ?? "Рабочий стол"} ▾
          </button>
          {menu && (
            <div style={{ position: "absolute", top: 36, left: 0, zIndex: 40, background: "#fff", border: `1px solid ${C.line}`, borderRadius: 8, boxShadow: "0 8px 24px rgba(20,30,50,.12)", padding: 6, width: 240, maxHeight: 320, overflow: "auto" }}>
              {layouts.length ? layouts.map((l) => (
                <div key={l.id} onClick={() => open(l)} style={{ padding: "7px 9px", fontSize: 12, borderRadius: 5, cursor: "pointer", color: l.id === cur?.id ? C.blue : C.ink, fontWeight: l.id === cur?.id ? 700 : 400 }}>{l.name}</div>
              )) : <div style={{ padding: 8, fontSize: 11.5, color: C.faint }}>Нет столов</div>}
              <div onClick={newBlank} style={{ padding: "7px 9px", fontSize: 12, color: C.blue, borderTop: `1px solid ${C.headRule}`, cursor: "pointer", fontWeight: 600 }}>+ Новый стол</div>
            </div>
          )}
        </div>
        <div style={{ display: "flex", gap: 6, position: "relative" }}>
          <button style={btn(mode === "view")} onClick={() => setMode("view")}>Просмотр</button>
          <button style={btn(mode === "edit")} onClick={() => setMode("edit")}>Изменить</button>
          {mode === "edit" && cur && <button style={btn()} onClick={() => setAddOpen((v) => !v)}>+ Виджет</button>}
          {mode === "edit" && cur && <button style={btn()} onClick={removeCurrent}>Удалить стол</button>}
          {mode === "edit" && cur && canTemplate && (
            <button style={btn()} onClick={async () => {
              const name = window.prompt("Название шаблона ДЗО:", cur.name);
              if (name) { await saveAsTemplate(cur.id, name).catch(() => {}); getTemplates().then((r) => setTpls(r.templates)).catch(() => {}); }
            }}>Сохранить как шаблон</button>
          )}
          <button style={btn()} onClick={() => setGallery(true)}>Шаблоны</button>
          {addOpen && (
            <div style={{ position: "absolute", top: 38, right: 0, zIndex: 40, background: "#fff", border: `1px solid ${C.line}`, borderRadius: 8, boxShadow: "0 8px 24px rgba(20,30,50,.12)", padding: 6, width: 230, maxHeight: 320, overflow: "auto" }}>
              {WIDGET_LIST.map((w) => (
                <div key={w.type} onClick={() => addWidget(w.type)} style={{ padding: "7px 9px", fontSize: 12, color: C.ink, borderRadius: 5, cursor: "pointer" }}
                  onMouseEnter={(e) => (e.currentTarget.style.background = C.bg)} onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}>{w.title}</div>
              ))}
            </div>
          )}
        </div>
      </div>

      {gridLayout && widgets.length
        ? <DashboardGrid layout={gridLayout} mode={mode} data={data} onChange={save} />
        : <Empty onPick={() => setGallery(true)} />}

      {gallery && <Gallery tpls={tpls} onApply={applyTpl} onBlank={newBlank} onClose={() => setGallery(false)} hasLayout={!!widgets.length} />}
    </div>
  );
}

function Empty({ onPick }: { onPick: () => void }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 12, padding: "60px 16px", color: C.muted }}>
      <div style={{ fontSize: 16, fontWeight: 700, color: C.ink }}>Начните с шаблона</div>
      <div style={{ fontSize: 13 }}>Соберите рабочий стол из виджетов или возьмите готовый шаблон роли.</div>
      <button style={{ ...btn(true), padding: "9px 16px", fontSize: 13 }} onClick={onPick}>Выбрать шаблон</button>
    </div>
  );
}

function Gallery({ tpls, onApply, onBlank, onClose, hasLayout }: {
  tpls: ServerTemplate[]; onApply: (t: ServerTemplate) => void; onBlank: () => void; onClose: () => void; hasLayout: boolean;
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
          {tpls.map((t) => (
            <div key={t.id} style={{ background: "#fff", border: `1px solid ${C.line}`, borderRadius: 10, padding: 14, display: "flex", flexDirection: "column", gap: 8 }}>
              {t.role && <span style={{ alignSelf: "flex-start", fontSize: 10, fontWeight: 700, color: C.blue, background: "#eef4fd", borderRadius: 10, padding: "2px 8px" }}>{t.role}</span>}
              <div style={{ fontSize: 13.5, fontWeight: 700, color: C.ink }}>{t.name}</div>
              <div style={{ fontSize: 11.5, color: C.muted, lineHeight: 1.45, flex: 1 }}>{t.description}</div>
              <div style={{ fontSize: 10.5, color: C.faint2 }}>{((t.layout?.widgets as unknown[]) || []).length} виджетов{t.is_system ? " · системный" : ""}</div>
              <button onClick={() => onApply(t)} style={{ ...btn(true), marginTop: 2 }}>{hasLayout ? "Создать стол" : "Использовать"}</button>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
