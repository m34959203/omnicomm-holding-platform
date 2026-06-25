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


def test_adaptive_speeds_up_on_clean_fast():
    from omnicomm_report.rate_limit import AdaptiveRateLimiter
    a = AdaptiveRateLimiter(start=40, min_rate=20, max_rate=120,
                            lat_low=2.0, lat_high=5.0, adjust_every=10, ai_step=10)
    for _ in range(10):                      # окно чистых быстрых запросов
        a.record(latency=1.0, ok=True)
    assert a.rate == 50                      # +ai_step (аддитивный рост)


def test_adaptive_backs_off_on_slow():
    from omnicomm_report.rate_limit import AdaptiveRateLimiter
    a = AdaptiveRateLimiter(start=80, min_rate=20, max_rate=120,
                            lat_low=2.0, lat_high=5.0, adjust_every=10, md_factor=0.5)
    for _ in range(10):                      # окно медленных ответов
        a.record(latency=9.0, ok=True)
    assert a.rate == 40                      # ×0.5 (резкий сброс)


def test_adaptive_backs_off_on_errors():
    from omnicomm_report.rate_limit import AdaptiveRateLimiter
    a = AdaptiveRateLimiter(start=60, min_rate=20, max_rate=120,
                            lat_low=2.0, lat_high=5.0, adjust_every=10)
    for i in range(10):
        a.record(latency=1.0, ok=(i != 0))   # одна ошибка в окне
    assert a.rate == 30                       # ошибка → сброс несмотря на низкую латентность


def test_adaptive_respects_bounds():
    from omnicomm_report.rate_limit import AdaptiveRateLimiter
    hi = AdaptiveRateLimiter(start=115, min_rate=20, max_rate=120,
                             lat_low=2.0, lat_high=5.0, adjust_every=5, ai_step=10)
    for _ in range(15):
        hi.record(0.5, True)
    assert hi.rate == 120                     # не выше max
    lo = AdaptiveRateLimiter(start=25, min_rate=20, max_rate=120,
                             lat_low=2.0, lat_high=5.0, adjust_every=5, md_factor=0.5)
    for _ in range(15):
        lo.record(10.0, False)
    assert lo.rate == 20                      # не ниже min


def test_adaptive_holds_in_corridor():
    from omnicomm_report.rate_limit import AdaptiveRateLimiter
    a = AdaptiveRateLimiter(start=50, min_rate=20, max_rate=120,
                            lat_low=2.0, lat_high=5.0, adjust_every=10)
    for _ in range(10):                       # латентность между low и high → держим
        a.record(latency=3.0, ok=True)
    assert a.rate == 50
