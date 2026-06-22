import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Статический экспорт: прод раздаётся реверс-прокси :8535 как статика (out/),
  // /api/* проксируется на FastAPI. Без Node-сервера — меньше движущихся частей.
  output: "export",
  images: { unoptimized: true },
  trailingSlash: true,
};

export default nextConfig;
