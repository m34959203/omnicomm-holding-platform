#!/usr/bin/env python3
"""Реверс-прокси holding-платформы на одном порту (для CF-туннеля :8535).

- `/api/*` и `/health` → FastAPI (127.0.0.1:API_PORT)
- всё остальное → статика Next-экспорта (`web/out/`)

Один публичный порт за туннелем `omnicomm.technokod.kz`. Без Node-сервера:
фронт — статический экспорт, динамику отдаёт FastAPI. Та же модель, что и
`omnicomm-fleet-report/scripts/fleet_proxy.py`, но static вместо streamlit и
без WebSocket (прогресс синка — polling).

Запуск: python3 deploy/holding_proxy.py <listen_port> <api_port> [static_dir]
"""

import sys
from pathlib import Path

from aiohttp import ClientSession, ClientTimeout, web

LISTEN = int(sys.argv[1]) if len(sys.argv) > 1 else 8535
API_PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 8810
STATIC = Path(sys.argv[3]) if len(sys.argv) > 3 else \
    Path(__file__).resolve().parent.parent / "web" / "out"
API_BASE = f"http://127.0.0.1:{API_PORT}"

_CT = {
    ".html": "text/html; charset=utf-8", ".js": "application/javascript",
    ".css": "text/css", ".json": "application/json", ".svg": "image/svg+xml",
    ".ico": "image/x-icon", ".txt": "text/plain; charset=utf-8",
    ".woff2": "font/woff2", ".woff": "font/woff", ".png": "image/png",
    ".webp": "image/webp", ".map": "application/json",
}


async def proxy_api(request: web.Request) -> web.StreamResponse:
    """Прокинуть запрос на FastAPI (динамика). Прозрачно для методов/тела."""
    url = API_BASE + request.rel_url.path_qs
    body = await request.read()
    timeout = ClientTimeout(total=120)
    try:
        async with ClientSession(timeout=timeout) as s:
            async with s.request(
                request.method, url, data=body or None,
                headers={k: v for k, v in request.headers.items()
                         if k.lower() not in ("host", "content-length")},
            ) as upstream:
                data = await upstream.read()
                resp = web.Response(
                    status=upstream.status, body=data,
                    content_type=upstream.content_type,
                )
                return resp
    except Exception as exc:  # noqa: BLE001 — мост не должен падать
        return web.json_response(
            {"error": "api_unreachable", "detail": str(exc)}, status=502)


def _safe_path(rel: str) -> Path | None:
    """Преобразовать URL-путь в файл внутри STATIC (защита от traversal)."""
    rel = rel.lstrip("/")
    candidate = (STATIC / rel).resolve()
    if STATIC.resolve() not in candidate.parents and candidate != STATIC.resolve():
        return None
    return candidate


async def serve_static(request: web.Request) -> web.StreamResponse:
    """Отдать файл из out/. Каталог → index.html. Не найдено → 404.html (SPA)."""
    path = request.path
    candidate = _safe_path(path)
    if candidate is None:
        return web.Response(status=403, text="forbidden")

    if candidate.is_dir():
        candidate = candidate / "index.html"
    if not candidate.exists():
        # trailingSlash-маршрут: /foo → /foo/index.html
        alt = _safe_path(path.rstrip("/") + "/index.html")
        candidate = alt if (alt and alt.exists()) else (STATIC / "404.html")

    if not candidate.exists():
        return web.Response(status=404, text="not found")

    ct = _CT.get(candidate.suffix, "application/octet-stream")
    # immutable-кэш для хэшированных ассетов _next/static
    headers = {}
    if "/_next/static/" in path:
        headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return web.Response(body=candidate.read_bytes(), content_type=ct.split(";")[0],
                        charset="utf-8" if "charset" in ct else None,
                        headers=headers)


def build_app() -> web.Application:
    app = web.Application()
    app.router.add_route("*", "/api/{tail:.*}", proxy_api)
    app.router.add_route("*", "/health", proxy_api)
    app.router.add_route("*", "/{tail:.*}", serve_static)
    return app


if __name__ == "__main__":
    print(f"holding-proxy :{LISTEN} → api {API_BASE} · static {STATIC}", flush=True)
    web.run_app(build_app(), host="0.0.0.0", port=LISTEN, print=None)
