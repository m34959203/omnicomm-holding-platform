"""Тесты адаптивной карточки ТС по типу агрегата: классификация, реестр моделей,
обогащение payload карточки типом + референсом модели."""

from omnicomm_report import vehicle_models as vm
from omnicomm_report import vehicle_types as vt


# --- Классификация по имени (порядок специфичных хинтов) ---

def test_classify_real_fleet_names():
    cases = {
        "Буровая Установка(ЗИФ) №27": "drill_rig",
        "Atlas Copco V900 №8": "compressor",
        "ATLAS COPCO XRVS336 №3": "compressor",
        "VOLVO FMX420 152AG-13": "dump_truck",
        "IVECO ASTRA 397BK13": "dump_truck",
        "SHACMAN 651AL11": "dump_truck",
        "ГАЗ 3309 АГП H008511": "agp",
        "DEVELON SD300N N925AND": "loader",
        "Toyota Prado": "car",
    }
    for name, key in cases.items():
        assert vt.classify_from_name(name) == key, name


def test_specific_hints_beat_generic_chassis():
    # УРБ на шасси МАЗ → буровая-на-шасси, НЕ самосвал/тягач
    assert vt.classify_from_name("МАЗ 253AO11 (УРБ)") == "drill_rig_mobile"
    # каротажная станция на Урале → каротаж, НЕ offroad_special
    assert vt.classify_from_name("Урал 752AW13 (Каротажная станция)") == "logging_station"
    # обычный Урал без спецхинта → вездеход
    assert vt.classify_from_name("УРАЛ H013111") == "offroad_special"


def test_classify_unknown_is_other():
    assert vt.classify_from_name("Объект 24") == "other"
    assert vt.classify_from_name(None) == "other"


def test_new_profiles_registered():
    for key in ("drill_rig", "drill_rig_mobile", "compressor", "logging_station",
                "agp", "tanker", "semi_truck", "offroad_special"):
        assert vt.profile(key).key == key
    # главный параметр буровой — л/моточас, самосвала — л/100км
    assert vt.profile("drill_rig").primary_metric == "l_per_mh"
    assert vt.profile("dump_truck").primary_metric == "l_per_100km"


# --- Реестр моделей ---

def test_model_lookup_and_type_hint():
    ref = vm.lookup("VOLVO FMX420 152AG-13")
    assert ref and ref["canonical"].startswith("Volvo FMX") and ref["type_hint"] == "dump_truck"
    assert ref["image_slug"] == "volvo-fmx"      # локальное фото есть


def test_model_lookup_order_urb_before_maz():
    ref = vm.lookup("МАЗ 253AO11 (УРБ)")
    assert ref and "УРБ" in ref["canonical"]      # не общий МАЗ-самосвал


def test_model_lookup_none_for_unknown():
    assert vm.lookup("Ёмкость №2-3 К1ДТ") is None
    assert vm.lookup("") is None


# --- Обогащение payload карточки ---

def test_payload_enriched_with_type_and_model():
    from api import vehicle
    track = [{"lat": 47.1, "lon": 68.2, "speed": 12.0, "ts": 100, "sat": 8}]
    p = vehicle._payload_from_track("777", 0, 86400, track,
                                    name="VOLVO FMX420 152AG-13", state={}, source="test")
    assert p["vehicle_type"] == "dump_truck"
    assert p["type_label"] == "Самосвал"
    assert p["model_ref"]["canonical"].startswith("Volvo FMX")
    assert p["name"] == "VOLVO FMX420 152AG-13"


def test_payload_kinematic_fallback_when_name_unknown():
    from api import vehicle
    # имя не распознано, но трек почти без движения → буровая по кинематике
    track = [{"lat": 47.1, "lon": 68.2, "speed": 1.0, "ts": 100, "sat": 8}]
    p = vehicle._payload_from_track("778", 0, 86400, track,
                                    name="Объект 24", state={}, source="test")
    assert p["vehicle_type"] == "drill_rig"
    assert p["model_ref"] is None
