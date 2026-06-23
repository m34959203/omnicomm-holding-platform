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
            {sh.missing_capabilities.slice(0, 30).map((m) => {
              const tone = m.power === "ok" ? "text-danger"        // питание есть → реальный сбой датчика
                : m.power === "low" ? "text-warn"
                  : m.power === "critical" ? "text-ink-faint"      // обесточен → не сбой датчика
                    : "text-ink-faint";
              return (
                <li
                  key={m.terminal_id}
                  className="grid grid-cols-[1fr_auto] items-baseline gap-4 border-t border-line py-2"
                >
                  <div className="min-w-0">
                    <span className="block truncate text-sm text-ink">{m.name || m.terminal_id}</span>
                    {m.power_verdict && (
                      <span className={`data text-[0.7rem] ${tone}`}>
                        {m.voltage != null ? `${m.voltage} В · ` : ""}{m.power_verdict}
                      </span>
                    )}
                  </div>
                  <span className="data shrink-0 text-xs text-warn">{m.missing.join(" · ")}</span>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}
