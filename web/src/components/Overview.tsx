"use client";

import { Economics, Kpi, Maintenance, Recommendation, SensorHealth } from "@/lib/api";
import { moneyShort, num } from "@/lib/format";
import { useLang } from "@/lib/i18n";
import { TabKey } from "@/lib/scope";

function Card({
  eyebrow, value, sub, tone, onOpen, openLabel,
}: {
  eyebrow: string; value: string; sub: string;
  tone: "neutral" | "accent" | "warn" | "danger";
  onOpen: () => void; openLabel: string;
}) {
  const valueColor =
    tone === "accent" ? "text-accent" : tone === "danger" ? "text-danger"
      : tone === "warn" ? "text-warn" : "text-ink";
  return (
    <button
      onClick={onOpen}
      className="group flex flex-col gap-2 bg-surface p-5 text-left transition-colors hover:bg-surface-2"
    >
      <span className="eyebrow">{eyebrow}</span>
      <span className={`display text-3xl ${valueColor}`}>{value}</span>
      <span className="data text-xs text-ink-faint">{sub}</span>
      <span className="eyebrow mt-2 text-ink-dim transition-colors group-hover:text-accent">
        {openLabel}
      </span>
    </button>
  );
}

// 4 домен-карточки: один сигнал на домен + вход в таб (прогрессивное раскрытие).
export default function Overview({
  kpi, eco, recsCount, sensor, maint, onOpen,
}: {
  kpi: Kpi;
  eco: Economics | null;
  recsCount: number;
  sensor: SensorHealth | null;
  maint: Maintenance | null;
  onOpen: (tab: TabKey) => void;
}) {
  const { t } = useLang();
  const offline = sensor?.counts.offline ?? 0;
  const missing = sensor?.missing_capabilities.length ?? 0;
  const overdue = maint?.counts["просрочено"] ?? 0;
  const due = maint?.counts["ожидается"] ?? 0;

  return (
    <section>
      <span className="eyebrow">{t("ov.title")}</span>
      <div className="mt-3 grid grid-cols-1 gap-px bg-line-strong sm:grid-cols-2 lg:grid-cols-4">
        <Card
          eyebrow={t("tab.money")}
          value={moneyShort(eco ? eco.coi_annual_kzt : kpi.idle_fuel_cost)}
          sub={eco ? t("health.year") : t("health.losses")}
          tone="accent"
          onOpen={() => onOpen("money")}
          openLabel={t("ov.open")}
        />
        <Card
          eyebrow={t("tab.speed")}
          value={num(recsCount)}
          sub={t("health.speeding")}
          tone={recsCount > 0 ? "warn" : "neutral"}
          onOpen={() => onOpen("speed")}
          openLabel={t("ov.open")}
        />
        <Card
          eyebrow={t("tab.quality")}
          value={num(offline)}
          sub={`${t("sh.offline")} · ${num(missing)} ${t("sh.missing")}`}
          tone={offline > 0 ? "danger" : "neutral"}
          onOpen={() => onOpen("quality")}
          openLabel={t("ov.open")}
        />
        <Card
          eyebrow={t("tab.maint")}
          value={num(overdue)}
          sub={due ? `+${num(due)} ${t("mt.due")}` : t("mt.ok")}
          tone={overdue > 0 ? "danger" : due > 0 ? "warn" : "neutral"}
          onOpen={() => onOpen("maint")}
          openLabel={t("ov.open")}
        />
      </div>
    </section>
  );
}
