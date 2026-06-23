"""Тест классификатора «транспорт vs стационарный объект» (вентиль доверия)."""

from omnicomm_report.classify import is_transport


def test_non_transport_objects_excluded():
    for name in [
        "АЗС Кыземшек Ёмкость №6 К2АИ",
        "Емкость №4 К3П2 ДТ",
        "ФЭС 196 кВт",
        "BS Power BSCU-275 №42 — Г7-96411",
        "AKSA-700 №23",
        "JETPOWER ген",
        "001 862059068243073",   # имя-IMEI
    ]:
        assert is_transport(name) is False, name


def test_real_vehicles_kept():
    for name in [
        "Hilux H757910",
        "КАМАЗ H1651-13",
        "JAC T6 H1653-13",
        "Автобус Тойтоа Коастер (Н1940/13)",
        "ZHONGTONG LCK6127H 845AV-13",
        "ТК №4",
    ]:
        assert is_transport(name) is True, name


def test_empty_name_fail_open():
    # без имени не отсекаем — лучше лишний ТС, чем потерянная машина
    assert is_transport(None) is True
    assert is_transport("") is True


def test_power_classification():
    from omnicomm_report.sensor_health import classify_power, PowerStatus
    assert classify_power(13.8) == PowerStatus.OK        # 12В норма
    assert classify_power(10.9) == PowerStatus.LOW       # 12В просадка
    assert classify_power(27.6) == PowerStatus.OK        # 24В норма
    assert classify_power(22.0) == PowerStatus.LOW       # 24В просадка
    assert classify_power(2.0) == PowerStatus.CRITICAL   # обесточен
    assert classify_power(None) == PowerStatus.UNKNOWN
    assert classify_power(0) == PowerStatus.UNKNOWN
