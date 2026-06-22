"""Тесты карты геозон (`geomap`): нормализация, цвет, bbox/zoom, фильтры.

Чистая логика — без pydeck и без сети. Формат `points` сверен с боевым
`list_geozones` (Polygon/LineString, points[{latitude,longitude}], color hex).
"""

from omnicomm_report import geomap


# Минимальные образцы в боевом формате Omnicomm.
_LINE = {
    "name": "н.п. Кыземшек 50 км/ч (АО НАК Казатомпром)",
    "geometryTypeName": "LineString", "color": "#005824", "lineWidth": 50,
    "points": [
        {"latitude": 45.258667, "longitude": 68.925476},
        {"latitude": 45.263447, "longitude": 68.927515},
    ],
}
_POLY = {
    "name": "СТОП (АО НАК Казатомпром)",
    "geometryTypeName": "Polygon", "color": "#ee1d24", "lineWidth": None,
    "points": [
        {"latitude": 44.186459, "longitude": 66.724611},
        {"latitude": 44.186443, "longitude": 66.724826},
        {"latitude": 44.187000, "longitude": 66.724700},
    ],
}
# Служебный след ТС без типа геометрии — должен отбрасываться.
_JUNK = {
    "name": "Renault Duster 710YZ13", "geometryTypeName": None,
    "points": [{"latitude": 43.86, "longitude": 68.73}],
}


def test_hex_to_rgb():
    assert geomap._hex_to_rgb("#005824") == (0, 88, 36)
    assert geomap._hex_to_rgb("#EE1D24") == (238, 29, 36)


def test_hex_to_rgb_bad_input_falls_back():
    assert geomap._hex_to_rgb(None) == geomap._DEFAULT_RGB
    assert geomap._hex_to_rgb("#zzz") == geomap._DEFAULT_RGB
    assert geomap._hex_to_rgb("12345") == geomap._DEFAULT_RGB


def test_features_kinds_and_coord_order():
    feats = geomap.geozone_features([_LINE, _POLY])
    assert [f.kind for f in feats] == ["line", "polygon"]
    # путь в порядке [lon, lat]
    assert feats[0].path[0] == [68.925476, 45.258667]


def test_features_carry_limit_color_width():
    line, poly = geomap.geozone_features([_LINE, _POLY])
    assert line.limit == 50 and line.color == (0, 88, 36) and line.width == 50
    assert poly.limit is None and poly.color == (238, 29, 36) and poly.width == 0


def test_features_drop_junk_and_short_paths():
    short = {"name": "x", "geometryTypeName": "Polygon",
             "points": [{"latitude": 1.0, "longitude": 2.0}]}
    feats = geomap.geozone_features([_JUNK, short, _LINE])
    assert [f.name for f in feats] == [_LINE["name"]]


def test_features_empty_and_non_dict_safe():
    assert geomap.geozone_features(None) == []
    assert geomap.geozone_features(["nope", 42, {}]) == []


def test_bbox_and_view_state_center():
    feats = geomap.geozone_features([_LINE, _POLY])
    min_lat, min_lon, max_lat, max_lon = geomap.bbox(feats)
    assert min_lat == 44.186443 and max_lat == 45.263447
    vs = geomap.view_state(feats)
    assert abs(vs["latitude"] - (min_lat + max_lat) / 2) < 1e-9
    assert abs(vs["longitude"] - (min_lon + max_lon) / 2) < 1e-9
    assert 3 <= vs["zoom"] <= 13


def test_view_state_default_when_empty():
    vs = geomap.view_state([])
    assert vs["zoom"] == 5 and vs["latitude"] == 47.0


def test_zoom_tightens_with_smaller_span():
    assert geomap._zoom_for(0.01) > geomap._zoom_for(3.0)
    assert geomap._zoom_for(50.0) == 5


def test_tooltip_includes_limit_only_when_present():
    line, poly = geomap.geozone_features([_LINE, _POLY])
    assert "50 км/ч" in line.tooltip
    assert poly.tooltip == "СТОП (АО НАК Казатомпром)"
