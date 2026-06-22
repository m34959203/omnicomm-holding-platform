"use client";

import { useLang } from "@/lib/i18n";
import { Signal, TabKey } from "@/lib/scope";

// Лента «что требует внимания»: ранжированные сигналы из всех доменов.
// Клик по строке ныряет в соответствующий таб.
export default function AttentionFeed({
  signals, total, onJump,
}: {
  signals: Signal[];
  total: number;
  onJump: (tab: TabKey, entityId?: string) => void;
}) {
  const { t } = useLang();

  return (
    <section>
      <div className="flex items-baseline justify-between gap-3">
        <span className="eyebrow">{t("attn.title")}</span>
        {total > signals.length && (
          <span className="data text-xs text-ink-faint">
            +{total - signals.length} {t("attn.more")}
          </span>
        )}
      </div>
      {signals.length === 0 ? (
        <p className="data mt-3 text-sm text-ink-faint">{t("attn.none")}</p>
      ) : (
        <ul className="mt-2">
          {signals.map((s) => (
            <li key={s.id}>
              <button
                onClick={() => onJump(s.tab, s.entityId)}
                className="grid w-full grid-cols-[auto_1fr_auto_auto] items-center gap-3 border-t border-line
                           py-2.5 text-left transition-colors hover:bg-surface/40"
              >
                <span
                  className={`h-1.5 w-1.5 shrink-0 rounded-full ${
                    s.severity === "danger" ? "bg-danger" : "bg-warn"
                  }`}
                />
                <span className="truncate text-sm text-ink">{s.label}</span>
                <span className="data shrink-0 text-xs text-ink-faint">{s.value}</span>
                <span className="eyebrow shrink-0 text-ink-faint transition-colors group-hover:text-accent">→</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
