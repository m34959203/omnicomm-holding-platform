// Гибкий рабочий стол — схема layout (Фаза 1, localStorage).
// Размещение виджетов — порядком в массиве + CSS Grid auto-flow (без x,y-движка
// коллизий): каждый виджет занимает span w×h, сетка раскладывает по порядку.
// x/y оставлены опционально в схеме на будущее (Фаза 2).

export type WidgetType =
  | "kpiTile" | "economics" | "recommendations" | "matrix"
  | "violations" | "fuel" | "speedTrend" | "sensorHealth"
  | "maintenance" | "parkDonut" | "dzoBars";

export interface WidgetInstance {
  id: string;
  type: WidgetType;
  w: number;            // ширина в колонках (1..12)
  h: number;            // высота в строках (span)
  x?: number;
  y?: number;
  settings?: Record<string, unknown>;
}

export interface DashboardLayout {
  schemaVersion: number;
  id: string;
  name: string;
  widgets: WidgetInstance[];
  columns: 12;
  builtin?: boolean;
  updatedAt: number;
}

export const SCHEMA_VERSION = 1;
