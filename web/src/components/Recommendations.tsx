"use client";

import { useMemo, useState } from "react";
import { Recommendation } from "@/lib/api";
import { num } from "@/lib/format";
import { useLang } from "@/lib/i18n";
import { ColumnChart, RankBars } from "./charts";

const SEV_TONE: Record<string, string> = {
  грубое: "text-danger",
  значительное: "text-warn",
};

const DEFAULT_SHOWN = 12;

export default function Recommendations({
  recs, topOrgs = [],
}: {
  recs: Recommendation[];
  topOrgs?: { label: string; value: number }[];
}) {
  const { t } = useLang();
  const [open, setOpen] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);

  const gross = recs.filter((r) => r.worst_severity === "грубое").length;
  const episodes = recs.reduce((s, r) => s + r.episodes, 0);

  // Гистограмма по тяжести превышения (макс. excess на ТС).
  const hist = useMemo(() => {
    const b = { mid: 0, high: 0, gross: 0 };
    for (const r of recs) {
      const e = r.max_excess || 0;
      if (e >= 40) b.gross++;
      else if (e >= 20) b.high++;
      else if (e >= 6) b.mid++;
    }
    return [
      { label: "6–20", value: b.mid, tone: "warn" as const },
      { label: "20–40", value: b.high, tone: "danger" as const },
      { label: "40+", value: b.gross, tone: "danger" as const },
    ];
  }, [recs]);

  if (!recs.length)
    return (
      <p className="text-sm text-ink-faint">
        Устойчивых превышений по геозонам СТ КАП за период не выявлено.
      </p>
    );

  const shown = showAll ? recs.slice(0, 60) : recs.slice(0, DEFAULT_SHOWN);

  return (
    <div>
      {/* сводка */}
      <div className="mb-8 grid grid-cols-3 gap-x-10">
        <div className="border-t border-line py-3">
          <span className="eyebrow">ТС с превышениями</span>
          <p className="data text-2xl text-ink">{num(recs.length)}</p>
        </div>
        <div className="border-t border-line py-3">
          <span className="eyebrow">Эпизодов</span>
          <p className="data text-2xl text-ink">{num(episodes)}</p>
        </div>
        <div className="border-t border-line py-3">
          <span className="eyebrow">Грубых ≥6 км/ч</span>
          <p className="data text-2xl text-danger">{num(gross)}</p>
        </div>
      </div>

      {/* графики: распределение по тяжести + топ-ДЗО по эпизодам */}
      <div className="mb-10 grid gap-10 lg:grid-cols-2">
        <div>
          <span className="eyebrow">Распределение по превышению, км/ч · ТС</span>
          <div className="mt-3"><ColumnChart bars={hist} /></div>
        </div>
        {topOrgs.length > 0 && (
          <div>
            <span className="eyebrow">Топ организаций по эпизодам</span>
            <div className="mt-4"><RankBars items={topOrgs} tone="warn" /></div>
          </div>
        )}
      </div>

      {/* список нарушителей — свёрнут по умолчанию */}
      <span className="eyebrow">Нарушители</span>
      <ul className="mt-2">
        {shown.map((r) => {
          const isOpen = open === r.terminal_id;
          return (
            <li key={r.terminal_id} className="border-t border-line">
              <button
                onClick={() => setOpen(isOpen ? null : r.terminal_id)}
                className="grid w-full grid-cols-[1fr_auto_auto] items-center gap-4 py-3 text-left
                           transition-colors hover:bg-surface/40"
              >
                <span className="truncate text-sm text-ink">{r.name || r.terminal_id}</span>
                <span className={`data text-xs ${SEV_TONE[r.worst_severity] ?? "text-ink-dim"}`}>
                  {r.worst_severity}
                </span>
                <span className="data w-24 text-right text-xs text-ink-faint">
                  +{num(r.max_excess, 0)} км/ч · {r.episodes}
                </span>
              </button>
              {isOpen && (
                <div className="grid grid-cols-1 gap-3 pb-4 pl-1 sm:grid-cols-[1fr_auto]">
                  <p className="data text-xs leading-relaxed text-ink-dim">{r.text}</p>
                  <div className="flex shrink-0 flex-wrap gap-x-6 gap-y-1 text-xs">
                    <span className="data text-ink-faint">
                      общ. дороги <span className="text-ink">{r.public_episodes}</span>
                    </span>
                    <span className="data text-ink-faint">
                      техдороги <span className="text-ink">{r.tech_episodes}</span>
                    </span>
                    {r.worst_article && (
                      <span className="data text-warn">{r.worst_article} КоАП</span>
                    )}
                  </div>
                </div>
              )}
            </li>
          );
        })}
      </ul>
      {recs.length > DEFAULT_SHOWN && (
        <button
          onClick={() => setShowAll((v) => !v)}
          className="eyebrow mt-4 text-accent transition-colors hover:text-ink"
        >
          {showAll
            ? "← свернуть"
            : `${t("common.show")} ещё ${num(Math.min(60, recs.length) - DEFAULT_SHOWN)} →`}
        </button>
      )}
    </div>
  );
}
