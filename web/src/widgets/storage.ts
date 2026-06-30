// Хранение раскладок столов в localStorage (Фаза 1). Фаза 2 — на сервер.
import { DashboardLayout, SCHEMA_VERSION, WidgetInstance } from "./types";
import { WIDGETS } from "./registry";

const KEY = (tab: string) => `dashboard:${tab}`;

type Migration = (raw: Record<string, unknown>) => Record<string, unknown>;
// Карта миграций по версиям (пока пусто — схема v1). Пример: 1: (r)=>{...; return r}.
const MIGRATIONS: Record<number, Migration> = {};

function migrate(raw: Record<string, unknown>): Record<string, unknown> {
  let v = Number(raw.schemaVersion) || 1;
  while (v < SCHEMA_VERSION && MIGRATIONS[v]) {
    raw = MIGRATIONS[v](raw); v += 1;
  }
  raw.schemaVersion = SCHEMA_VERSION;
  return raw;
}

function sanitize(layout: DashboardLayout): DashboardLayout {
  // выкинуть инстансы с неизвестным type (защита от устаревших раскладок)
  const widgets = (layout.widgets || []).filter((w) => w && (w as WidgetInstance).type in WIDGETS);
  return { ...layout, widgets, columns: 12, schemaVersion: SCHEMA_VERSION };
}

export function loadLayout(tab: string): DashboardLayout | null {
  if (typeof window === "undefined") return null;
  try {
    const s = window.localStorage.getItem(KEY(tab));
    if (!s) return null;
    return sanitize(migrate(JSON.parse(s)) as unknown as DashboardLayout);
  } catch { return null; }
}

let timer: ReturnType<typeof setTimeout> | null = null;
export function saveLayout(tab: string, layout: DashboardLayout): void {
  if (typeof window === "undefined") return;
  const data = { ...sanitize(layout), updatedAt: Date.now() };
  if (timer) clearTimeout(timer);
  timer = setTimeout(() => {
    try { window.localStorage.setItem(KEY(tab), JSON.stringify(data)); } catch { /* quota */ }
  }, 400);
}

export function clearLayout(tab: string): void {
  if (typeof window === "undefined") return;
  try { window.localStorage.removeItem(KEY(tab)); } catch { /* no-op */ }
}
