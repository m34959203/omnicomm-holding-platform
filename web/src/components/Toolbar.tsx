"use client";

import { excelUrl } from "@/lib/api";
import { Lang, useLang } from "@/lib/i18n";
import ThemeToggle from "./ThemeToggle";

// Панель действий масткеда: переключатель языка RU/KK + кнопка Excel-выгрузки.
export default function Toolbar({ periodKey }: { periodKey?: string }) {
  const { lang, setLang, t } = useLang();
  const langs: Lang[] = ["ru", "kk"];

  return (
    <div className="flex flex-wrap items-center gap-3">
      <div className="flex gap-1">
        {langs.map((l) => (
          <button
            key={l}
            onClick={() => setLang(l)}
            className={`border px-3 py-1 text-[0.7rem] uppercase tracking-[0.12em] transition-colors ${
              lang === l ? "border-accent text-accent" : "border-line-strong text-ink-dim hover:text-ink"
            }`}
            style={{ fontFamily: "var(--font-mono)" }}
          >
            {l}
          </button>
        ))}
      </div>
      <a
        href={excelUrl(periodKey)}
        className="border border-accent px-3 py-1 text-[0.7rem] uppercase tracking-[0.12em] text-accent transition-colors hover:bg-accent hover:text-surface"
        style={{ fontFamily: "var(--font-mono)" }}
      >
        ↓ {t("excel.btn")}
      </a>
      <ThemeToggle />
    </div>
  );
}
