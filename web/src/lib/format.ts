// Форматирование для RU-аудитории: деньги ₸, тысячные пробелы, краткие млн/тыс.

const nf = new Intl.NumberFormat("ru-RU");

export const num = (v: number, frac = 0) =>
  new Intl.NumberFormat("ru-RU", {
    minimumFractionDigits: frac,
    maximumFractionDigits: frac,
  }).format(v ?? 0);

// NBSP ( ) между числом, разрядом и ₸ — чтобы «14,1 млн ₸» не рвалось
// переносом на узких плитках (баг «14,1 млн ↵ ₸»).
const NB = "\u00A0";
export const money = (v: number) => `${nf.format(Math.round(v ?? 0))}${NB}₸`;

export function moneyShort(v: number): string {
  v = v ?? 0;
  if (Math.abs(v) >= 1_000_000) return `${num(v / 1_000_000, 1)}${NB}млн${NB}₸`;
  if (Math.abs(v) >= 1_000) return `${num(v / 1_000, 0)}${NB}тыс${NB}₸`;
  return `${num(v, 0)}${NB}₸`;
}

export const pct = (v: number, frac = 0) => `${num((v ?? 0) * 100, frac)}%`;

export function ago(ts: number): string {
  const s = Math.max(0, Math.floor(Date.now() / 1000 - ts));
  if (s < 60) return `${s} с назад`;
  if (s < 3600) return `${Math.floor(s / 60)} мин назад`;
  if (s < 86400) return `${Math.floor(s / 3600)} ч назад`;
  return `${Math.floor(s / 86400)} дн назад`;
}
