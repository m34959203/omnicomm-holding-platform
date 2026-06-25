// Скоупинг данных под выбранную организацию (поддерево dim_org) — клиентский слой.
// Ключевой факт: OrgNode.kpi уже сроллапен по поддереву (KPI скоупятся «бесплатно»),
// а списки скорости/датчиков/ТО скоупятся через vehicle_org (terminal_id → org_id).
// Economics (buckets/coi/worst) клиентски НЕ скоупится — честный backend-долг.

import {
  Economics,
  Maintenance,
  OrgNode,
  Recommendation,
  SensorHealth,
} from "./api";

export const TABS = ["money", "speed", "map", "quality", "maint",
  "visits", "fleet", "violations", "fuel"] as const;
export type TabKey = (typeof TABS)[number];

export interface Signal {
  id: string;
  severity: "danger" | "warn";
  kind: "maint" | "speed" | "sensor" | "cost";
  label: string;
  value: string;
  tab: TabKey;
  weight: number;
  entityId?: string; // terminal_id/имя — для drill к конкретной проблеме
}

// Плоский индекс дерева организаций по org_id (строится один раз).
export function indexOrgs(orgs: OrgNode[]): Map<string, OrgNode> {
  const byId = new Map<string, OrgNode>();
  const walk = (n: OrgNode) => {
    byId.set(n.org_id, n);
    n.children?.forEach(walk);
  };
  orgs.forEach(walk);
  return byId;
}

// Множество org_id всего поддерева выбранного узла.
export function subtreeOrgIds(byId: Map<string, OrgNode>, root: string): Set<string> {
  const ids = new Set<string>();
  const start = byId.get(root);
  if (!start) return ids;
  const stack: OrgNode[] = [start];
  while (stack.length) {
    const n = stack.pop()!;
    ids.add(n.org_id);
    n.children?.forEach((c) => stack.push(c));
  }
  return ids;
}

type InScope = (terminalId: string) => boolean;

export function makeInScope(
  scopeIds: Set<string> | null,
  vehicleOrg: Record<string, string>,
): InScope {
  return (tid: string) => !scopeIds || scopeIds.has(vehicleOrg[tid]);
}

export function scopeRecs(recs: Recommendation[], inScope: InScope): Recommendation[] {
  return recs.filter((r) => inScope(r.terminal_id));
}

// Фильтр терминалов + ПЕРЕСБОРКА counts (иначе плитки покажут холдинговые числа).
export function scopeSensor(sh: SensorHealth | null, inScope: InScope): SensorHealth | null {
  if (!sh) return null;
  const terminals = sh.terminals.filter((t) => inScope(t.terminal_id));
  const missing = sh.missing_capabilities.filter((m) => inScope(m.terminal_id));
  const counts: Record<string, number> = { online: 0, stale: 0, offline: 0, unknown: 0 };
  for (const t of terminals) counts[t.status] = (counts[t.status] ?? 0) + 1;
  return { ...sh, terminals, missing_capabilities: missing, counts };
}

export function scopeMaint(mt: Maintenance | null, inScope: InScope): Maintenance | null {
  if (!mt) return null;
  const items = mt.items.filter((i) => inScope(i.terminal_id));
  const counts: Record<string, number> = {};
  for (const i of items) counts[i.status] = (counts[i.status] ?? 0) + 1;
  return { ...mt, items, counts };
}

// Лента «что требует внимания»: топ-N сигналов, ранжированных по severity-весу.
export function buildSignals(
  recs: Recommendation[],
  sensor: SensorHealth | null,
  maint: Maintenance | null,
  economics: Economics | null,
  scoped: boolean,
  limit = 6,
): Signal[] {
  const out: Signal[] = [];

  // Ранжирование по УРОВНЯМ: danger (3000+) всегда выше warn (<1000),
  // внутри уровня — по величине. Без этого ₸-потери забивали грубые превышения.
  for (const i of maint?.items ?? []) {
    if (i.status === "просрочено") {
      out.push({
        id: `maint-${i.terminal_id}`, severity: "danger", kind: "maint",
        label: i.name || i.terminal_id, value: "ТО просрочено", tab: "maint", weight: 3000,
        entityId: i.terminal_id,
      });
    }
  }
  for (const r of recs) {
    if (r.worst_severity === "грубое") {
      out.push({
        id: `speed-${r.terminal_id}`, severity: "danger", kind: "speed",
        label: r.name || r.terminal_id, value: `+${Math.round(r.max_excess)} км/ч · ${r.episodes}`,
        tab: "speed", weight: 2000 + r.max_excess, entityId: r.terminal_id,
      });
    }
  }
  const offline = (sensor?.terminals ?? []).filter((t) => t.status === "offline");
  if (offline.length) {
    out.push({
      id: "sensor-offline", severity: "warn", kind: "sensor",
      label: `${offline.length} терминалов офлайн`, value: "нет данных", tab: "quality", weight: 500,
    });
  }
  // worst_vehicles по ₸ — только на уровне холдинга (клиентски не скоупится).
  if (!scoped) {
    (economics?.worst_vehicles ?? []).slice(0, 3).forEach(([name], idx) => {
      out.push({
        id: `cost-${name}`, severity: "warn", kind: "cost",
        label: name, value: "крупные потери", tab: "money", weight: 400 - idx,
        entityId: name,
      });
    });
  }

  return out.sort((a, b) => b.weight - a.weight).slice(0, limit);
}
