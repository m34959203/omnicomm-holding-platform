"use client";

import { SensorHealth } from "@/lib/api";
import { num } from "@/lib/format";
import { useLang } from "@/lib/i18n";

const TONE: Record<string, string> = {
  online: "text-accent",
  stale: "text-warn",
  offline: "text-danger",
  unknown: "text-ink-faint",
};
const DOT: Record<string, string> = {
  online: "🟢", stale: "🟡", offline: "🔴", unknown: "⚪",
};

export default function SensorHealthPanel({ sh }: { sh: SensorHealth }) {
  const { t } = useLang();
  const order = ["online", "stale", "offline", "unknown"] as const;

  return (
    <div>
      <div className="mb-6 grid grid-cols-2 gap-x-8 gap-y-3 sm:grid-cols-4">
        {order.map((k) => (
          <div key={k} className="border-t border-line py-3">
            <span className="eyebrow">{DOT[k]} {t(`sh.${k}`)}</span>
            <p className={`data text-2xl ${TONE[k]}`}>{num(sh.counts[k] ?? 0)}</p>
          </div>
        ))}
      </div>

      <p className="data mb-4 text-xs text-ink-faint">{t("sh.terminal_note")}</p>

      <div className="border-t border-line-strong pt-4">
        <span className="eyebrow">
          {sh.missing_capabilities.length ? t("sh.missing") : t("sh.missing.none")}
        </span>
        {sh.missing_capabilities.length > 0 && (
          <ul className="mt-2">
            {sh.missing_capabilities.slice(0, 30).map((m) => (
              <li
                key={m.terminal_id}
                className="grid grid-cols-[1fr_auto] items-center gap-4 border-t border-line py-2"
              >
                <span className="truncate text-sm text-ink">{m.name || m.terminal_id}</span>
                <span className="data text-xs text-warn">{m.missing.join(" · ")}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
