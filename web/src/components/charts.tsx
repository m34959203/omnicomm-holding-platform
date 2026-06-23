"use client";

// Лёгкие инлайн-SVG графики без зависимостей. Дисциплина цвета: нейтраль —
// кость/серый, accent/warn/danger только для смысловой нагрузки.

export type Tone = "accent" | "warn" | "danger" | "neutral";

const FILL: Record<Tone, string> = {
  accent: "var(--accent)",
  warn: "var(--warn)",
  danger: "var(--danger)",
  neutral: "var(--ink-dim)",
};
const cssVar = (t: Tone) => (t === "neutral" ? "var(--ink-dim)" : `var(--${t})`);

// Вертикальная столбчатая диаграмма (распределение по корзинам).
export function ColumnChart({
  bars,
}: {
  bars: { label: string; value: number; tone?: Tone }[];
}) {
  const W = 320, H = 150, padB = 32, padT = 18;
  const max = Math.max(1, ...bars.map((b) => b.value));
  const n = Math.max(1, bars.length);
  const gap = 16;
  const bw = (W - gap * (n + 1)) / n;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" className="block" role="img" aria-label="график">
      <line x1="0" y1={H - padB} x2={W} y2={H - padB} stroke="var(--line-strong)" strokeWidth="1" />
      {bars.map((b, i) => {
        const h = (b.value / max) * (H - padB - padT);
        const x = gap + i * (bw + gap);
        const y = H - padB - h;
        return (
          <g key={i}>
            <rect x={x} y={y} width={bw} height={Math.max(0, h)} fill={FILL[b.tone ?? "neutral"]} opacity="0.92" />
            <text x={x + bw / 2} y={y - 5} textAnchor="middle" fontSize="13"
              fill="var(--ink)" style={{ fontFamily: "var(--font-mono)" }}>{b.value}</text>
            <text x={x + bw / 2} y={H - padB + 16} textAnchor="middle" fontSize="10"
              fill="var(--ink-faint)" style={{ fontFamily: "var(--font-mono)" }}>{b.label}</text>
          </g>
        );
      })}
    </svg>
  );
}

// Горизонтальный 100%-stacked bar (доли статусов: online/stale/offline и т.п.).
export function StackedBar({
  segments,
}: {
  segments: { label: string; value: number; tone: Tone }[];
}) {
  const total = Math.max(1, segments.reduce((s, x) => s + x.value, 0));
  const W = 320, H = 20;
  let x = 0;
  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} preserveAspectRatio="none" className="block">
        {segments.map((s, i) => {
          const w = (s.value / total) * W;
          const rect = (
            <rect key={i} x={x} y="0" width={Math.max(0, w - 1)} height={H} fill={FILL[s.tone]} opacity="0.92" />
          );
          x += w;
          return rect;
        })}
      </svg>
      <div className="mt-2 flex flex-wrap gap-x-5 gap-y-1">
        {segments.map((s, i) => (
          <span key={i} className="data flex items-center gap-1.5 text-xs text-ink-dim">
            <span className="h-2 w-2 shrink-0" style={{ background: cssVar(s.tone) }} />
            {s.label} <span className="text-ink">{s.value}</span>
          </span>
        ))}
      </div>
    </div>
  );
}

// Линейный график (скорость во времени). threshold — горизонтальная риска лимита.
export function LineChart({
  series, max, threshold, unit = "",
}: {
  series: number[];
  max?: number;
  threshold?: number;
  unit?: string;
}) {
  const W = 640, H = 150, padB = 16, padT = 16, padX = 4;
  const n = series.length;
  const mx = Math.max(1, max ?? Math.max(...series, threshold ?? 0));
  const x = (i: number) => padX + (i / Math.max(1, n - 1)) * (W - padX * 2);
  const y = (v: number) => padT + (1 - v / mx) * (H - padT - padB);
  const d = series.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" className="block" role="img" aria-label="график скорости">
      <line x1={padX} x2={W - padX} y1={H - padB} y2={H - padB} stroke="var(--line-strong)" strokeWidth="1" />
      {threshold != null && (
        <line x1={padX} x2={W - padX} y1={y(threshold)} y2={y(threshold)}
          stroke="var(--danger)" strokeWidth="1" strokeDasharray="4 3" opacity="0.75" />
      )}
      {n > 1 && <path d={d} fill="none" stroke="var(--positive)" strokeWidth="1.4" />}
      <text x={padX} y={padT - 4} fontSize="11" fill="var(--ink-faint)"
        style={{ fontFamily: "var(--font-mono)" }}>{Math.round(mx)}{unit ? ` ${unit}` : ""}</text>
    </svg>
  );
}

// Ранжированные горизонтальные бары (топ-N: ДЗО по эпизодам и т.п.).
export function RankBars({
  items, tone = "warn", unit = "",
}: {
  items: { label: string; value: number }[];
  tone?: Tone;
  unit?: string;
}) {
  const max = Math.max(1, ...items.map((i) => i.value));
  return (
    <ul className="flex flex-col gap-2.5">
      {items.map((it, i) => (
        <li key={i}>
          <div className="flex items-baseline justify-between gap-3">
            <span className="truncate text-sm text-ink">{it.label}</span>
            <span className="data shrink-0 text-xs text-ink-faint">
              {it.value}{unit ? ` ${unit}` : ""}
            </span>
          </div>
          <div className="mt-1 h-1.5 bg-line-strong">
            <div className="h-1.5" style={{ width: `${(it.value / max) * 100}%`, background: cssVar(tone) }} />
          </div>
        </li>
      ))}
    </ul>
  );
}
