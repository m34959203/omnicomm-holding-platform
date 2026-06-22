"use client";

import { SensorHealth } from "@/lib/api";
import { useLang } from "@/lib/i18n";
import { StackedBar } from "./charts";

export default function SensorHealthPanel({ sh }: { sh: SensorHealth }) {
  const { t } = useLang();

  const segments = [
    { label: t("sh.online"), value: sh.counts.online ?? 0, tone: "neutral" as const },
    { label: t("sh.stale"), value: sh.counts.stale ?? 0, tone: "warn" as const },
    { label: t("sh.offline"), value: sh.counts.offline ?? 0, tone: "danger" as const },
    { label: t("sh.unknown"), value: sh.counts.unknown ?? 0, tone: "neutral" as const },
  ].filter((s) => s.value > 0);

  return (
    <div>
      <div className="mb-6">
        <StackedBar segments={segments} />
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
