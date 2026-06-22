"use client";

import { useMemo, useState } from "react";
import { OrgNode } from "@/lib/api";
import { num } from "@/lib/format";
import { useLang } from "@/lib/i18n";

// Простой индикатор «здоровья» узла по его роллап-KPI (где смотреть).
function nodeTone(n: OrgNode): "danger" | "warn" | "neutral" {
  const k = n.kpi;
  if ((k?.max_speed_kmh ?? 0) > 100) return "danger";
  if ((k?.idle_hours_share ?? 0) > 0.4) return "warn";
  return "neutral";
}
const DOT = {
  danger: "bg-danger", warn: "bg-warn", neutral: "bg-line-strong",
} as const;

interface Row { n: OrgNode; depth: number; path: string }

function flatten(nodes: OrgNode[], depth = 0, prefix = "", acc: Row[] = []): Row[] {
  for (const n of nodes) {
    acc.push({ n, depth, path: prefix });
    if (n.children?.length) flatten(n.children, depth + 1, `${prefix}${n.name} › `, acc);
  }
  return acc;
}

// Видимые строки при свёрнутом дереве: показываем узел, если все его предки раскрыты.
function visibleRows(
  nodes: OrgNode[], expanded: Set<string>, depth = 0, acc: Row[] = [],
): Row[] {
  for (const n of nodes) {
    acc.push({ n, depth, path: "" });
    if (n.children?.length && expanded.has(n.org_id)) {
      visibleRows(n.children, expanded, depth + 1, acc);
    }
  }
  return acc;
}

export default function ScopeRail({
  orgs, scope, onScope,
}: {
  orgs: OrgNode[];
  scope: string;
  onScope: (orgId: string) => void;
}) {
  const { t } = useLang();
  const root = orgs[0];
  // По умолчанию раскрыт только корень (видны ДЗО, но не под-ДЗО/подрядчики).
  const [expanded, setExpanded] = useState<Set<string>>(
    () => new Set(root ? [root.org_id] : []),
  );
  const [q, setQ] = useState("");

  const all = useMemo(() => flatten(orgs), [orgs]);
  const query = q.trim().toLowerCase();
  const rows = useMemo(() => {
    if (query) return all.filter((r) => r.n.name.toLowerCase().includes(query));
    return visibleRows(orgs, expanded);
  }, [all, orgs, expanded, query]);

  if (!root) return null;

  const toggle = (id: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });

  return (
    <div className="flex flex-col gap-3">
      <span className="eyebrow">{t("scope.title")} · {all.length} {t("scope.units")}</span>
      <input
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder={t("scope.search")}
        className="border border-line-strong bg-transparent px-3 py-2 text-sm text-ink
                   placeholder:text-ink-faint focus:border-accent focus:outline-none"
      />

      {/* Весь холдинг — сброс scope */}
      <button
        onClick={() => onScope("")}
        className={`flex items-baseline justify-between gap-2 border-t border-line py-2 text-left
                    transition-colors ${scope === "" ? "text-accent" : "text-ink hover:text-ink-dim"}`}
      >
        <span className="text-sm">{t("scope.holding")}</span>
        <span className="data text-[0.65rem] text-ink-faint">
          {num(root.vehicle_count)} {t("scope.vehicles")}
        </span>
      </button>

      <ul className="max-h-[60vh] overflow-y-auto lg:max-h-[68vh]">
        {rows.map(({ n, depth, path }) => {
          const active = n.org_id === scope;
          const hasKids = !!n.children?.length;
          const open = expanded.has(n.org_id);
          return (
            <li key={n.org_id}>
              <div
                className={`group grid grid-cols-[1rem_1fr_auto] items-center gap-1.5 border-t border-line
                            py-2 ${active ? "text-accent" : "text-ink"}`}
                style={{ paddingLeft: query ? 0 : depth * 12 }}
              >
                {hasKids && !query ? (
                  <button
                    onClick={() => toggle(n.org_id)}
                    className="text-[0.7rem] text-ink-faint transition-colors hover:text-ink"
                    aria-label="развернуть"
                  >
                    {open ? "▾" : "▸"}
                  </button>
                ) : (
                  <span className={`h-1 w-1 justify-self-center rounded-full ${DOT[nodeTone(n)]}`} />
                )}
                <button
                  onClick={() => onScope(n.org_id)}
                  className="truncate text-left text-sm transition-colors hover:text-ink-dim"
                  title={path ? `${path}${n.name}` : n.name}
                >
                  {n.name}
                </button>
                <span className="data text-[0.65rem] text-ink-faint">{num(n.vehicle_count)}</span>
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
