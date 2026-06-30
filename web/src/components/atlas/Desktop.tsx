"use client";
// Вкладка «Рабочий стол» (Фаза 2): серверное хранение столов и шаблонов,
// несколько столов, row-level на сервере. Виджеты — из Atlas-данных.
import { useEffect, useRef, useState } from "react";
import {
  Schedule, ServerLayout, ServerTemplate, applyTemplate, createLayout, createSchedule,
  deleteLayout, deleteSchedule, getDefaultLayout, getLayouts, getSchedules, getTemplates,
  saveAsTemplate, updateLayout,
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

export default function Desktop({ data, canTemplate, me }: { data: WidgetData; canTemplate?: boolean; me?: string }) {
  const [layouts, setLayouts] = useState<ServerLayout[]>([]);
  const [cur, setCur] = useState<ServerLayout | null>(null);
  const [widgets, setWidgets] = useState<WidgetInstance[]>([]);
  const [tpls, setTpls] = useState<ServerTemplate[]>([]);
  const [mode, setMode] = useState<"view" | "edit">("view");
  const [gallery, setGallery] = useState(false);
  const [addOpen, setAddOpen] = useState(false);
  const [menu, setMenu] = useState(false);
  const [sched, setSched] = useState(false);
  const saveT = useRef<ReturnType<typeof setTimeout> | null>(null);

  const isOwner = cur ? (!me || cur.owner === me) : true;
  const eMode = isOwner ? mode : "view";        // чужой shared-стол — только чтение

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
    if (!cur || !isOwner) return;
    if (saveT.current) clearTimeout(saveT.current);
    saveT.current = setTimeout(() => {
      updateLayout(cur.id, cur.name, { schemaVersion: 1, name: cur.name, widgets: next, columns: 12 }, !!cur.shared)
        .then((r) => setCur(r.layout)).catch(() => {});
    }, 500);
  };
  const toggleShare = async () => {
    if (!cur) return;
    const r = await updateLayout(cur.id, cur.name, { schemaVersion: 1, name: cur.name, widgets, columns: 12 }, !cur.shared).catch(() => null);
    if (r) { setCur(r.layout); refreshList(); }
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
        <div style={{ display: "flex", gap: 6, position: "relative", alignItems: "center" }}>
          {cur && !isOwner && (
            <span style={{ fontSize: 11, color: C.muted, background: C.bg, borderRadius: 6, padding: "5px 9px" }}>🔒 только чтение · {cur.owner}</span>
          )}
          {isOwner && <>
            <button style={btn(mode === "view")} onClick={() => setMode("view")}>Просмотр</button>
            <button style={btn(mode === "edit")} onClick={() => setMode("edit")}>Изменить</button>
            {mode === "edit" && cur && <button style={btn()} onClick={() => setAddOpen((v) => !v)}>+ Виджет</button>}
            {mode === "edit" && cur && <button style={btn(!!cur.shared)} onClick={toggleShare} title="Доступ ДЗО (только чтение)">{cur.shared ? "✓ Общий ДЗО" : "Поделиться"}</button>}
            {mode === "edit" && cur && <button style={btn()} onClick={removeCurrent}>Удалить стол</button>}
            {mode === "edit" && cur && canTemplate && (
              <button style={btn()} onClick={async () => {
                const name = window.prompt("Название шаблона ДЗО:", cur.name);
                if (name) { await saveAsTemplate(cur.id, name).catch(() => {}); getTemplates().then((r) => setTpls(r.templates)).catch(() => {}); }
              }}>Сохранить как шаблон</button>
            )}
          </>}
          <button style={btn()} onClick={() => setSched(true)} title="Excel-отчёт на почту">Расписание</button>
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
        ? <DashboardGrid layout={gridLayout} mode={eMode} data={data} onChange={save} />
        : <Empty onPick={() => setGallery(true)} />}

      {gallery && <Gallery tpls={tpls} onApply={applyTpl} onBlank={newBlank} onClose={() => setGallery(false)} hasLayout={!!widgets.length} />}
      {sched && <ScheduleModal layoutId={cur?.id ?? null} onClose={() => setSched(false)} />}
    </div>
  );
}

