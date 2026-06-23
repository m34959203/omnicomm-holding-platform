"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Recommendation } from "@/lib/api";
import { num } from "@/lib/format";
import { useLang } from "@/lib/i18n";
import { ColumnChart, RankBars } from "./charts";

const SEV_TONE: Record<string, string> = {
  грубое: "text-danger",
  значительное: "text-warn",
};

const DEFAULT_SHOWN = 12;

// Поле структурной рекомендации: подпись (mono) + значение.
function Field({
  label, value, full, tone = "ink",
}: {
  label: string; value: string; full?: boolean;
  tone?: "ink" | "dim" | "warn" | "accent";
}) {
  const color = tone === "accent" ? "text-accent" : tone === "warn" ? "text-warn"
    : tone === "dim" ? "text-ink-faint" : "text-ink";
  return (
    <div className={full ? "sm:col-span-2" : ""}>
      <span className="eyebrow text-ink-faint">{label}</span>
      <p className={`mt-0.5 text-xs leading-relaxed ${color}`}>{value}</p>
    </div>
  );
}

export default function Recommendations({
  recs, topOrgs = [], focusId, onOpenVehicle,
}: {
  recs: Recommendation[];
  topOrgs?: { label: string; value: number }[];
  focusId?: string | null;
  onOpenVehicle?: (id: string, name?: string) => void;
}) {
  const { t } = useLang();
  const [open, setOpen] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);
  const focusRef = useRef<HTMLLIElement | null>(null);

  // Drill из ленты «Что требует внимания»: раскрыть список, открыть карточку,
  // проскроллить и подсветить конкретного нарушителя.
  useEffect(() => {
    if (!focusId) return;
    const idx = recs.findIndex((r) => r.terminal_id === focusId);
    if (idx < 0) return;
    if (idx >= DEFAULT_SHOWN) setShowAll(true);
    setOpen(focusId);
    const id = setTimeout(() => {
      focusRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
    }, 120);
    return () => clearTimeout(id);
  }, [focusId, recs]);

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

  let shown = showAll ? recs.slice(0, 60) : recs.slice(0, DEFAULT_SHOWN);
  // Закрепить нарушителя из drill вверху, если он за пределами среза.
  if (focusId && !shown.some((r) => r.terminal_id === focusId)) {
    const f = recs.find((r) => r.terminal_id === focusId);
    if (f) shown = [f, ...shown];
  }

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
          const focused = focusId === r.terminal_id;
          return (
            <li
              key={r.terminal_id}
              ref={focused ? focusRef : null}
              className={`border-t border-line ${focused ? "bg-surface ring-1 ring-accent/50" : ""}`}
            >
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
                <div className="pb-5 pl-1">
                  <dl className="grid gap-x-8 gap-y-3 sm:grid-cols-2">
                    <Field label="Нарушение"
                      value={`${r.worst_severity} превышение · макс +${num(r.max_excess, 0)} км/ч`}
                      tone={r.worst_severity === "грубое" ? "warn" : "ink"} />
                    <Field label="Частота"
                      value={`${num(r.episodes)} эпизодов · дороги общ. пользования ${r.public_episodes} · техдороги ${r.tech_episodes}`} />
                    <Field label="Квалификация"
                      value={r.worst_article
                        ? `${r.worst_article} КоАП РК`
                        : "технологические дороги — дисциплинарная мера по СТ КАП (без статьи)"}
                      tone={r.worst_article ? "warn" : "dim"} />
                    <Field label="Штраф / ставка"
                      value={r.statutory_rate_kzt != null
                        ? `${num(r.statutory_rate_kzt)} ₸ за случай · ст. 592 КоАП РК`
                        : "технологические дороги — дисциплинарная мера, без ₸"}
                      tone={r.statutory_rate_kzt != null ? "warn" : "dim"} />
                    {r.risk_note && (
                      <Field label="Вероятный ущерб (оценочно)" value={r.risk_note} full tone="dim" />
                    )}
                    {(r.action || r.text) && (
                      <Field label="Действие" value={r.action || r.text} full tone="accent" />
                    )}
                  </dl>
                  {onOpenVehicle && (
                    <button
                      onClick={() => onOpenVehicle(r.terminal_id, r.name)}
                      className="eyebrow mt-4 border border-line-strong px-3 py-1 text-accent
                                 transition-colors hover:border-accent hover:bg-accent hover:text-surface"
                    >
                      Трек на карте →
                    </button>
                  )}
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
