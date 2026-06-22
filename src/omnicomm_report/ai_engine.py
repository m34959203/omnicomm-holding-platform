"""AI-слой ВЗАИМОДЕЙСТВИЯ (Claude) поверх рекомендаций системы.

ПРИНЦИП (Дмитрий 22.06): инструкции / правила / датасет — В СИСТЕМЕ
(`config` КоАП/МРП, seed геозон, движки `geozone_limit`/`speeding`/
`recommendations`). **ИИ — только инструмент взаимодействия:** берёт ГОТОВУЮ,
посчитанную системой рекомендацию (`Recommendation.as_text()`) и переписывает её
более читаемо/деловым тоном, НИЧЕГО не меняя по сути. Claude не несёт доменных
знаний, не применяет правил, не хранит датасета — вся логика и данные в системе.

Graceful fallback: нет ключа / сети / ошибка API → системный текст как есть.
Система полностью работает и без Claude.
"""

from __future__ import annotations

import logging
import os

from . import config
from .recommendations import Recommendation

log = logging.getLogger(__name__)

# Промпт — ТОЛЬКО про форму (переписать читаемо). Никаких доменных правил,
# статей, лимитов: их посчитала система, они уже внутри входного текста.
_SYSTEM = """Ты — инструмент взаимодействия. Тебе дают ГОТОВУЮ рекомендацию,
полностью посчитанную системой. Твоя единственная задача — переписать её
более читаемо и деловым тоном на русском.

ЖЁСТКО:
- НИЧЕГО не меняй по сути: сохрани все числа, статьи, суммы, тип дороги, оговорки и действие;
- НЕ добавляй новых фактов, статей, сумм, советов или правил, которых нет во входном тексте;
- НЕ суммируй штрафы, НЕ обвиняй, НЕ убирай оговорки («оценочно», «к рассмотрению», «при условии фиксации»);
- если улучшать нечего — верни текст как есть.
Верни ТОЛЬКО переписанный текст рекомендации, без преамбул и заголовков."""


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
    """Переписать ГОТОВУЮ рекомендацию системы читаемее через Claude.

    Вход для модели — авторитетный текст системы (`rec.as_text()`); ИИ только
    переписывает форму. Fallback → тот же системный текст. `client` инъектируется
    в тестах (без сети).
    """
    system_text = rec.as_text()                         # источник истины — система
    if not getattr(config, "AI_RECOMMENDATIONS_ENABLED", False):
        return system_text
    c = client or _default_client()
    if c is None:
        return system_text
    try:
        msg = c.messages.create(
            model=config.AI_MODEL, max_tokens=config.AI_MAX_TOKENS,
            system=_SYSTEM,
            messages=[{"role": "user",
                       "content": "Рекомендация системы (перепиши читаемее, "
                                  "ничего не меняя по сути):\n\n" + system_text}],
        )
        text = "".join(b.text for b in msg.content
                       if getattr(b, "type", None) == "text").strip()
        return text or system_text
    except Exception as e:                              # noqa: BLE001
        log.warning("AI-слой недоступен (%s) — системный текст как есть",
                    repr(e)[:120])
        return system_text


def polish_fleet(recs, *, client=None) -> list[tuple[Recommendation, str]]:
    """Переписать список рекомендаций: [(Recommendation, текст)]."""
    c = client or _default_client()
    return [(r, polish_recommendation(r, client=c)) for r in recs]
