"use client";

// Лёгкий словарный i18n без внешних зависимостей (R3.4). Язык хранится в
// localStorage, общий стор синхронит все компоненты через useSyncExternalStore.
// RU — по умолчанию; KK — казахский. Глубокие data-подписи доберём по мере.

import { useSyncExternalStore } from "react";

export type Lang = "ru" | "kk";

const KEY = "okp_lang";
const listeners = new Set<() => void>();
let current: Lang = "ru";

function read(): Lang {
  if (typeof window === "undefined") return "ru";
  const v = window.localStorage.getItem(KEY);
  return v === "kk" ? "kk" : "ru";
}

function subscribe(cb: () => void) {
  listeners.add(cb);
  return () => listeners.delete(cb);
}

export function setLang(l: Lang) {
  current = l;
  if (typeof window !== "undefined") window.localStorage.setItem(KEY, l);
  listeners.forEach((cb) => cb());
}

// Словарь. Ключ → {ru, kk}. Отсутствующий перевод падает на RU.
const DICT: Record<string, { ru: string; kk: string }> = {
  "mast.eyebrow": { ru: "Аналитическая платформа автопарка", kk: "Автопарк аналитика платформасы" },
  "mast.title_a": { ru: "Автопарк", kk: "Холдинг" },
  "mast.title_b": { ru: "холдинга", kk: "автопаркы" },
  "mast.lead": {
    ru: "Телеметрия 23 ДЗО Казатомпрома в едином разрезе: километры и литры в деньги, скоростной режим на букве СТ КАП, геозоны — без посемест­ных лицензий.",
    kk: "Қазатомпромның 23 ЕТҰ телеметриясы бірыңғай көрініс: километр мен литрді ақшаға, СТ ҚАП бойынша жылдамдық режимі, геозоналар — әр орынға лицензиясыз.",
  },
  "sec.hierarchy": { ru: "Парк по иерархии", kk: "Иерархия бойынша автопарк" },
  "sec.hierarchy.kicker": { ru: "ТС · данные у", kk: "КҚ · деректер" },
  "sec.money": { ru: "Деньги", kk: "Ақша" },
  "sec.money.kicker": { ru: "км и литры → ₸", kk: "км мен литр → ₸" },
  "sec.speeding": { ru: "Скоростной режим · СТ КАП", kk: "Жылдамдық режимі · СТ ҚАП" },
  "sec.speeding.kicker": { ru: "детекция → квалификация → рекомендации", kk: "анықтау → саралау → ұсыныстар" },
  "sec.geozones": { ru: "Геозоны", kk: "Геозоналар" },
  "sec.geozones.kicker": { ru: "площадки и трассы с лимитами", kk: "алаңдар мен трассалар лимиттермен" },
  "sec.sensor": { ru: "Качество данных", kk: "Деректер сапасы" },
  "sec.sensor.kicker": { ru: "светофор терминалов · доверие к цифрам", kk: "терминалдар бағдаршамы · сандарға сенім" },
  "sec.maint": { ru: "Контроль ТО", kk: "ТҚ бақылауы" },
  "sec.maint.kicker": { ru: "наработка → алерт", kk: "өндірім → ескерту" },
  "excel.btn": { ru: "Выгрузить в Excel", kk: "Excel-ге жүктеу" },
  "footer": { ru: "Omnicomm Holding Platform · снимок из кэша, чтение мгновенно", kk: "Omnicomm Holding Platform · кэштен снимок, оқу лезде" },
  // Sensor Health
  "sh.online": { ru: "онлайн", kk: "онлайн" },
  "sh.stale": { ru: "устарели", kk: "ескірген" },
  "sh.offline": { ru: "офлайн", kk: "офлайн" },
  "sh.unknown": { ru: "нет записи", kk: "жазба жоқ" },
  "sh.missing": { ru: "ТС с пропавшими блоками данных", kk: "Деректер блоктары жоғалған КҚ" },
  "sh.missing.none": { ru: "Все ТС передают ключевые блоки данных", kk: "Барлық КҚ негізгі блоктарды береді" },
  "sh.terminal_note": { ru: "Уровень — терминальный (давность данных). Сенсор-уровень недоступен через REST.", kk: "Деңгей — терминалдық (деректер ескілігі). Сенсор деңгейі REST арқылы қолжетімсіз." },
  // Maintenance
  "mt.overdue": { ru: "просрочено", kk: "мерзімі өтті" },
  "mt.due": { ru: "ожидается", kk: "күтілуде" },
  "mt.ok": { ru: "в норме", kk: "қалыпты" },
  "mt.vehicle": { ru: "ТС", kk: "КҚ" },
  "mt.status": { ru: "Статус", kk: "Күй" },
  "mt.left": { ru: "Осталось", kk: "Қалды" },
  "mt.mh": { ru: "моточас", kk: "моторсағ" },
  "mt.km": { ru: "км", kk: "км" },
  // Scope / навигация
  "scope.holding": { ru: "Весь холдинг", kk: "Бүкіл холдинг" },
  "scope.search": { ru: "Найти ДЗО / подрядчика…", kk: "ЕТҰ / мердігерді табу…" },
  "scope.units": { ru: "узлов", kk: "түйін" },
  "scope.vehicles": { ru: "ТС", kk: "КҚ" },
  "scope.title": { ru: "Организация", kk: "Ұйым" },
  // Health-полоса
  "health.title": { ru: "Здоровье холдинга", kk: "Холдинг денсаулығы" },
  "health.online": { ru: "Терминалы на связи", kk: "Байланыстағы терминалдар" },
  "health.savings": { ru: "Потенциал экономии", kk: "Үнемдеу әлеуеті" },
  "health.losses": { ru: "Топливо на простое", kk: "Бос жүрістегі отын" },
  "health.speeding": { ru: "ТС с превышениями", kk: "Асулары бар КҚ" },
  "health.overdue": { ru: "Просрочено ТО", kk: "Мерзімі өткен ТҚ" },
  "health.idle": { ru: "Холостой ход", kk: "Бос жүріс" },
  "health.year": { ru: "в год", kk: "жылына" },
  // Лента внимания
  "attn.title": { ru: "Что требует внимания", kk: "Назар талап ететіні" },
  "attn.none": { ru: "Срочных сигналов нет", kk: "Шұғыл сигналдар жоқ" },
  "attn.more": { ru: "ещё сигналов", kk: "тағы сигнал" },
  // Overview
  "ov.title": { ru: "Обзор по доменам", kk: "Домендер бойынша шолу" },
  "ov.open": { ru: "Открыть →", kk: "Ашу →" },
  // Табы
  "tab.money": { ru: "Деньги", kk: "Ақша" },
  "tab.speed": { ru: "Скоростной режим", kk: "Жылдамдық" },
  "tab.map": { ru: "Геозоны", kk: "Геозоналар" },
  "tab.quality": { ru: "Качество данных", kk: "Деректер сапасы" },
  "tab.maint": { ru: "Контроль ТО", kk: "ТҚ бақылауы" },
  "tab.visits": { ru: "Посещение геозон", kk: "Геозоналарға кіру" },
  "tab.fleet": { ru: "Сводный по ТС", kk: "КҚ бойынша жиынтық" },
  "tab.violations": { ru: "Нарушения", kk: "Бұзушылықтар" },
  "tab.fuel": { ru: "Топливо", kk: "Отын" },
  "rep.refuel": { ru: "Заправки, л", kk: "Құю, л" },
  "rep.drain": { ru: "Слив, л", kk: "Төгу, л" },
  "rep.delivery": { ru: "Выдача, л", kk: "Беру, л" },
  "rep.volume": { ru: "Бак (нач→кон)", kk: "Бак (баст→соң)" },
  "rep.geozone": { ru: "Геозона", kk: "Геозона" },
  "rep.enter": { ru: "Вход", kk: "Кіру" },
  "rep.duration": { ru: "Время", kk: "Уақыт" },
  "rep.visits": { ru: "визитов", kk: "кіру" },
  "rep.type": { ru: "Тип", kk: "Түрі" },
  "rep.maxspeed": { ru: "Макс, км/ч", kk: "Макс, км/сағ" },
  "rep.mileage": { ru: "Пробег, км", kk: "Жүріс, км" },
  "rep.fuel": { ru: "Топливо, л", kk: "Отын, л" },
  "rep.moto": { ru: "Моточасы", kk: "Моточас" },
  "rep.fine": { ru: "Штраф", kk: "Айыппұл" },
  "rep.empty": { ru: "Нет данных за период", kk: "Кезеңде дерек жоқ" },
  "common.show": { ru: "Показать", kk: "Көрсету" },
  "common.holdingOnly": { ru: "по всему холдингу", kk: "бүкіл холдинг бойынша" },
};

export function translate(lang: Lang, key: string): string {
  const e = DICT[key];
  if (!e) return key;
  return lang === "kk" ? e.kk || e.ru : e.ru;
}

export function useLang() {
  const lang = useSyncExternalStore(subscribe, read, () => "ru" as Lang);
  return {
    lang,
    setLang,
    t: (key: string) => translate(lang, key),
  };
}
