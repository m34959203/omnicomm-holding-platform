"use client";

import { useEffect, useRef, useState } from "react";
import { Job, Meta, getJob, startSync } from "@/lib/api";
import { ago } from "@/lib/format";

interface Props {
  syncedAt: number | null;
  periodLabel: string | null;
  onDone: () => void;
  snapshots: Meta[];
  periodKey: string;
  onSelectSnapshot: (key: string) => void;
}

// Готовые шаблоны периода: один клик собирает снимок за нужный диапазон.
const TEMPLATES: { label: string; days: number }[] = [
  { label: "Сутки", days: 1 },
  { label: "2 суток", days: 2 },
  { label: "Неделя", days: 7 },
];

export default function SyncBar({
  syncedAt, periodLabel, onDone, snapshots, periodKey, onSelectSnapshot,
}: Props) {
  const [job, setJob] = useState<Job | null>(null);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);
  const running = job?.status === "running" || job?.status === "pending";

  function poll(id: string) {
    if (timer.current) clearInterval(timer.current);
    timer.current = setInterval(async () => {
      try {
        const j = await getJob(id);
        setJob(j);
        if (j.status === "done" || j.status === "error") {
          if (timer.current) clearInterval(timer.current);
          if (j.status === "done") onDone();
        }
      } catch {
        if (timer.current) clearInterval(timer.current);
      }
    }, 800);
  }

  useEffect(() => () => { if (timer.current) clearInterval(timer.current); }, []);

  async function trigger(range?: { start_ts: number; end_ts: number }) {
    try {
      const j = await startSync(false, range);
      setJob(j);
      if (j.status === "done") onDone();
      else if (j.status !== "error") poll(j.id);
    } catch (e) {
      setJob({
        id: "", status: "error", pct: 0, message: "", elapsed_s: 0,
        result: null, error: String(e),
      });
    }
  }

  function syncTemplate(days: number) {
    const end = Math.floor(Date.now() / 1000);
    trigger({ start_ts: end - days * 86400, end_ts: end });
  }

  // Произвольный период по календарю (день начала 00:00 — день конца 23:59, UTC).
  function syncCustom() {
    if (!from || !to) return;
    const s = Math.floor(Date.parse(`${from}T00:00:00Z`) / 1000);
    const e = Math.floor(Date.parse(`${to}T23:59:59Z`) / 1000);
    if (Number.isNaN(s) || Number.isNaN(e) || s >= e) return;
    trigger({ start_ts: s, end_ts: e });
  }
  const today = new Date().toISOString().slice(0, 10);

  return (
    <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
      {/* выбор снимка */}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <span className="eyebrow">Снимок данных</span>
        {snapshots.length > 0 ? (
          <select
            value={periodKey || snapshots[0]?.period_key || ""}
            onChange={(e) => onSelectSnapshot(e.target.value)}
            className="data border border-line-strong bg-transparent px-2 py-1 text-xs text-ink
                       focus:border-accent focus:outline-none"
          >
            {snapshots.map((s) => (
              <option key={s.period_key} value={s.period_key} className="bg-surface text-ink">
                {s.label}
              </option>
            ))}
          </select>
        ) : (
          <span className="data text-xs text-ink-dim">снимок ещё не собран</span>
        )}
        {syncedAt && (
          <span className="data text-xs text-ink-faint">обновлён {ago(syncedAt)}</span>
        )}
      </div>

      {/* шаблоны периода + статус + ручной синк */}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <span className="eyebrow text-ink-faint">Собрать за:</span>
        {TEMPLATES.map((tpl) => (
          <button
            key={tpl.days}
            onClick={() => syncTemplate(tpl.days)}
            disabled={running}
            className="border border-line-strong px-2.5 py-1 text-[0.7rem] uppercase tracking-[0.12em]
                       text-ink-dim transition-colors hover:border-accent hover:text-accent
                       disabled:cursor-not-allowed disabled:opacity-40"
            style={{ fontFamily: "var(--font-mono)" }}
          >
            {tpl.label}
          </button>
        ))}

        {/* произвольный период по календарю */}
        <span className="eyebrow text-ink-faint">период:</span>
        <input
          type="date" value={from} max={to || today} onChange={(e) => setFrom(e.target.value)}
          disabled={running}
          className="data border border-line-strong bg-transparent px-2 py-1 text-xs text-ink
                     focus:border-accent focus:outline-none disabled:opacity-40"
        />
        <span className="text-ink-faint">—</span>
        <input
          type="date" value={to} min={from || undefined} max={today} onChange={(e) => setTo(e.target.value)}
          disabled={running}
          className="data border border-line-strong bg-transparent px-2 py-1 text-xs text-ink
                     focus:border-accent focus:outline-none disabled:opacity-40"
        />
        <button
          onClick={syncCustom}
          disabled={running || !from || !to}
          className="border border-accent px-2.5 py-1 text-[0.7rem] uppercase tracking-[0.12em]
                     text-accent transition-colors hover:bg-accent hover:text-surface
                     disabled:cursor-not-allowed disabled:opacity-40"
          style={{ fontFamily: "var(--font-mono)" }}
        >
          Собрать
        </button>

        {running && (
          <span className="flex items-center gap-2">
            <span className="relative h-[2px] w-28 overflow-hidden bg-line-strong">
              <span
                className="absolute inset-y-0 left-0 bg-accent transition-[width] duration-500 ease-out"
                style={{ width: `${job?.pct ?? 0}%` }}
              />
            </span>
            <span className="data w-9 text-right text-xs text-accent">
              {Math.round(job?.pct ?? 0)}%
            </span>
          </span>
        )}
        {job?.status === "error" && (
          <span className="data text-xs text-danger">Ошибка синка — сервер жив</span>
        )}
      </div>
    </div>
  );
}
