"""
Tests for ratelimiter.
Run with: pytest tests/ -v
"""

import asyncio
import time
import threading
import pytest

from ratelimiter import RateLimiter, RateLimitExceeded, rate_limit
from ratelimiter.window import SlidingWindow, MultiKeySlidingWindow, WindowType


# ── SlidingWindow ─────────────────────────────────────────────────────────────

class TestSlidingWindow:
    def test_allows_up_to_limit(self):
        w = SlidingWindow(3, "second")
        for _ in range(3):
            allowed, _, _ = w.acquire()
            assert allowed

    def test_blocks_over_limit(self):
        w = SlidingWindow(3, "second")
        for _ in range(3):
            w.acquire()
        allowed, _, retry_after = w.acquire()
        assert not allowed
        assert retry_after > 0

    def test_burst_extends_limit(self):
        w = SlidingWindow(3, "second", burst=2)
        for _ in range(5):
            allowed, _, _ = w.acquire()
            assert allowed
        allowed, _, _ = w.acquire()
        assert not allowed

    def test_remaining_decreases(self):
        w = SlidingWindow(5, "second")
        _, r1, _ = w.acquire()
        _, r2, _ = w.acquire()
        assert r2 == r1 - 1

    def test_reset_clears_window(self):
        w = SlidingWindow(2, "second")
        w.acquire(); w.acquire()
        allowed, _, _ = w.acquire()
        assert not allowed
        w.reset()
        allowed, _, _ = w.acquire()
        assert allowed

    def test_sliding_window_expires(self):
        w = SlidingWindow(2, "second")
        w.acquire(); w.acquire()
        time.sleep(1.1)
        allowed, _, _ = w.acquire()
        assert allowed

    def test_invalid_limit_raises(self):
        with pytest.raises(ValueError):
            SlidingWindow(0, "second")

    def test_invalid_burst_raises(self):
        with pytest.raises(ValueError):
            SlidingWindow(5, "second", burst=-1)

    def test_stats(self):
        w = SlidingWindow(10, "minute")
        w.acquire(); w.acquire()
        s = w.stats()
        assert s["total_calls"] == 2
        assert s["current_count"] == 2
        assert s["limit"] == 10

    def test_check_does_not_consume(self):
        w = SlidingWindow(3, "second")
        for _ in range(3):
            w.check()
        allowed, _, _ = w.acquire()
        assert allowed  # still allowed since check() didn't consume


# ── MultiKeySlidingWindow ────────────────────────────────────────────────────

class TestMultiKeySlidingWindow:
    def test_separate_limits_per_key(self):
        mw = MultiKeySlidingWindow(2, "second")
        mw.acquire("user1"); mw.acquire("user1")
        allowed, _, _ = mw.acquire("user1")
        assert not allowed
        # user2 should be unaffected
        allowed, _, _ = mw.acquire("user2")
        assert allowed

    def test_reset_specific_key(self):
        mw = MultiKeySlidingWindow(2, "second")
        mw.acquire("u"); mw.acquire("u")
        mw.reset("u")
        allowed, _, _ = mw.acquire("u")
        assert allowed

    def test_all_stats(self):
        mw = MultiKeySlidingWindow(5, "second")
        mw.acquire("a"); mw.acquire("b"); mw.acquire("a")
        stats = mw.all_stats()
        assert "a" in stats
        assert "b" in stats
        assert stats["a"]["total_calls"] == 2


# ── RateLimiter ───────────────────────────────────────────────────────────────

