"""AI-движок полировки рекомендаций через Claude (Anthropic SDK).

ПРИНЦИП (docs/CONCEPT.md §1, kb-05 §0): Claude НЕ источник права. Движок
`recommendations.py` детерминированно считает факты (статья КоАП, ставка, тип
дороги, частота, действие) с соблюдением инвариантов R-INV-1…8. AI-слой ТОЛЬКО
переформулирует эти факты в связный деловой текст — без новых правовых
утверждений, без суммирования штрафов, без обвинений. Это «на букве закона»,
а не «ИИ-вода».

Graceful fallback: нет ключа / сети / ошибка API → детерминированный
`Recommendation.as_text()`. Система работает и без Claude.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Optional

from . import config
from .recommendations import Recommendation

log = logging.getLogger(__name__)

_SYSTEM = """Ты — редактор управленческих рекомендаций для автопарка холдинга КАП (Казатомпром).
Тебе дают УЖЕ ПОСЧИТАННЫЕ ФАКТЫ о превышениях скорости одного ТС за период.
Задача: переформулировать их в одну связную деловую рекомендацию на русском (3–5 предложений).

СТРОГО ЗАПРЕЩЕНО:
- добавлять, менять или выдумывать статьи закона, суммы или числа, которых нет во входных фактах;
- суммировать штрафы в «задолженность» водителя — ставка указана ЗА СЛУЧАЙ и только при условии фиксации органом УДП;
- обвинять водителя или утверждать его вину; формулировки — нейтральные, «к рассмотрению»;
- предписывать кадровые меры (депремирование, приказ) — только «к рассмотрению руководителем ДЗО».

Если у эпизодов есть «технологические дороги» — это дисциплинарное отклонение по СТ КАП,
БЕЗ статьи КоАП и без суммы. Статья КоАП и ставка применимы ТОЛЬКО к «дорогам общего пользования».
Пиши деловым тоном, без общих планов и воды. Верни ТОЛЬКО текст рекомендации, без преамбул и заголовков."""


def _facts(rec: Recommendation) -> dict:
    """Факты движка → вход для Claude (только посчитанное, ничего нового)."""
    return {
        "ТС": rec.name or rec.terminal_id,
        "эпизодов_всего": rec.episodes,
        "макс_превышение_км_ч": rec.max_excess,
        "худшая_тяжесть_СТ_КАП": rec.worst_severity,
        "эпизоды_на_дорогах_общего_пользования": rec.public_episodes,
        "эпизоды_на_технологических_дорогах": rec.tech_episodes,
        "статья_КоАП": rec.worst_article,
        "ставка_за_случай_тенге": rec.statutory_rate_kzt,
        "рекомендуемое_действие": rec.action,
    }


def _default_client():
    """Anthropic-клиент из ENV (ANTHROPIC_API_KEY). None — ключа/SDK нет."""
    if not (os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN")):
        return None
    try:
        import anthropic
        return anthropic.Anthropic()
    except Exception:                                   # noqa: BLE001
        return None


def polish_recommendation(rec: Recommendation, *, client=None) -> str:
    """Переформулировать рекомендацию через Claude. Fallback → `rec.as_text()`.

    `client` — инъекция Anthropic-клиента (для тестов без сети).
    """
    if not getattr(config, "AI_RECOMMENDATIONS_ENABLED", False):
        return rec.as_text()
    c = client or _default_client()
    if c is None:
        return rec.as_text()
    try:
        msg = c.messages.create(
            model=config.AI_MODEL, max_tokens=config.AI_MAX_TOKENS,
            system=_SYSTEM,
            messages=[{"role": "user",
                       "content": "Факты:\n" + json.dumps(_facts(rec),
                                                          ensure_ascii=False, indent=2)}],
        )
        text = "".join(b.text for b in msg.content
                       if getattr(b, "type", None) == "text").strip()
        return text or rec.as_text()
    except Exception as e:                              # noqa: BLE001
        log.warning("AI-полировка недоступна (%s) — детерминированный текст",
                    repr(e)[:120])
        return rec.as_text()


def polish_fleet(recs, *, client=None) -> list[tuple[Recommendation, str]]:
    """Полировка списка рекомендаций: [(Recommendation, текст)]."""
    c = client or _default_client()
    return [(r, polish_recommendation(r, client=c)) for r in recs]
