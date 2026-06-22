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


# --- детекция по визитам геозон (без геометрии) ------------------------------

def _visit(name, vid, max_speed, mileage=5.0, mileage_speeding=2, duration=3600,
           vname="КамАЗ"):
    return {"vehicleId": vid, "vehicleName": vname, "geozoneName": name,
            "geoInfo": {"startDate": 1000, "duration": duration},
            "mv": {"maxSpeed": max_speed, "mileage": mileage,
                   "mileageSpeeding": mileage_speeding}}


def test_detect_from_visits_public_and_tech():
    visits = [
        _visit("Трасса Каратау 60 км/ч", 1, 85),          # public, лимит 60 → excess 25
        _visit("Тех дорога Инкудук 30 км/ч", 1, 50),      # техдорога, лимит 30 → excess 20
        _visit("н.п. Тараз 60 км/ч", 2, 55),              # не превышение (55<60)
        _visit("Полигон 40 км/ч", 2, 70, mileage=0),      # стоял (mileage 0) → пропуск
    ]
    out = sp.detect_from_visits(visits)
    assert set(out) == {"1"}                              # только ТС 1 нарушил
    vs = {v.geozone: v for v in out["1"]}
    pub = vs["Трасса Каратау 60 км/ч"]
    assert pub.excess == 25.0 and pub.public_road is True and pub.koap_article == "ст.592 ч.2"
    tech = vs["Тех дорога Инкудук 30 км/ч"]
    assert tech.excess == 20.0 and tech.public_road is False and tech.koap_article is None


def test_detect_from_visits_uses_seed_when_name_has_no_limit():
    from omnicomm_report import geozones as gz
    seed = gz.build_seed([{"name": "Полигон Север"}])     # без «км/ч» → None в seed
    # имя без лимита → фолбэк-матрица (Полигон=зона4, truck=20); maxSpeed 35 → excess 15
    out = sp.detect_from_visits([_visit("Полигон Север", 1, 35)], seed=seed)
    assert out["1"][0].excess == 15.0 and out["1"][0].public_road is False