class TestRateLimiter:
    def test_decorator_allows_calls(self):
        limiter = RateLimiter(10, "second")
        @limiter
        def fn(): return 42
        assert fn() == 42

    def test_decorator_blocks_over_limit(self):
        limiter = RateLimiter(3, "second")
        @limiter
        def fn(): return 1
        fn(); fn(); fn()
        with pytest.raises(RateLimitExceeded):
            fn()

    def test_burst_allows_extra(self):
        limiter = RateLimiter(3, "second", burst=2)
        @limiter
        def fn(): return 1
        for _ in range(5):
            fn()
        with pytest.raises(RateLimitExceeded):
            fn()

    def test_raise_on_limit_false_waits(self):
        limiter = RateLimiter(2, "second", raise_on_limit=False)
        @limiter
        def fn(): return 1
        fn(); fn()
        start = time.monotonic()
        fn()  # Should wait instead of raising
        elapsed = time.monotonic() - start
        assert elapsed >= 0.05  # waited

    def test_key_func_per_user(self):
        limiter = RateLimiter(2, "second",
                              key_func=lambda a, kw: kw.get("user_id"))
        @limiter
        def fn(user_id): return user_id
        fn(user_id="alice"); fn(user_id="alice")
        with pytest.raises(RateLimitExceeded):
            fn(user_id="alice")
        # bob unaffected
        assert fn(user_id="bob") == "bob"

    def test_additional_windows(self):
        limiter = RateLimiter(
            5, "second",
            additional_windows=[{"limit": 3, "window": "second"}]
        )
        @limiter
        def fn(): return 1
        fn(); fn(); fn()
        with pytest.raises(RateLimitExceeded):
            fn()

    def test_check_status(self):
        limiter = RateLimiter(5, "second")
        status = limiter.check()
        assert status["allowed"] is True
        assert status["remaining"] == 5

    def test_reset(self):
        limiter = RateLimiter(2, "second")
        @limiter
        def fn(): return 1
        fn(); fn()
        limiter.reset()
        fn()  # Should work after reset

    def test_stats(self):
        limiter = RateLimiter(10, "second")
        @limiter
        def fn(): return 1
        fn(); fn()
        s = limiter.stats()
        assert s["total_calls"] == 2

    def test_thread_safety(self):
        limiter = RateLimiter(50, "second")
        results = []
        @limiter
        def fn(): return 1

        def worker():
            try:
                results.append(fn())
            except RateLimitExceeded:
                results.append(None)

        threads = [threading.Thread(target=worker) for _ in range(30)]
        for t in threads: t.start()
        for t in threads: t.join()
        assert len(results) == 30


# ── Async support ─────────────────────────────────────────────────────────────

class TestAsync:
    def test_async_allows_calls(self):
        limiter = RateLimiter(10, "second")
        @limiter
        async def fn(): return "ok"
        assert asyncio.run(fn()) == "ok"

    def test_async_blocks_over_limit(self):
        limiter = RateLimiter(3, "second")
        @limiter
        async def fn(): return 1

        async def run():
            await fn(); await fn(); await fn()
            with pytest.raises(RateLimitExceeded):
                await fn()

        asyncio.run(run())

    def test_async_burst(self):
        limiter = RateLimiter(2, "second", burst=3)
        @limiter
        async def fn(): return 1

        async def run():
            for _ in range(5):
                await fn()
            with pytest.raises(RateLimitExceeded):
                await fn()

        asyncio.run(run())


# ── rate_limit decorator factory ─────────────────────────────────────────────

class TestRateLimitDecorator:
    def test_basic(self):
        @rate_limit(5, "second")
        def fn(): return "done"
        assert fn() == "done"

    def test_with_burst(self):
        @rate_limit(2, "second", burst=2)
        def fn(): return 1
        for _ in range(4):
            fn()
        with pytest.raises(RateLimitExceeded):
            fn()

    def test_retry_after_in_exception(self):
        @rate_limit(1, "second")
        def fn(): return 1
        fn()
        try:
            fn()
        except RateLimitExceeded as e:
            assert e.retry_after > 0


# ── RateLimitExceeded ────────────────────────────────────────────────────────

class TestRateLimitExceeded:
    def test_str_includes_retry_after(self):
        e = RateLimitExceeded("limit hit", retry_after=1.5)
        assert "1.5" in str(e)

    def test_attributes(self):
        e = RateLimitExceeded("msg", retry_after=2.0, key="user_1")
        assert e.retry_after == 2.0
        assert e.key == "user_1"
