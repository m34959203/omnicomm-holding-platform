// Инлайн-SVG-иконки по типу агрегата — fallback для блока «референс модели»,
// когда локального/внешнего фото нет. Стиль — линейный, в тон Atlas (currentColor).
import { JSX } from "react";

const P = { fill: "none", stroke: "currentColor", strokeWidth: 1.6,
  strokeLinecap: "round" as const, strokeLinejoin: "round" as const };

// набор простых пиктограмм (ключ → path-контент)
const ICONS: Record<string, JSX.Element> = {
  drill: (<><path {...P} d="M12 3v9" /><path {...P} d="M9 12h6l-3 8z" /><circle cx="12" cy="4" r="1.4" {...P} /></>),
  compressor: (<><rect x="3" y="9" width="14" height="8" rx="1.5" {...P} /><circle cx="7" cy="13" r="2" {...P} /><path {...P} d="M17 11h3v6h-3M15 9V6h3" /></>),
  truck: (<><path {...P} d="M3 15V7h11v8" /><path {...P} d="M14 10h4l3 3v2h-7" /><circle cx="7" cy="17" r="1.8" {...P} /><circle cx="17" cy="17" r="1.8" {...P} /></>),
  dump: (<><path {...P} d="M3 16V8l10-2 2 6H3" /><path {...P} d="M15 12h3l3 3v1h-6" /><circle cx="7" cy="17" r="1.8" {...P} /><circle cx="18" cy="17" r="1.8" {...P} /></>),
  tanker: (<><rect x="3" y="8" width="12" height="7" rx="3.5" {...P} /><path {...P} d="M15 10h3l3 3v2h-6" /><circle cx="7" cy="17" r="1.8" {...P} /><circle cx="18" cy="17" r="1.8" {...P} /></>),
  loader: (<><path {...P} d="M6 15V9h6v6" /><circle cx="8" cy="17" r="1.8" {...P} /><circle cx="15" cy="17" r="1.8" {...P} /><path {...P} d="M12 13l6-2v3l-6 1z" /></>),
  crane: (<><path {...P} d="M5 20V7h3v13" /><path {...P} d="M6 7l12 2" /><path {...P} d="M18 9v4" /><circle cx="7" cy="20" r="1.4" {...P} /></>),
  agp: (<><path {...P} d="M4 17V11h6v6" /><circle cx="6" cy="18" r="1.4" {...P} /><circle cx="11" cy="18" r="1.4" {...P} /><path {...P} d="M9 11l7-6 3 1-2 3" /><rect x="17" y="4" width="3" height="2" {...P} /></>),
  car: (<><path {...P} d="M4 15v-3l2-4h10l2 4v3" /><path {...P} d="M4 12h16" /><circle cx="8" cy="16" r="1.6" {...P} /><circle cx="16" cy="16" r="1.6" {...P} /></>),
  bus: (<><rect x="4" y="5" width="16" height="11" rx="1.5" {...P} /><path {...P} d="M4 12h16M9 5v7M15 5v7" /><circle cx="8" cy="18" r="1.4" {...P} /><circle cx="16" cy="18" r="1.4" {...P} /></>),
  logging: (<><rect x="3" y="8" width="12" height="8" rx="1" {...P} /><circle cx="9" cy="12" r="2.2" {...P} /><path {...P} d="M15 10h4l2 3v3h-6" /><circle cx="18" cy="17" r="1.6" {...P} /></>),
  generic: (<><rect x="4" y="7" width="16" height="9" rx="1.5" {...P} /><path {...P} d="M4 12h16" /></>),
};

const TYPE_ICON: Record<string, string> = {
  drill_rig: "drill", drill_rig_mobile: "drill", compressor: "compressor",
  logging_station: "logging", agp: "agp", tanker: "tanker",
  dump_truck: "dump", offroad_special: "dump", semi_truck: "truck", truck: "truck",
  loader: "loader", excavator: "loader", crane: "crane", tractor: "loader",
  refuse_truck: "truck", vacuum_sweeper: "truck", bus: "bus", car: "car",
};

export function TypeIcon({ type, size = 40 }: { type?: string; size?: number }) {
  const key = TYPE_ICON[type ?? ""] ?? "generic";
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden>
      {ICONS[key]}
    </svg>
  );
}
