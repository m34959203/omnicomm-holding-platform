// Контурные рисунки (line-art) по типу агрегата — вместо фото в карточке ТС.
// viewBox 0 0 200 120, техника «едет влево», stroke=currentColor. Узнаваемый
// силуэт каждого класса (буровая-мачта, самосвал с кузовом, компрессор, каротаж…).

const W = (cx: number, cy = 96, r = 13) =>
  `<circle cx="${cx}" cy="${cy}" r="${r}"/><circle cx="${cx}" cy="${cy}" r="4.5"/>`;

const ART: Record<string, string> = {
  car:
    '<path d="M14,90 V76 Q14,71 20,70 L44,66 L62,49 Q66,45 73,45 H118 Q126,45 131,51 L150,68 L184,74 Q190,75 190,82 V90"/>' +
    '<path d="M46,66 L150,68"/><path d="M92,46 V66"/>' + W(56) + W(150),
  bus:
    '<path d="M14,90 V44 Q14,37 22,37 H180 Q187,37 187,44 V90"/>' +
    '<path d="M20,50 H182"/><path d="M20,66 H150"/>' +
    '<path d="M40,50 V66 M62,50 V66 M84,50 V66 M106,50 V66 M128,50 V66"/>' +
    '<path d="M150,66 V90"/>' + W(48) + W(156),
  truck:
    '<path d="M116,90 V50 H150 L162,60 V90"/><path d="M150,64 H132 V50"/>' +
    '<path d="M14,90 V64 H116 V90"/><path d="M14,64 H116 M14,76 H116"/>' + W(44) + W(140),
  dump_truck:
    '<path d="M120,90 V52 H152 L166,64 V90"/><path d="M166,66 H146 V52"/>' +
    '<path d="M14,90 V72 H120 V90"/><path d="M28,72 L40,42 H120 L120,66"/>' + W(46) + W(140),
  tanker:
    '<path d="M116,90 V52 H148 L162,64 V90"/><path d="M162,66 H142 V52"/>' +
    '<path d="M14,72 H112"/><rect x="14" y="46" width="98" height="30" rx="15"/>' +
    '<path d="M62,46 V76"/>' + W(44) + W(96),
  semi_truck:
    '<path d="M118,90 V44 H150 L166,60 V90"/><path d="M166,64 H144 V44"/>' +
    '<path d="M14,90 V48 H118 V90"/>' + W(40) + W(70) + W(150),
  offroad_special:
    '<path d="M120,88 V50 H152 L166,62 V88"/><path d="M166,66 H146 V50"/>' +
    '<path d="M16,88 V60 H120 V88"/>' + W(46, 94, 17) + W(96, 94, 17) + W(150, 94, 17),
  drill_rig:
    '<path d="M60,100 L92,20 L124,100"/><path d="M70,80 H114 M78,58 H106 M85,40 H99"/>' +
    '<path d="M92,20 V12"/><path d="M84,12 H100"/>' +
    '<path d="M40,100 H150 V112 H40 Z"/><rect x="118" y="82" width="30" height="18"/>',
  drill_rig_mobile:
    '<path d="M116,92 V52 H148 L162,64 V92"/><path d="M162,66 H142 V52"/>' +
    '<path d="M14,92 V70 H116 V92"/>' +
    '<path d="M40,70 L36,20 M56,70 L60,20 M36,20 H60"/><path d="M44,54 H52 M40,38 H56"/>' + W(44) + W(138),
  compressor:
    '<path d="M40,50 H150 Q158,50 158,58 V80 H40 Q32,80 32,72 Z"/>' +
    '<path d="M60,50 V80 M120,50 V80"/><path d="M40,66 L14,78"/><circle cx="14" cy="80" r="4"/>' +
    W(70, 88, 12) + W(120, 88, 12),
  logging_station:
    '<path d="M116,92 V52 H148 L162,64 V92"/><path d="M162,66 H142 V52"/>' +
    '<path d="M14,92 V56 H116 V92"/><circle cx="52" cy="72" r="18"/><circle cx="52" cy="72" r="5"/>' +
    W(44) + W(138),
  agp:
    '<path d="M116,92 V54 H148 L162,66 V92"/><path d="M162,68 H142 V54"/>' +
    '<path d="M14,92 V70 H116 V92"/><path d="M70,70 L110,26"/><path d="M40,70 L70,70 L70,60"/>' +
    '<rect x="104" y="18" width="22" height="14"/>' + W(44) + W(138),
  loader:
    '<path d="M78,88 V54 H112 Q120,54 120,62 V88"/><path d="M78,66 H120"/>' +
    '<path d="M78,74 L34,74 L18,58"/><path d="M18,58 L18,84 L40,84"/>' + W(58, 92, 17) + W(104, 92, 17),
  excavator:
    '<path d="M20,100 H120 Q128,100 128,92 V86 H12 V92 Q12,100 20,100 Z"/>' +
    '<circle cx="30" cy="93" r="4"/><circle cx="110" cy="93" r="4"/>' +
    '<path d="M64,86 V58 Q64,52 72,52 H108 Q116,52 116,60 V86"/>' +
    '<path d="M108,72 L150,40 L176,64 L150,84"/><path d="M176,64 L184,78 L170,82 Z"/>',
  crane:
    '<path d="M14,92 V66 H116 V92"/><path d="M116,92 V56 H146 L160,66 V92"/><path d="M160,68 H142 V56"/>' +
    '<rect x="40" y="54" width="34" height="12"/><path d="M57,54 L150,22"/><path d="M150,22 L150,44"/>' +
    W(46) + W(138),
  tractor:
    '<path d="M108,86 V50 H150 Q156,50 156,56 V86"/><path d="M112,64 H150"/>' +
    '<path d="M40,86 V70 H108 V86"/>' + W(44, 90, 12) + W(132, 86, 20),
  refuse_truck:
    '<path d="M120,90 V54 H150 L164,66 V90"/><path d="M164,68 H144 V54"/>' +
    '<path d="M14,90 V46 H120 V90"/><path d="M14,58 L36,58 L40,46"/>' + W(46) + W(140),
  vacuum_sweeper:
    '<path d="M116,90 V54 H146 L160,66 V90"/><path d="M160,68 H142 V54"/>' +
    '<rect x="20" y="50" width="94" height="30" rx="8"/><path d="M14,86 A8,8 0 0 0 30,86"/>' +
    W(48) + W(134),
  other:
    '<path d="M14,88 V52 H120 V42 H150 L172,60 V88"/><path d="M120,64 H150 V42"/>' + W(46) + W(150),
};

export function TypeArt({ type, height = 92 }: { type?: string; height?: number }) {
  const inner = ART[type ?? "other"] ?? ART.other;
  return (
    <svg viewBox="0 0 200 120" height={height} style={{ width: "100%", height }} aria-hidden
      preserveAspectRatio="xMidYMid meet">
      <g fill="none" stroke="currentColor" strokeWidth={3} strokeLinecap="round"
        strokeLinejoin="round" dangerouslySetInnerHTML={{ __html: inner }} />
    </svg>
  );
}
