"use client";

import { useEffect, useState } from "react";

type Theme = "light" | "dark";

// Переключатель светлой/тёмной темы. Тема хранится в localStorage и
// применяется к <html data-theme>; анти-флэш — в layout (inline-скрипт).
export default function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>("light");

  useEffect(() => {
    const t = (document.documentElement.dataset.theme as Theme) || "light";
    setTheme(t === "dark" ? "dark" : "light");
  }, []);

  const set = (t: Theme) => {
    document.documentElement.dataset.theme = t;
    try { localStorage.setItem("okp_theme", t); } catch { /* приватный режим */ }
    setTheme(t);
  };

  return (
    <button
      onClick={() => set(theme === "dark" ? "light" : "dark")}
      title="Сменить тему"
      className="border border-line-strong px-3 py-1 text-[0.7rem] uppercase tracking-[0.12em]
                 text-ink-dim transition-colors hover:border-accent hover:text-accent"
      style={{ fontFamily: "var(--font-mono)" }}
    >
      {theme === "dark" ? "☀ Светлая" : "☾ Тёмная"}
    </button>
  );
}
