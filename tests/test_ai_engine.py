"""Тесты AI-движка полировки рекомендаций (с моками — без сети)."""

from omnicomm_report import ai_engine, config
from omnicomm_report.recommendations import Recommendation


def _rec():
    return Recommendation(
        terminal_id="7", name="КамАЗ", episodes=3, max_excess=25.0,
        worst_severity="существенное", public_episodes=2, tech_episodes=1,
        worst_article="ст.592 ч.2", statutory_rate_kzt=None,
        risk_note="оценочно", action="К рассмотрению руководителем ДЗО.")


class _FakeBlock:
    type = "text"
    def __init__(self, text): self.text = text

class _FakeMsg:
    def __init__(self, text): self.content = [_FakeBlock(text)]

class _FakeMessages:
    def __init__(self, text=None, raise_exc=None):
        self._text, self._exc = text, raise_exc
        self.last_kwargs = None
    def create(self, **kw):
        self.last_kwargs = kw
        if self._exc: raise self._exc
        return _FakeMsg(self._text)

class _FakeClient:
    def __init__(self, text=None, raise_exc=None):
        self.messages = _FakeMessages(text, raise_exc)


def test_fallback_when_disabled(monkeypatch):
    monkeypatch.setattr(config, "AI_RECOMMENDATIONS_ENABLED", False)
    out = ai_engine.polish_recommendation(_rec(), client=_FakeClient("ИИ-текст"))
    assert out == _rec().as_text()           # движок, не Claude


def test_fallback_when_no_client(monkeypatch):
    monkeypatch.setattr(config, "AI_RECOMMENDATIONS_ENABLED", True)
    # client=None и нет ключа → fallback
    out = ai_engine.polish_recommendation(_rec(), client=None)
    assert out == _rec().as_text()


def test_uses_claude_when_available(monkeypatch):
    monkeypatch.setattr(config, "AI_RECOMMENDATIONS_ENABLED", True)
    fake = _FakeClient("Деловая рекомендация по ТС КамАЗ.")
    out = ai_engine.polish_recommendation(_rec(), client=fake)
    assert out == "Деловая рекомендация по ТС КамАЗ."
    # модель — claude-opus-4-8, факты переданы, ставка не суммирована
    kw = fake.messages.last_kwargs
    assert kw["model"] == "claude-opus-4-8"
    assert "ст.592 ч.2" in kw["messages"][0]["content"]


def test_fallback_on_api_error(monkeypatch):
    monkeypatch.setattr(config, "AI_RECOMMENDATIONS_ENABLED", True)
    fake = _FakeClient(raise_exc=RuntimeError("API down"))
    out = ai_engine.polish_recommendation(_rec(), client=fake)
    assert out == _rec().as_text()           # graceful fallback


def test_facts_have_no_summed_fine():
    facts = ai_engine._facts(_rec())
    assert facts["статья_КоАП"] == "ст.592 ч.2"
    assert "задолженность" not in str(facts).lower()
    assert facts["ставка_за_случай_тенге"] is None
