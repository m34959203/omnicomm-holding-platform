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