function ScheduleModal({ layoutId, onClose }: { layoutId: string | null; onClose: () => void }) {
  const [list, setList] = useState<Schedule[]>([]);
  const [email, setEmail] = useState("");
  const [freq, setFreq] = useState("daily");
  const [hour, setHour] = useState(6);
  const load = () => getSchedules().then((r) => setList(r.schedules)).catch(() => {});
  useEffect(() => { load(); }, []);
  const add = async () => {
    if (!email.includes("@")) return;
    await createSchedule(email.trim(), freq, hour, layoutId ?? undefined).catch(() => {});
    setEmail(""); load();
  };
  const inp: React.CSSProperties = { padding: "6px 8px", fontSize: 12, border: `1px solid ${C.railLine}`, borderRadius: 5, fontFamily: FONT };
  return (
    <div onClick={onClose} style={{ position: "fixed", inset: 0, zIndex: 50, background: "rgba(20,30,50,.35)", display: "flex", alignItems: "center", justifyContent: "center", padding: 20 }}>
      <div onClick={(e) => e.stopPropagation()} style={{ background: "#fff", borderRadius: 12, padding: 20, width: "min(560px,96vw)", fontFamily: FONT }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
          <div style={{ fontSize: 16, fontWeight: 700, color: C.ink }}>Excel-отчёт на почту</div>
          <button onClick={onClose} style={{ border: "none", background: "transparent", color: C.muted, fontSize: 13, cursor: "pointer", fontWeight: 600 }}>закрыть ✕</button>
        </div>
        <div style={{ fontSize: 11.5, color: C.faint, marginBottom: 14 }}>Дашборд по вашему скоупу ДЗО уйдёт письмом по расписанию (UTC).</div>
        <div style={{ display: "flex", gap: 8, marginBottom: 14, flexWrap: "wrap", alignItems: "center" }}>
          <input value={email} onChange={(e) => setEmail(e.target.value)} placeholder="e-mail" style={{ ...inp, flex: 1, minWidth: 160 }} />
          <select value={freq} onChange={(e) => setFreq(e.target.value)} style={inp}><option value="daily">Ежедневно</option><option value="weekly">Еженедельно</option></select>
          <select value={hour} onChange={(e) => setHour(+e.target.value)} style={inp}>{Array.from({ length: 24 }, (_, h) => <option key={h} value={h}>{String(h).padStart(2, "0")}:00</option>)}</select>
          <button style={{ ...btn(true) }} onClick={add}>Добавить</button>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 6, maxHeight: 240, overflow: "auto" }}>
          {list.length ? list.map((s) => (
            <div key={s.id} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", fontSize: 12, color: C.ink, border: `1px solid ${C.line}`, borderRadius: 6, padding: "7px 10px" }}>
              <span>{s.email} · {s.frequency === "weekly" ? "еженед." : "ежедн."} · {String(s.hour).padStart(2, "0")}:00 UTC</span>
              <button onClick={async () => { await deleteSchedule(s.id).catch(() => {}); load(); }} style={{ border: "none", background: "transparent", color: C.red, cursor: "pointer", fontSize: 12, fontWeight: 600 }}>удалить</button>
            </div>
          )) : <div style={{ fontSize: 11.5, color: C.faint }}>Расписаний нет</div>}
        </div>
      </div>
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

const WCOLOR: Record<string, string> = {
  kpiTile: C.blue, economics: C.green, dzoBars: C.teal, parkDonut: C.amber,
  sensorHealth: "#2e9e5b", maintenance: C.amber, recommendations: C.red,
  matrix: C.muted2, violations: C.red, fuel: C.blue, speedTrend: C.amber,
};

// Реалистичный эскиз содержимого виджета (как мини-скрин отчёта Omnicomm Online).
function sketch(type: string, a: string): React.ReactNode {
  const bar = (w: number, c = a) => <div style={{ height: 3, width: `${w}%`, background: c, borderRadius: 2, opacity: 0.8 }} />;
  if (type === "kpiTile")
    return <div style={{ display: "flex", flexDirection: "column", gap: 3, justifyContent: "center", height: "100%" }}>{bar(35, C.faint2)}<div style={{ height: 7, width: "60%", background: a, borderRadius: 2 }} /></div>;
  if (type === "parkDonut" || type === "sensorHealth")
    return <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100%" }}><div style={{ width: 26, height: 26, borderRadius: "50%", border: `5px solid ${a}`, borderRightColor: "#e6e9ee", borderBottomColor: "#e6e9ee" }} /></div>;
  if (type === "speedTrend")
    return <div style={{ display: "grid", gridTemplateColumns: "repeat(6,1fr)", gap: 2, height: "100%", alignContent: "center" }}>{Array.from({ length: 18 }, (_, i) => <div key={i} style={{ height: 5, background: a, borderRadius: 1, opacity: 0.25 + (i % 6) * 0.13 }} />)}</div>;
  if (type === "matrix" || type === "violations" || type === "fuel")
    return <div style={{ display: "flex", flexDirection: "column", gap: 3, paddingTop: 2 }}>{bar(100, C.faint2)}{[0, 1, 2, 3].map((i) => bar(100 - i * 6, a))}</div>;
  // dzoBars / economics / recommendations / maintenance — горизонтальные бары
  return <div style={{ display: "flex", flexDirection: "column", gap: 4, justifyContent: "center", height: "100%" }}>{[90, 70, 55, 40].map((w, i) => <div key={i} style={{ display: "flex", gap: 4, alignItems: "center" }}><div style={{ width: 12, height: 3, background: C.faint2, borderRadius: 2 }} />{bar(w)}</div>)}</div>;
}

// Мини-превью раскладки шаблона (заголовки виджетов + эскизы содержимого).
function TplPreview({ widgets }: { widgets: { type: string; w: number; h: number }[] }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(12,1fr)", gridAutoRows: "26px", gridAutoFlow: "dense", gap: 4, background: "#eef1f5", borderRadius: 6, padding: 8, height: 150, overflow: "hidden" }}>
      {widgets.map((w, i) => {
        const a = WCOLOR[w.type] || C.faint2;
        return (
          <div key={i} style={{ gridColumn: `span ${Math.max(1, Math.min(12, w.w))}`, gridRow: `span ${Math.max(1, Math.min(4, w.h))}`, background: "#fff", border: `1px solid ${C.line}`, borderRadius: 3, overflow: "hidden", display: "flex", flexDirection: "column" }}>
            <div style={{ height: 4, background: a, opacity: 0.9, flexShrink: 0 }} />
            <div style={{ flex: 1, minHeight: 0, padding: "3px 4px", overflow: "hidden" }}>{sketch(w.type, a)}</div>
          </div>
        );
      })}
    </div>
  );
}

