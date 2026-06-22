"use client";

import { useEffect, useRef } from "react";
import { Maintenance } from "@/lib/api";
import { num } from "@/lib/format";
import { useLang } from "@/lib/i18n";
import { StackedBar } from "./charts";

const TONE: Record<string, string> = {
  "просрочено": "text-danger",
  "ожидается": "text-warn",
  "ok": "text-accent",
};

export default function MaintenancePanel({
  mt, focusId,
}: {
  mt: Maintenance;
  focusId?: string | null;
}) {
  const { t } = useLang();
  const STAT: Record<string, string> = {
    "просрочено": t("mt.overdue"), "ожидается": t("mt.due"), "ok": t("mt.ok"),
  };
  // показываем срочные (просрочено + ожидается); «ok» сворачиваем в счётчик
  const urgent = mt.items.filter((i) => i.status !== "ok");
  const focusRef = useRef<HTMLLIElement | null>(null);
  useEffect(() => {
    if (!focusId) return;
    const id = setTimeout(() => {
      focusRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
    }, 120);
    return () => clearTimeout(id);
  }, [focusId]);
  const segments = [
    { label: t("mt.overdue"), value: mt.counts["просрочено"] ?? 0, tone: "danger" as const },
    { label: t("mt.due"), value: mt.counts["ожидается"] ?? 0, tone: "warn" as const },
    { label: t("mt.ok"), value: mt.counts["ok"] ?? 0, tone: "neutral" as const },
  ].filter((s) => s.value > 0);

  return (
    <div>
      <div className="mb-6">
        <StackedBar segments={segments} />
      </div>

      {urgent.length > 0 ? (
        <ul className="border-t border-line-strong pt-2">
          {urgent.slice(0, 40).map((i) => {
            const focused = focusId === i.terminal_id;
            return (
            <li
              key={i.terminal_id}
              ref={focused ? focusRef : null}
              className={`grid grid-cols-[1fr_auto_auto] items-center gap-4 border-t border-line py-2 ${
                focused ? "bg-surface ring-1 ring-accent/50" : ""
              }`}
            >
              <span className="truncate text-sm text-ink">{i.name || i.terminal_id}</span>
              <span className={`data text-xs ${TONE[i.status] ?? "text-ink-dim"}`}>
                {STAT[i.status] ?? i.status}
              </span>
              <span className="data w-40 text-right text-xs text-ink-faint">
                {i.mh_left != null
                  ? `${t("mt.left")} ${num(i.mh_left, 0)} ${t("mt.mh")}`
                  : i.km_left != null
                    ? `${t("mt.left")} ${num(i.km_left, 0)} ${t("mt.km")}`
                    : ""}
              </span>
            </li>
            );
          })}
        </ul>
      ) : (
        <p className="text-sm text-ink-faint">{t("mt.ok")}</p>
      )}
      <p className="data mt-4 text-xs text-ink-faint">{mt.note}</p>
    </div>
  );
}
