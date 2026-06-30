// Системные шаблоны рабочих столов (Фаза 1 — клиентские пресеты).
// Применение = копия с новыми id (structuredClone + reid), не связь с шаблоном.
import { DashboardLayout, SCHEMA_VERSION, WidgetInstance, WidgetType } from "./types";

export interface Template {
  id: string; name: string; role: string; description: string; builtin?: true;
  widgets: { type: WidgetType; w: number; h: number; settings?: Record<string, unknown> }[];
}

export const TEMPLATES: Template[] = [
  {
    id: "exec-overview", name: "Руководитель — обзор", role: "Руководство",
    description: "Деньги, превышения, связь и матрица по ДЗО на одном экране.",
    widgets: [
      { type: "kpiTile", w: 3, h: 1, settings: { metric: "potential" } },
      { type: "kpiTile", w: 3, h: 1, settings: { metric: "coi" } },
      { type: "kpiTile", w: 3, h: 1, settings: { metric: "episodes" } },
      { type: "kpiTile", w: 3, h: 1, settings: { metric: "sensor" } },
      { type: "dzoBars", w: 5, h: 2, settings: { metric: "potential" } },
      { type: "economics", w: 4, h: 2 },
      { type: "parkDonut", w: 3, h: 2 },
      { type: "matrix", w: 12, h: 3 },
    ],
  },
  {
    id: "money", name: "Экономика и топливо", role: "Финансы",
    description: "Потенциал/COI, структура потерь, ₸/км и перерасход топлива.",
    widgets: [
      { type: "kpiTile", w: 3, h: 1, settings: { metric: "potential" } },
      { type: "kpiTile", w: 3, h: 1, settings: { metric: "fuelCost" } },
      { type: "kpiTile", w: 3, h: 1, settings: { metric: "cpkm" } },
      { type: "kpiTile", w: 3, h: 1, settings: { metric: "coi" } },
      { type: "economics", w: 5, h: 2 },
      { type: "dzoBars", w: 4, h: 2, settings: { metric: "cpkm" } },
      { type: "dzoBars", w: 3, h: 2, settings: { metric: "l100" } },
      { type: "fuel", w: 12, h: 4 },
    ],
  },
  {
    id: "speed", name: "Скоростной режим", role: "БДД / СТ КАП",
    description: "Превышения по ДЗО, повторяемость по месяцам, детальная таблица.",
    widgets: [
      { type: "kpiTile", w: 3, h: 1, settings: { metric: "episodes" } },
      { type: "dzoBars", w: 5, h: 2, settings: { metric: "episodes" } },
      { type: "recommendations", w: 4, h: 2 },
      { type: "speedTrend", w: 12, h: 4 },
      { type: "violations", w: 12, h: 4 },
    ],
  },
  {
    id: "quality", name: "Качество данных", role: "Телематика",
    description: "Связь терминалов и состояние датчиков по ДЗО.",
    widgets: [
      { type: "kpiTile", w: 3, h: 1, settings: { metric: "sensor" } },
      { type: "sensorHealth", w: 5, h: 2 },
      { type: "dzoBars", w: 4, h: 2, settings: { metric: "episodes" } },
      { type: "matrix", w: 12, h: 3 },
    ],
  },
  {
    id: "maintenance", name: "Контроль ТО", role: "Сервис / ремонт",
    description: "Наработка, просроченные ТО по ДЗО.",
    widgets: [
      { type: "kpiTile", w: 3, h: 1, settings: { metric: "sensor" } },
      { type: "maintenance", w: 6, h: 3 },
      { type: "dzoBars", w: 6, h: 3, settings: { metric: "overdue" } },
    ],
  },
  {
    id: "fuel-ops", name: "Топливо — операционка", role: "ГСМ",
    description: "Расход/норма/перерасход по ТС и ₸/км по ДЗО.",
    widgets: [
      { type: "kpiTile", w: 3, h: 1, settings: { metric: "fuelCost" } },
      { type: "dzoBars", w: 5, h: 2, settings: { metric: "cpkm" } },
      { type: "dzoBars", w: 4, h: 2, settings: { metric: "l100" } },
      { type: "fuel", w: 12, h: 5 },
    ],
  },
  {
    id: "dzo-card", name: "Карточка ДЗО", role: "ДЗО",
    description: "Компактный набор под одно ДЗО: деньги, скорость, ТО, связь.",
    widgets: [
      { type: "kpiTile", w: 3, h: 1, settings: { metric: "potential" } },
      { type: "kpiTile", w: 3, h: 1, settings: { metric: "episodes" } },
      { type: "kpiTile", w: 3, h: 1, settings: { metric: "sensor" } },
      { type: "kpiTile", w: 3, h: 1, settings: { metric: "veh" } },
      { type: "economics", w: 4, h: 2 },
      { type: "sensorHealth", w: 4, h: 2 },
      { type: "maintenance", w: 4, h: 2 },
      { type: "recommendations", w: 6, h: 3 },
      { type: "violations", w: 6, h: 3 },
    ],
  },
];

let _seq = 0;
const uid = () => `w${Date.now().toString(36)}${(_seq++).toString(36)}`;

export function instantiate(tpl: Template): DashboardLayout {
  const widgets: WidgetInstance[] = tpl.widgets.map((w) => ({
    id: uid(), type: w.type, w: w.w, h: w.h,
    settings: w.settings ? structuredClone(w.settings) : undefined,
  }));
  return { schemaVersion: SCHEMA_VERSION, id: uid(), name: tpl.name, widgets, columns: 12, updatedAt: Date.now() };
}

export function emptyLayout(name = "Мой стол"): DashboardLayout {
  return { schemaVersion: SCHEMA_VERSION, id: uid(), name, widgets: [], columns: 12, updatedAt: Date.now() };
}
