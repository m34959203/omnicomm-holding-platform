import type { Metadata, Viewport } from "next";
import { Spectral, IBM_Plex_Sans, JetBrains_Mono, Noto_Sans } from "next/font/google";
import "./globals.css";

// Валютный шрифт: JetBrains/IBM Plex в subset latin+cyrillic НЕ содержат ₸ (U+20B8)
// → браузер подставлял огромный фолбэк-глиф, ломавший сетку плиток. Noto Sans
// содержит ₸ — применяем к денежным значениям через класс .money.
const currency = Noto_Sans({
  variable: "--font-currency",
  subsets: ["latin"],
  weight: ["400", "500"],
});

const spectral = Spectral({
  variable: "--font-spectral",
  subsets: ["latin", "cyrillic"],
  weight: ["400", "500", "600"],
});

const body = IBM_Plex_Sans({
  variable: "--font-body",
  subsets: ["latin", "cyrillic"],
  weight: ["400", "500", "600"],
});

const jetbrains = JetBrains_Mono({
  variable: "--font-jetbrains",
  subsets: ["latin", "cyrillic"],
});

export const metadata: Metadata = {
  title: "Казатомпром · Автопарк холдинга",
  description:
    "Аналитическая платформа автопарка холдинга: KPI по ДЗО, деньги, скоростной режим СТ КАП, геозоны.",
};

// Явный viewport — корректный масштаб на телефоне (R3.5).
export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#0c0c0d",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html
      lang="ru"
      className={`${spectral.variable} ${body.variable} ${jetbrains.variable} ${currency.variable} h-full`}
    >
      <body className="min-h-full">{children}</body>
    </html>
  );
}
