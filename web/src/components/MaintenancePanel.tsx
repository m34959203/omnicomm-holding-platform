"use client";

import { Maintenance } from "@/lib/api";
import { num } from "@/lib/format";
import { useLang } from "@/lib/i18n";

const TONE: Record<string, string> = {
  "просрочено": "text-danger",
  "ожидается": "text-warn",
  "ok": "text-accent",
};

export default function MaintenancePanel({ mt }: { mt: Maintenance }) {
  const { t } = useLang();
  const STAT: Record<string, string> = {
    "просрочено": t("mt.overdue"), "ожидается": t("mt.due"), "ok": t("mt.ok"),
  };
  // показываем срочные (просрочено + ожидается); «ok» сворачиваем в счётчик
  const urgent = mt.items.filter((i) => i.status !== "ok");

  return (
    <div>
      <div className="mb-6 grid grid-cols-3 gap-x-8">
        {(["просрочено", "ожидается", "ok"] as const).map((k) => (
          <div key={k} className="border-t border-line py-3">
            <span className="eyebrow">{STAT[k]}</span>
            <p className={`data text-2xl ${TONE[k]}`}>{num(mt.counts[k] ?? 0)}</p>
          </div>
        ))}
      </div>

      {urgent.length > 0 ? (
        <ul className="border-t border-line-strong pt-2">
          {urgent.slice(0, 40).map((i) => (
            <li
              key={i.terminal_id}
              className="grid grid-cols-[1fr_auto_auto] items-center gap-4 border-t border-line py-2"
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
          ))}
        </ul>
      ) : (
        <p className="text-sm text-ink-faint">{t("mt.ok")}</p>
      )}
      <p className="data mt-4 text-xs text-ink-faint">{mt.note}</p>
    </div>
  );
}
