"""Тест глобального rate-limiter (token-bucket) — защита сервера Omnicomm."""

import time

from omnicomm_report.rate_limit import RateLimiter, get_limiter


def test_bucket_caps_steady_rate():
    # 3000/мин = 50/сек. Опустошаем стартовый бак, затем 25 запросов должны
    # занять ~0.5с (≈50/сек), а не мгновенно — лимит держится.
    lim = RateLimiter(3000)
    for _ in range(3000):
        lim.acquire()
    t0 = time.monotonic()
    for _ in range(25):
        lim.acquire()
    dt = time.monotonic() - t0
    assert 0.25 < dt < 1.5, dt          # держится около 0.5с, не мгновенно


def test_initial_burst_allowed():
    # стартовый бак полон — короткий всплеск в пределах ёмкости проходит быстро.
    lim = RateLimiter(6000)
    t0 = time.monotonic()
    for _ in range(50):
        lim.acquire()
    assert time.monotonic() - t0 < 0.3


def test_limiter_shared_per_account():
    a = get_limiter("acc1", 170)
    b = get_limiter("acc1", 170)
    c = get_limiter("acc2", 170)
    assert a is b and a is not c        # один лимитер на аккаунт