function Gallery({ tpls, onApply, onBlank, onClose }: {
  tpls: ServerTemplate[]; onApply: (t: ServerTemplate) => void; onBlank: () => void; onClose: () => void; hasLayout?: boolean;
}) {
  const card: React.CSSProperties = {
    background: "#fff", border: `1px solid ${C.line}`, borderRadius: 8, overflow: "hidden",
    cursor: "pointer", display: "flex", flexDirection: "column", transition: "box-shadow .15s, border-color .15s",
  };
  return (
    <div onClick={onClose} style={{ position: "fixed", inset: 0, zIndex: 50, background: "rgba(20,30,50,.35)", display: "flex", alignItems: "center", justifyContent: "center", padding: 20 }}>
      <div onClick={(e) => e.stopPropagation()} style={{ background: C.bg, borderRadius: 12, padding: 22, width: "min(1080px, 96vw)", maxHeight: "88vh", overflow: "auto", fontFamily: FONT }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
          <div style={{ fontSize: 16, fontWeight: 700, color: C.ink }}>Добавить рабочий стол</div>
          <button onClick={onClose} style={{ border: "none", background: "transparent", color: C.muted, fontSize: 13, cursor: "pointer", fontWeight: 600 }}>закрыть ✕</button>
        </div>
        <div style={{ fontSize: 12.5, fontWeight: 700, color: C.muted2, textTransform: "uppercase", letterSpacing: ".04em", marginBottom: 10 }}>Готовые шаблоны</div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px,1fr))", gap: 16 }}>
          {tpls.map((t) => {
            const ws = ((t.layout?.widgets as { type: string; w: number; h: number }[]) || []);
            return (
              <div key={t.id} onClick={() => onApply(t)} style={card}
                onMouseEnter={(e) => { e.currentTarget.style.boxShadow = "0 4px 16px rgba(20,30,50,.12)"; e.currentTarget.style.borderColor = C.blue; }}
                onMouseLeave={(e) => { e.currentTarget.style.boxShadow = "none"; e.currentTarget.style.borderColor = C.line; }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "9px 12px", borderBottom: `1px solid ${C.headRule}` }}>
                  <span style={{ fontSize: 13, fontWeight: 700, color: C.ink, flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{t.name}</span>
                  {t.role && <span style={{ fontSize: 9.5, fontWeight: 700, color: C.blue, background: "#eef4fd", borderRadius: 10, padding: "2px 7px", whiteSpace: "nowrap" }}>{t.role}</span>}
                </div>
                <div style={{ padding: 10 }}><TplPreview widgets={ws} /></div>
                <div style={{ padding: "0 12px 11px", fontSize: 11, color: C.muted, lineHeight: 1.4 }}>{t.description}</div>
              </div>
            );
          })}
        </div>
        <div style={{ fontSize: 12.5, fontWeight: 700, color: C.muted2, textTransform: "uppercase", letterSpacing: ".04em", margin: "20px 0 10px" }}>С нуля</div>
        <div onClick={onBlank} style={{ ...card, maxWidth: 280, alignItems: "center", justifyContent: "center", minHeight: 120, color: C.muted }}
          onMouseEnter={(e) => { e.currentTarget.style.borderColor = C.blue; }}
          onMouseLeave={(e) => { e.currentTarget.style.borderColor = C.line; }}>
          <div style={{ fontSize: 30, color: C.blue, lineHeight: 1 }}>+</div>
          <div style={{ fontSize: 13, fontWeight: 600, marginTop: 6 }}>Пустой стол</div>
        </div>
      </div>
    </div>
  );
}
