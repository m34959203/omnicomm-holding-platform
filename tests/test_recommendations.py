"""Тесты движка рекомендаций «на букве закона»."""

from omnicomm_report import recommendations as rec
from omnicomm_report.speeding import Violation


def _v(excess, public, severity, article=None):
    return Violation(terminal_id="7", geozone="z", limit=30, max_speed=30 + excess,
                     excess=excess, duration_s=60, start_ts=1000, points=3,
                     public_road=public, st_kap_severity=severity, koap_article=article)


def test_separates_public_and_tech_no_summed_fine():
    vs = [_v(25, True, "существенное", "ст.592 ч.2"),
          _v(20, False, "грубое")]
    r = rec.build_recommendation("7", "КамАЗ", vs)
    assert r.public_episodes == 1 and r.tech_episodes == 1
    assert r.worst_severity == "грубое"
    assert r.statutory_rate_kzt is None              # не сверено → нет ставки
    # текст не содержит суммарной «задолженности» (R-INV-2)
    txt = r.as_text()
    assert "задолжен" not in txt.lower()
    assert "не начисленный штраф" in txt.lower()


def test_action_escalation():
    one = rec.build_recommendation("7", "", [_v(15, False, "грубое")])
    assert "беседа" in one.action.lower() or "беседу" in one.action.lower()  # грубое → эскалация
    few = rec.build_recommendation("7", "", [_v(2, False, "незначительное")])
    assert "к сведению" in few.action.lower()


def test_no_violations_returns_none():
    assert rec.build_recommendation("7", "", []) is None


def test_recommend_fleet_sorted_worst_first():
    by_t = {
        "1": [_v(2, False, "незначительное")],
        "2": [_v(20, False, "грубое"), _v(20, False, "грубое")],
    }
    out = rec.recommend_fleet(by_t, names={"2": "Урал"})
    assert out[0].terminal_id == "2"     # грубое+частота выше
    assert out[0].name == "Урал"
