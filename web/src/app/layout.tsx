import type { Metadata, Viewport } from "next";
import { Roboto, Roboto_Mono } from "next/font/google";
import "./globals.css";

// Шрифт Omnicomm Online — чистый гротеск Roboto (+ Roboto Mono для чисел).
const roboto = Roboto({
  variable: "--font-roboto",
  subsets: ["latin", "cyrillic"],
  weight: ["400", "500", "700"],
});
const robotoMono = Roboto_Mono({
  variable: "--font-roboto-mono",
  subsets: ["latin", "cyrillic"],
  weight: ["400", "500"],
});

export const metadata: Metadata = {
  title: "Казатомпром · Автопарк холдинга",
  description:
    "Аналитическая платформа автопарка холдинга: KPI по ДЗО, деньги, скоростной режим СТ КАП, геозоны.",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#13294b",
};

// Анти-флэш: применяем сохранённую тему до первой отрисовки.
const themeInit = `(function(){try{var t=localStorage.getItem('okp_theme');document.documentElement.dataset.theme=(t==='dark'||t==='light')?t:'light';}catch(e){document.documentElement.dataset.theme='light';}})();`;

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html
      lang="ru"
      data-theme="light"
      suppressHydrationWarning
      className={`${roboto.variable} ${robotoMono.variable} h-full`}
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeInit }} />
      </head>
      <body className="min-h-full">{children}</body>
    </html>
  );
}
