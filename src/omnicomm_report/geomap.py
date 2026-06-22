"""Карта геозон СТ КАП для портала: pydeck-слои из `list_geozones`.

Геозоны Omnicomm несут геометрию прямо в выгрузке:
`points: [{latitude, longitude}]`, тип `geometryTypeName` (Polygon / LineString),
собственный цвет `color` (hex) и для линий — ширину буфера `lineWidth` (метры).

Здесь — нормализация выгрузки в лёгкие фичи (`GeoFeature`) и ленивая сборка
pydeck-деки. Чистая часть (фичи / bbox / view_state) не зависит от pydeck и
покрыта тестами; сборка деки (`build_deck`) импортирует pydeck лениво и рисует
на базовой карте Carto — **без Mapbox-токена и без сети к стороннему API**.

Лимит достаём из имени геозоны (`geozones.parse_limit_from_name`) — тот же
источник истины, что и у движка скоростного режима.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from . import geozones

# Базовый цвет, если у геозоны нет/битый `color`.
_DEFAULT_RGB = (90, 120, 160)
# Геометрии, которые рисуем (прочее — следы ТС/служебное — отбрасываем).
_DRAWN_TYPES = {"Polygon", "LineString"}


def _hex_to_rgb(value: Any, default: tuple[int, int, int] = _DEFAULT_RGB
                ) -> tuple[int, int, int]:
    """`"#005824"` → `(0, 88, 36)`. Битый/пустой ввод → `default`."""
    if not isinstance(value, str):
        return default
    s = value.strip().lstrip("#")
    if len(s) != 6:
        return default
    try:
        return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
    except ValueError:
        return default


@dataclass
class GeoFeature:
    """Одна геозона, готовая к отрисовке.

    `path` — список `[lon, lat]` (порядок pydeck/GeoJSON). `kind` — `"polygon"`
    (заливка площадки) либо `"line"` (трасса с буфером `width` метров).
    """

    name: str
    kind: str                       # "polygon" | "line"
    path: list[list[float]]         # [[lon, lat], ...]
    color: tuple[int, int, int]
    limit: Optional[int] = None     # км/ч из имени, если есть
    width: int = 0                  # ширина буфера линии, м (для line)

    @property
    def tooltip(self) -> str:
        lim = f" · {self.limit} км/ч" if self.limit else ""
        return f"{self.name}{lim}"


def _coords(raw: dict) -> list[list[float]]:
    """`points: [{latitude, longitude}]` → `[[lon, lat], ...]` (валидные)."""
    out: list[list[float]] = []
    for p in raw.get("points") or []:
        if not isinstance(p, dict):
            continue
        lat, lon = p.get("latitude"), p.get("longitude")
        if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
            out.append([float(lon), float(lat)])
    return out


def geozone_features(raw_geozones: Any) -> list[GeoFeature]:
    """Нормализовать `list_geozones()` в список `GeoFeature` для карты.

    Берём только Polygon/LineString с ≥2 точками; служебные следы ТС
    (без типа геометрии) отбрасываем. Цвет — собственный `color` геозоны.
    """
    feats: list[GeoFeature] = []
    for g in raw_geozones or []:
        if not isinstance(g, dict):
            continue
        gtype = g.get("geometryTypeName")
        if gtype not in _DRAWN_TYPES:
            continue
        path = _coords(g)
        if len(path) < 2:
            continue
        name = (g.get("name") or "").strip() or "Геозона"
        feats.append(GeoFeature(
            name=name,
            kind="polygon" if gtype == "Polygon" else "line",
            path=path,
            color=_hex_to_rgb(g.get("color")),
            limit=geozones.parse_limit_from_name(name),
            width=int(g.get("lineWidth") or 0) if gtype == "LineString" else 0,
        ))
    return feats


def bbox(feats: list[GeoFeature]) -> Optional[tuple[float, float, float, float]]:
    """Габариты всех точек: `(min_lat, min_lon, max_lat, max_lon)` или None."""
    lats = [pt[1] for f in feats for pt in f.path]
    lons = [pt[0] for f in feats for pt in f.path]
    if not lats:
        return None
    return (min(lats), min(lons), max(lats), max(lons))


def _zoom_for(span: float) -> int:
    """Грубый web-mercator zoom под размах bbox (градусы)."""
    for thr, z in ((0.05, 13), (0.15, 11), (0.4, 10), (1.0, 9),
                   (2.5, 8), (5.0, 7), (10.0, 6)):
        if span <= thr:
            return z
    return 5


def view_state(feats: list[GeoFeature]) -> dict:
    """Центр и zoom карты под данные (по центру bbox)."""
    box = bbox(feats)
    if box is None:
        return {"latitude": 47.0, "longitude": 69.0, "zoom": 5}
    min_lat, min_lon, max_lat, max_lon = box
    span = max(max_lat - min_lat, max_lon - min_lon)
    return {
        "latitude": (min_lat + max_lat) / 2,
        "longitude": (min_lon + max_lon) / 2,
        "zoom": _zoom_for(span),
    }


def _payload(feats: list[GeoFeature], kind: str, *, fill_alpha: int) -> list[dict]:
    """Строки данных одного слоя (полигоны или линии) для pydeck."""
    rows = []
    for f in feats:
        if f.kind != kind:
            continue
        rows.append({
            "name": f.name,
            "tooltip": f.tooltip,
            "path": f.path,
            "polygon": f.path,
            "color": [*f.color, fill_alpha],
            "line_color": [*f.color, 230],
            # буфер линии в метрах → радиус pydeck PathLayer (width_units="meters")
            "width": max(f.width, 6),
        })
    return rows


def build_deck(raw_geozones: Any, *, fill_alpha: int = 70):
    """Собрать `pydeck.Deck` из выгрузки геозон (базовая карта Carto, без токена).

    Полигоны — `PolygonLayer` (заливка их цветом), линии-трассы — `PathLayer`
    (ширина = буфер `lineWidth` в метрах). Тултип показывает имя + лимит.
    Возвращает `None`, если нечего рисовать.
    """
    import pydeck as pdk  # ленивый импорт: тесты логики не требуют pydeck

    feats = geozone_features(raw_geozones)
    if not feats:
        return None

    polygons = _payload(feats, "polygon", fill_alpha=fill_alpha)
    lines = _payload(feats, "line", fill_alpha=fill_alpha)

    layers = []
    if polygons:
        layers.append(pdk.Layer(
            "PolygonLayer", data=polygons, get_polygon="polygon",
            get_fill_color="color", get_line_color="line_color",
            line_width_min_pixels=1, stroked=True, filled=True,
            pickable=True, auto_highlight=True,
        ))
    if lines:
        layers.append(pdk.Layer(
            "PathLayer", data=lines, get_path="path", get_color="line_color",
            get_width="width", width_units="meters", width_min_pixels=2,
            pickable=True, auto_highlight=True, cap_rounded=True,
        ))

    vs = view_state(feats)
    return pdk.Deck(
        layers=layers,
        initial_view_state=pdk.ViewState(
            latitude=vs["latitude"], longitude=vs["longitude"], zoom=vs["zoom"],
        ),
        map_provider="carto",
        map_style="light",
        tooltip={"text": "{tooltip}"},
    )
