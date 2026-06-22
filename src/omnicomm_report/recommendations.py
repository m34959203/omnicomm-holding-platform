"""Движок рекомендаций «на букве закона» (docs/knowledge-base/05).

Превращает нарушения (`speeding.Violation`) в рекомендации, СТРОГО соблюдая
красные линии:
- **R-INV-1:** КоАП-квалификация — только для эпизодов на дорогах общего
  пользования; на технологических — дисциплинарка СТ КАП, без статьи и ₸.
- **R-INV-2:** НЕ суммируем штрафы в «задолженность» водителю. Деньги — только
  обезличенный риск-индикатор (частота/тяжесть) + ставка за случай «при условии
  фиксации органом УДП», с оговоркой «оценочно, не начисленный штраф».
- **R-INV-6:** действие — «к рассмотрению руководителем ДЗО», не предписание.
- **R-INV-8:** ставка в ₸ показывается только при `config.KOAP_VERIFIED`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from . import config
from .speeding import Violation

_SEVERITY_RANK = {"в норме": 0, "незначительное": 1, "существенное": 2, "грубое": 3}


@dataclass
class Recommendation:
    terminal_id: str
    name: str
    episodes: int                       # всего устойчивых превышений за период
    max_excess: float
    worst_severity: str                 # худшая дисциплинарная градация СТ КАП
    public_episodes: int                # на дорогах общего пользования (КоАП)
    tech_episodes: int                  # на технологических (дисциплинарка СТ КАП)
    worst_article: Optional[str] = None # худшая статья КоАП среди public-эпизодов
    statutory_rate_kzt: Optional[int] = None  # ставка ЗА СЛУЧАЙ (не сумма!), если сверено
    risk_note: str = ""
    action: str = ""

    def as_text(self) -> str:
        parts = [f"ТС «{self.name or self.terminal_id}» — {self.episodes} "
                 f"устойчивых превышений за период (макс +{self.max_excess} км/ч; "
                 f"худшее: {self.worst_severity})."]
        if self.public_episodes and self.worst_article:
            rate = (f", ставка {self.statutory_rate_kzt} ₸/случай при условии "
                    f"фиксации органом УДП" if self.statutory_rate_kzt else
                    " (ставка не показывается — статьи не сверены)")
            parts.append(f"На дорогах общего пользования ({self.public_episodes}): "
                         f"{self.worst_article} КоАП РК{rate}.")
        if self.tech_episodes:
            parts.append(f"На технологических дорогах ({self.tech_episodes}): "
                         f"дисциплинарное отклонение по СТ КАП, без статьи и ₸.")
        if self.risk_note:
            parts.append(self.risk_note)
        if self.action:
            parts.append(self.action)
        return " ".join(parts)


def _worst(severities) -> str:
    return max(severities, key=lambda s: _SEVERITY_RANK.get(s, 0), default="в норме")


def _action_for(episodes: int, worst_severity: str) -> str:
    """Лестница эскалации (R-INV-6 — информируем, не предписываем)."""
    if episodes >= 5 or worst_severity == "грубое":
        return ("К рассмотрению руководителем ДЗО: беседа с водителем; при "
                "сохранении динамики — оценить дооснащение видеоконтролем (DSM).")
    if episodes >= 2:
        return "К рассмотрению руководителем ДЗО: провести беседу с водителем."
    return "К сведению: зафиксировать, наблюдать динамику."


def build_recommendation(terminal_id: str, name: str,
                         violations: list[Violation]) -> Optional[Recommendation]:
    """Собрать рекомендацию по нарушениям одного ТС за период. None — нет нарушений."""
    if not violations:
        return None
    public = [v for v in violations if v.public_road]
    tech = [v for v in violations if not v.public_road]
    worst_sev = _worst(v.st_kap_severity for v in violations)

    worst_article = None
    rate = None
    if public:
        # худшая статья = по максимальному превышению среди public-эпизодов
        worst_pub = max(public, key=lambda v: v.excess)
        worst_article = worst_pub.koap_article
        rate = worst_pub.fine_kzt          # ставка за случай (не сумма!), если сверено

    risk_note = ("Риск-индикатор (обезличенно, оценочно, НЕ начисленный штраф): "
                 f"частота {len(violations)} эпизодов — рост риска ДТП и износа.")

    return Recommendation(
        terminal_id=str(terminal_id), name=name or "", episodes=len(violations),
        max_excess=max(v.excess for v in violations), worst_severity=worst_sev,
        public_episodes=len(public), tech_episodes=len(tech),
        worst_article=worst_article, statutory_rate_kzt=rate,
        risk_note=risk_note, action=_action_for(len(violations), worst_sev),
    )


def recommend_fleet(violations_by_terminal: dict, names: Optional[dict] = None
                    ) -> list[Recommendation]:
    """Рекомендации по парку: {terminal_id -> [Violation]} → отсортированный список
    (худшее — выше: по тяжести, затем частоте)."""
    names = names or {}
    out = []
    for tid, vs in violations_by_terminal.items():
        rec = build_recommendation(tid, names.get(str(tid), ""), vs)
        if rec:
            out.append(rec)
    out.sort(key=lambda r: (_SEVERITY_RANK.get(r.worst_severity, 0), r.episodes),
             reverse=True)
    return out
