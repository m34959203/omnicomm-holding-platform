"use client";

import { useEffect, useRef, useState } from "react";
import { Job, getJob, startSync } from "@/lib/api";
import { ago } from "@/lib/format";

interface Props {
  syncedAt: number | null;
  periodLabel: string | null;
  onDone: () => void;
}

export default function SyncBar({ syncedAt, periodLabel, onDone }: Props) {
  const [job, setJob] = useState<Job | null>(null);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);
  const running = job?.status === "running" || job?.status === "pending";

  // Polling прогресса — надёжнее SSE за Cloudflare/реверс-прокси.
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

  async function trigger() {
    try {
      const j = await startSync(false); // прод: live-синк КАП
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

  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex items-baseline gap-3">
        <span className="eyebrow">Снимок данных</span>
        <span className="data text-xs text-ink-dim">
          {syncedAt
            ? `${periodLabel ?? ""} · обновлён ${ago(syncedAt)}`
            : "снимок ещё не собран"}
        </span>
      </div>

      <div className="flex items-center gap-4">
        {running && (
          <div className="flex items-center gap-3">
            <div className="relative h-[2px] w-44 overflow-hidden bg-line-strong">
              <div
                className="absolute inset-y-0 left-0 bg-accent transition-[width] duration-500 ease-out"
                style={{ width: `${job?.pct ?? 0}%` }}
              />
            </div>
            <span className="data w-10 text-right text-xs text-accent">
              {Math.round(job?.pct ?? 0)}%
            </span>
          </div>
        )}
        {running && (
          <span className="data max-w-[16rem] truncate text-xs text-ink-dim">
            {job?.message}
          </span>
        )}
        {job?.status === "error" && (
          <span className="data text-xs text-danger">Ошибка синка — сервер жив</span>
        )}

        <button
          onClick={trigger}
          disabled={running}
          className="group relative flex items-center gap-2 border border-line-strong px-4 py-2
                     text-xs uppercase tracking-[0.15em] text-ink
                     transition-colors hover:border-accent hover:text-accent
                     disabled:cursor-not-allowed disabled:opacity-50"
          style={{ fontFamily: "var(--font-mono)" }}
        >
          <span
            className={`live-dot inline-block h-1.5 w-1.5 rounded-full ${
              running ? "bg-accent" : "bg-ink-faint"
            }`}
          />
          {running ? "Синхронизация…" : "Синхронизировать"}
        </button>
      </div>
    </div>
  );
}
