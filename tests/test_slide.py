"""Тесты выгрузки «галочкой» — один лист-презентация (kb-15 §5)."""

import io
import re
import zipfile

from api import slide


def _snap():
    return {
        "orgs": [{"name": "КАП", "kpi": {
            "vehicles_total": 100, "total_mileage_km": 5000.0, "total_fuel_l": 2000.0,
            "total_engine_hours": 300.0, "fuel_idle_share": 0.3,
            "speeding_mileage_share": 0.02, "fuel_idle_l": 600.0,
            "mobile_fuel_per_100km": 28.5,
        }}],
        "fleet": {"vehicles": 100, "with_data": 90},
        "period": {"label": "01.06 — 30.06"},
        "economics": {"total_existing_kzt": 5_000_000, "total_potential_kzt": 2_000_000,
                      "buckets": [{"label": "Холостой ход", "existing_kzt": 3_000_000}]},
        "recommendations": [{"name": "КамАЗ 1", "episodes": 10, "max_excess": 20.0}],
        "fuel": {"totals": {"refuel_l": 10_000, "delivery_l": 4_000}},
        "sensor_health": {"counts": {"online": 60, "stale": 20, "offline": 20}},
        "maintenance": {"counts": {"просрочено": 3, "ожидается": 2},
                        "items": [{"name": "Урал 7", "status": "просрочено",
                                   "km_since": 16000, "mh_since": 100}]},
        "tyres": {"counts": {"просрочено": 4, "пора менять": 1}, "wear_kzt_total": 900_000,
                  "items": [{"name": "Самосвал 9", "status": "просрочено", "worn_share": 1.2}]},
    }


def _slide_xml(data: bytes) -> str:
    out = ""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for n in z.namelist():
            if n.startswith("ppt/slides/") and n.endswith(".xml"):
                out += z.read(n).decode("utf-8", "ignore")
    return out


def test_build_slide_all_sections_one_slide():
    data = slide.build_slide(_snap(), [])
    from pptx import Presentation
    prs = Presentation(io.BytesIO(data))
    assert len(prs.slides) == 1                    # ровно ОДИН лист
    xml = _slide_xml(data)
    for marker in ("КАП", "ДЕНЬГИ", "СКОРОСТНОЙ РЕЖИМ", "ТОПЛИВО",
                   "КАЧЕСТВО ДАННЫХ", "КОНТРОЛЬ ТО", "ШИНЫ"):
        assert marker in xml, marker


def test_build_slide_selected_sections_only():
    data = slide.build_slide(_snap(), ["fleet", "tyres"])
    xml = _slide_xml(data)
    assert "ШИНЫ" in xml and "ТС В ПРОГРАММЕ" in xml
    assert "ДЕНЬГИ" not in xml and "КОНТРОЛЬ ТО" not in xml


def test_slide_never_mentions_drains():
    """Бизнес-инвариант .pptx: «сливы» не выводятся."""
    xml = _slide_xml(slide.build_slide(_snap(), []))
    assert not re.search(r"[Сс]лив", xml)
