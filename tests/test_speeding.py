"""Тесты детекции превышений по треку (СТ КАП + КоАП)."""

from omnicomm_report import speeding as sp
from omnicomm_report import config


def _pt(t, speed, sat=6):
    return {"date": t, "latitude": 0, "longitude": 0, "speed": speed, "satellitesCount": sat}


def _track(speeds, start=1000, step=30, sat=6):
    return [_pt(start + i * step, s, sat) for i, s in enumerate(speeds)]


TECH = lambda p: ("Тех дорога Инкудук", 30, False)      # техдорога, лимит 30
PUBLIC = lambda p: ("Трасса Каратау", 60, True)         # дорога общего пользования, 60


def test_sustained_segment_is_violation_single_point_is_not():
    # 4 точки по 50 при лимите 30 → нарушение (excess 20)
    v = sp.detect_speeding(_track([50, 50, 50, 50]), TECH, terminal_id="7")
    assert len(v) == 1 and v[0].excess == 20.0 and v[0].points == 4
    # одна точка над лимитом среди нормальных → не нарушение (R-INV-3)
    v2 = sp.detect_speeding(_track([10, 10, 55, 10, 10]), TECH)
    assert v2 == []


def test_despike_drops_gps_spike():
    # выброс 600 км/ч между нормальными → отброшен, нарушения нет
    track = _track([10, 600, 10, 10])
    v = sp.detect_speeding(track, TECH)
    assert v == []


def test_low_satellites_filtered():
    track = _track([50, 51, 52, 50], sat=2)   # <4 спутников
    assert sp.detect_speeding(track, TECH) == []


def test_tech_road_no_koap_only_disciplinary():
    v = sp.detect_speeding(_track([50, 50, 50]), TECH)[0]
    assert v.public_road is False
    assert v.koap_article is None and v.fine_kzt is None
    assert v.st_kap_severity == "грубое"      # excess 20 ≥ 6


def test_public_road_koap_article_no_fine_until_verified():
    # лимит 60, скорость 85 → excess 25 → ст.592 ч.2 (20–40)
    v = sp.detect_speeding(_track([85, 85, 85]), PUBLIC)[0]
    assert v.public_road is True
    assert v.koap_article == "ст.592 ч.2"
    assert v.fine_kzt is None                 # KOAP_VERIFIED=False (R-INV-8)


def test_koap_fine_when_verified(monkeypatch):
    monkeypatch.setattr(config, "KOAP_VERIFIED", True)
    article, fine = sp.koap_for(25)
    assert article == "ст.592 ч.2" and fine == 10 * config.MRP_KZT


def test_severity_grading():
    assert sp.st_kap_severity(2) == "незначительное"
    assert sp.st_kap_severity(4) == "существенное"
    assert sp.st_kap_severity(10) == "грубое"


def test_triage_by_maxspeed():
    rows = [
        {"consolidatedReport": {"vehicleId": 1, "mv": {"maxSpeed": 70}}},   # кандидат
        {"consolidatedReport": {"vehicleId": 2, "mv": {"maxSpeed": 5}}},    # нет
        {"consolidatedReport": {"vehicleId": 3, "mv": {"maxSpeed": None}}}, # нет данных
    ]
    assert sp.triage_speeding_suspects(rows, min_zone_limit=20) == ["1"]
