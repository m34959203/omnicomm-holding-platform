"use client";
import { useEffect, useRef, useState } from "react";
import { slideUrl } from "@/lib/api";
import { C, FONT } from "@/lib/atlas";

// Выгрузка «галочкой» (kb-15): выбираешь разделы → один лист-презентация (PPTX).
const SECTIONS: [string, string][] = [
  ["fleet", "Парк (KPI)"],
  ["economics", "Деньги"],
  ["speed", "Скоростной режим"],
  ["fuel", "Топливо"],
  ["quality", "Качество данных"],
  ["maint", "Контроль ТО"],
  ["tyres", "Шины"],
];

export default function SlideExport({ periodKey }: { periodKey?: string }) {
  const [open, setOpen] = useState(false);
  const [sel, setSel] = useState<Set<string>>(new Set(SECTIONS.map(([k]) => k)));
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  const toggle = (k: string) =>
    setSel((s) => { const n = new Set(s); if (n.has(k)) n.delete(k); else n.add(k); return n; });

  return (
    <div ref={ref} style={{ position: "relative" }}>
      <button onClick={() => setOpen((o) => !o)}
        style={{ display: "flex", alignItems: "center", gap: 6, padding: "6px 11px",
          background: C.blue, border: "none", borderRadius: 6, color: "#fff",
          font: `600 11.5px/1 ${FONT}`, cursor: "pointer" }}>
        ↓ Слайд
      </button>
      {open && (
        <div style={{ position: "absolute", top: "calc(100% + 6px)", right: 0, zIndex: 40,
          width: 210, background: "#fff", border: `1px solid ${C.line2}`, borderRadius: 8,
          boxShadow: "0 8px 24px rgba(20,30,50,.14)", padding: 10 }}>
          <div style={{ fontSize: 10.5, fontWeight: 700, color: C.muted, marginBottom: 6 }}>
            РАЗДЕЛЫ НА ОДНОМ ЛИСТЕ
          </div>
          {SECTIONS.map(([k, label]) => (
            <label key={k} style={{ display: "flex", alignItems: "center", gap: 7,
              padding: "4px 2px", fontSize: 12, color: C.ink, cursor: "pointer" }}>
              <input type="checkbox" checked={sel.has(k)} onChange={() => toggle(k)} />
              {label}
            </label>
          ))}
          <a
            href={sel.size ? slideUrl(Array.from(sel), periodKey) : undefined}
            onClick={() => setOpen(false)}
            style={{ display: "block", textAlign: "center", marginTop: 8, padding: "7px 0",
              background: sel.size ? C.blue : C.line2, borderRadius: 6, color: "#fff",
              fontSize: 11.5, fontWeight: 600, textDecoration: "none",
              pointerEvents: sel.size ? "auto" : "none" }}>
            Скачать презентацию
          </a>
        </div>
      )}
    </div>
  );
}
