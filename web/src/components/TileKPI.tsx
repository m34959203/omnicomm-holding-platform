"use client";

// Health-плитка с дисциплиной цвета: число всегда «кость» (кроме апсайда —
// потенциал экономии = lime), статус кодируется точкой и заливкой доля-бара.
// Норма НЕ светится: tone="neutral" = серая точка/бар или их отсутствие.

export type Tone = "neutral" | "accent" | "warn" | "danger";

export default function TileKPI({
  label, value, sub, tone = "neutral", share,
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: Tone;
  share?: number; // 0..1 — геометрическая доля (деноминатор виден глазом)
}) {
  const dot =
    tone === "accent" ? "bg-accent" : tone === "warn" ? "bg-warn"
      : tone === "danger" ? "bg-danger" : "bg-ink-faint";
  const valueColor = tone === "accent" ? "text-accent" : "text-ink";
  const barColor =
    tone === "accent" ? "bg-accent" : tone === "warn" ? "bg-warn"
      : tone === "danger" ? "bg-danger" : "bg-ink-dim";

  return (
    <div className="flex flex-col gap-1 border-t border-line py-3">
      <div className="flex items-center justify-between gap-2">
        <span className="eyebrow">{label}</span>
        <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${dot}`} />
      </div>
      <span className={`data text-2xl leading-tight ${valueColor}`}>{value}</span>
      {sub && <span className="data text-[0.7rem] text-ink-faint">{sub}</span>}
      {share != null && (
        <span className="mt-1 block h-1 bg-line-strong">
          <span
            className={`block h-1 ${barColor}`}
            style={{ width: `${Math.min(100, Math.max(0, share * 100))}%` }}
          />
        </span>
      )}
    </div>
  );
}
