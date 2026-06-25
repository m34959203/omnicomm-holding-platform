"""Глобальный rate-limiter на аккаунт Omnicomm (защита московского сервера).

Документированный лимит Omnicomm Online: **180 запросов/мин на пользователя**
(при превышении — блокировка). Параллельный синк создаёт несколько клиентов на
ОДНОЙ учётке, поэтому пер-клиентной паузы недостаточно — нужен общий на процесс
token-bucket, через который проходят ВСЕ запросы всех потоков под этим логином.

Реализация — классический token-bucket: ёмкость = лимит/мин, доливка равномерная;
`acquire()` блокирует поток, пока не освободится токен. Гарантирует, что суммарно
по всем потоком частота не превысит заданную, сколько бы воркеров ни было.
"""

from __future__ import annotations

import threading
import time
from typing import Callable, Optional


class RateLimiter:
    def __init__(self, rate_per_min: float):
        self.capacity = float(rate_per_min)
        self.tokens = float(rate_per_min)
        self.refill_per_sec = rate_per_min / 60.0
        self._last = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        """Заблокировать до получения одного токена (≤ rate_per_min суммарно)."""
        while True:
            with self._lock:
                now = time.monotonic()
                self.tokens = min(
                    self.capacity,
                    self.tokens + (now - self._last) * self.refill_per_sec)
                self._last = now
                if self.tokens >= 1.0:
                    self.tokens -= 1.0
                    return
                wait = (1.0 - self.tokens) / self.refill_per_sec
            time.sleep(min(max(wait, 0.0), 1.0))

    def set_rate(self, rate_per_min: float) -> None:
        """Сменить темп на лету (для адаптивного управления). Ёмкость = новый темп."""
        with self._lock:
            self.capacity = float(rate_per_min)
            self.refill_per_sec = rate_per_min / 60.0
            self.tokens = min(self.tokens, self.capacity)


class AdaptiveRateLimiter:
    """Адаптивный темп по здоровью сервера (AIMD), в границах [min, max].

    Сигнал — латентность самих запросов + ошибки (никаких лишних проб). По окну из
    `adjust_every` запросов: чисто и быстро (avg latency < `lat_low`) → темп += `ai_step`
    (аддитивный рост); ошибки/таймауты ИЛИ avg latency > `lat_high` → темп ×= `md_factor`
    (резкий сброс). Так забор сам подбирает максимум, который сервер тянет без деградации,
    и откатывается при первых признаках перегрузки. Верхняя граница ≤ аккаунт-лимита.
    """

    def __init__(self, *, start: float, min_rate: float, max_rate: float,
                 lat_low: float, lat_high: float, adjust_every: int = 30,
                 ai_step: float = 10.0, md_factor: float = 0.5,
                 on_change: Optional["Callable[[float, str], None]"] = None):
        self.min_rate = float(min_rate)
        self.max_rate = float(max_rate)
        self.rate = max(self.min_rate, min(float(start), self.max_rate))
        self.lat_low = lat_low
        self.lat_high = lat_high
        self.adjust_every = max(1, int(adjust_every))
        self.ai_step = ai_step
        self.md_factor = md_factor
        self._on_change = on_change
        self._bucket = RateLimiter(self.rate)
        self._lock = threading.Lock()
        self._n = 0
        self._lat_sum = 0.0
        self._err = 0

    def acquire(self) -> None:
        self._bucket.acquire()

    def record(self, latency: float, ok: bool) -> None:
        """Учесть итог запроса; раз в `adjust_every` — пересчитать темп (AIMD)."""
        with self._lock:
            self._n += 1
            self._lat_sum += max(0.0, latency)
            if not ok:
                self._err += 1
            if self._n < self.adjust_every:
                return
            avg = self._lat_sum / self._n
            errs = self._err
            self._n = 0
            self._lat_sum = 0.0
            self._err = 0
            old = self.rate
            if errs > 0 or avg > self.lat_high:
                self.rate = max(self.min_rate, self.rate * self.md_factor)
                why = f"backoff (ошибок {errs}, avg {avg:.1f}с)"
            elif avg < self.lat_low:
                self.rate = min(self.max_rate, self.rate + self.ai_step)
                why = f"ускорение (avg {avg:.1f}с чисто)"
            else:
                return                               # в «коридоре» — держим темп
            self._bucket.set_rate(self.rate)
        if self._on_change and self.rate != old:
            self._on_change(self.rate, why)


_limiters: dict[str, RateLimiter] = {}
_registry_lock = threading.Lock()


def get_limiter(account: str, rate_per_min: float) -> RateLimiter:
    """Общий лимитер на аккаунт (один на процесс, разделяется всеми клиентами)."""
    key = account or "_default"
    with _registry_lock:
        lim = _limiters.get(key)
        if lim is None:
            lim = RateLimiter(rate_per_min)
            _limiters[key] = lim
        return lim
