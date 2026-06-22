"""Тесты движка скоростных лимитов по геозонам (СТ КАП)."""

from omnicomm_report import geozones as gz
from omnicomm_report.geozones import VehicleCategory as VC


# --- матрица 6×3 -------------------------------------------------------------

def test_zone_matrix_values():
    assert gz.ZONE_SPEED_MATRIX[VC.LIGHT][6] == 110
    assert gz.ZONE_SPEED_MATRIX[VC.TRUCK_SPECIAL][4] == 20
    assert gz.ZONE_SPEED_MATRIX[VC.BUS][6] == 90
    assert gz.ZONE_SPEED_MATRIX[VC.TRUCK_SPECIAL][1] == 5


# --- классификация зоны по реальным именам -----------------------------------

def test_classify_zone_real_names():
    assert gz.classify_zone("Тех дорога вдоль ОПЗ км") == 4       # техдорога > завод
    assert gz.classify_zone("Завод ОПЗ Огр.") == 2
    assert gz.classify_zone("Полигон Сат-1 Север") == 4
    assert gz.classify_zone("Вахтовый лагерь км") == 1
    assert gz.classify_zone("г. Усть-Каменогорск") == 5
    assert gz.classify_zone("Трасса Каратау - Будёновск") == 6
    assert gz.classify_zone("Дорога до Рудник Инкай 80 км/ч") == 6
    assert gz.classify_zone("Сателлит-1") == 4                    # неизвестно → техдорога


def test_public_road_gate():
    # дороги общего пользования (КоАП) vs технологические (дисциплинарка СТ КАП)
    assert gz.is_public_road(gz.classify_zone("Трасса Каратау")) is True
    assert gz.is_public_road(gz.classify_zone("г. Тараз")) is True
    assert gz.is_public_road(gz.classify_zone("Тех дорога Инкудук")) is False
    assert gz.is_public_road(gz.classify_zone("ГТП (СП Акбастау)")) is False
    assert gz.is_public_road(gz.classify_zone("Вахтовый посёлок")) is False


# --- категория ТС (дефолтный классификатор) ----------------------------------

def test_categorize_vehicle():
    assert gz.categorize_vehicle("TOYOTA LC Prado 250 709AL11") is VC.LIGHT
    assert gz.categorize_vehicle("Автобус ПАЗ-32053 040AY13") is VC.BUS
    assert gz.categorize_vehicle("Компрессор XRVS 336 №8") is VC.TRUCK_SPECIAL
    assert gz.categorize_vehicle("КамАЗ-43118 (БЕНЗОВОЗ)") is VC.TRUCK_SPECIAL
    assert gz.categorize_vehicle("Неведомая машина") is VC.TRUCK_SPECIAL  # дефолт строгий


# --- лимит из имени + нормализация аномалий -----------------------------------

def test_parse_limit_from_name():
    assert gz.parse_limit_from_name("Дорога до Рудник Инкай 80 км/ч") == 80
    assert gz.parse_limit_from_name("Скоростной режим 60 км/ч объезд") == 60
    assert gz.parse_limit_from_name("Сателлит-1") is None


def test_normalize_seed_limit_anomalies():
    assert gz.normalize_seed_limit(60) == 60
    assert gz.normalize_seed_limit("90") == 90
    assert gz.normalize_seed_limit(None) is None
    assert gz.normalize_seed_limit("") is None
    assert gz.normalize_seed_limit("СТОП") is None       # запрет ≠ скоростной лимит
    assert gz.normalize_seed_limit(0) is None
    assert gz.normalize_seed_limit(999) is None          # нереальный → отброс


# --- основной резолвер -------------------------------------------------------

def test_geozone_limit_named_wins():
    # именованный лимит из справочника — источник истины
    r = gz.geozone_limit("Тех дорога вдоль ОПЗ", VC.TRUCK_SPECIAL, named_limit=20)
    assert r.limit == 20 and r.source == "named" and r.zone == 4
    assert r.public_road is False        # техдорога → дисциплинарка, не КоАП


def test_geozone_limit_parsed_from_name():
    r = gz.geozone_limit("Дорога до Рудник Инкай 80 км/ч", VC.LIGHT)
    assert r.limit == 80 and r.zone == 6 and r.public_road is True


def test_geozone_limit_matrix_fallback():
    # нет именованного лимита → матрица по зоне×категории
    r = gz.geozone_limit("Сателлит-1", VC.TRUCK_SPECIAL)
    assert r.limit == 20 and r.source == "matrix" and r.zone == 4
    r2 = gz.geozone_limit("г. Караганда", VC.LIGHT)
    assert r2.limit == 60 and r2.source == "matrix" and r2.zone == 5


def test_geozone_limit_named_not_lowered_by_matrix():
    # официальные 80 на «Технологическая дорога» Семизбай (zone4) НЕ занижаются до 20
    r = gz.geozone_limit("Технологическая дорога", VC.TRUCK_SPECIAL, named_limit=80)
    assert r.limit == 80 and r.source == "named"


# --- seed из выгрузки Omnicomm ------------------------------------------------

def test_build_seed_and_lookup():
    raw = [{"name": "н.п. Кыземшек 50 км/ч (АО НАК Казатомпром)"},
           {"name": "Полигон Север"}]            # без лимита
    seed = gz.build_seed(raw)
    assert gz.seed_limit(seed, "Н.П. КЫЗЕМШЕК 50 КМ/Ч (АО НАК Казатомпром)") == 50  # регистр-независимо
    assert gz.seed_limit(seed, "Полигон Север") is None
    assert gz.seed_limit(seed, "неизвестная") is None
