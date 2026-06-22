"use client";

import { useState } from "react";
import { Recommendation } from "@/lib/api";
import { num } from "@/lib/format";

const SEV_TONE: Record<string, string> = {
  грубое: "text-danger",
  значительное: "text-warn",
};

export default function Recommendations({ recs }: { recs: Recommendation[] }) {
  const [open, setOpen] = useState<string | null>(null);
  const gross = recs.filter((r) => r.worst_severity === "грубое").length;
  const episodes = recs.reduce((s, r) => s + r.episodes, 0);

  if (!recs.length)
    return (
      <p className="text-sm text-ink-faint">
        Устойчивых превышений по геозонам СТ КАП за период не выявлено.
      </p>
    );

  return (
    <div>
      <div className="mb-6 grid grid-cols-3 gap-x-10">
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

      <ul>
        {recs.slice(0, 40).map((r) => {
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
      {recs.length > 40 && (
        <p className="data mt-4 text-xs text-ink-faint">
          показаны 40 из {recs.length} — отсортированы по тяжести
        </p>
      )}
    </div>
  );
}
