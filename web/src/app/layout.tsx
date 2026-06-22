import type { Metadata, Viewport } from "next";
import { Spectral, IBM_Plex_Sans, JetBrains_Mono } from "next/font/google";
import "./globals.css";

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
      className={`${spectral.variable} ${body.variable} ${jetbrains.variable} h-full`}
    >
      <body className="min-h-full">{children}</body>
    </html>
  );
}
