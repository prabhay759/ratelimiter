"""
ratelimiter.core
----------------
RateLimiter class and @rate_limit decorator.
"""

import asyncio
import functools
import time
from typing import Any, Callable, Dict, List, Optional, Union

from .window import SlidingWindow, MultiKeySlidingWindow, WindowType, WINDOW_SECONDS


class RateLimitExceeded(Exception):
    """Raised when a rate limit is exceeded."""

    def __init__(self, message: str, retry_after: float = 0.0, key: str = ""):
        super().__init__(message)
        self.retry_after = retry_after
        self.key = key

    def __str__(self):
        msg = super().__str__()
        if self.retry_after:
            msg += f" (retry after {self.retry_after:.2f}s)"
        return msg


class RateLimiter:
    """
    Rate limiter with sliding window, burst allowance, and multi-key support.

    Supports multiple windows simultaneously (e.g. 10/sec AND 100/min).

    Parameters
    ----------
    limit : int
        Max calls per window.
    window : str
        Time window: "second", "minute", "hour", "day".
    burst : int
        Extra calls allowed above limit as burst. Default: 0.
    key_func : callable, optional
        Function that extracts a rate limit key from function args.
        Enables per-user/per-IP limiting.
        Example: key_func=lambda args, kwargs: kwargs.get("user_id")
    raise_on_limit : bool
        If True (default), raise RateLimitExceeded when limit hit.
        If False, block/wait until a slot is available.
    additional_windows : list[dict]
        Extra windows, e.g. [{"limit": 100, "window": "minute"}].

    Examples
    --------
    >>> limiter = RateLimiter(limit=10, window="second", burst=5)

    >>> @limiter
    ... def call_api():
    ...     return requests.get(url)

    >>> # Per-user limiting
    >>> limiter = RateLimiter(10, "minute", key_func=lambda a, kw: kw["user_id"])
    """

    def __init__(
        self,
        limit: int,
        window: str = WindowType.SECOND,
        burst: int = 0,
        key_func: Optional[Callable] = None,
        raise_on_limit: bool = True,
        additional_windows: Optional[List[dict]] = None,
    ):
        self.limit = limit
        self.window = window
        self.burst = burst
        self.key_func = key_func
        self.raise_on_limit = raise_on_limit

        # Primary window
        if key_func:
            self._primary = MultiKeySlidingWindow(limit, window, burst)
        else:
            self._primary = SlidingWindow(limit, window, burst)

        # Additional windows (e.g. also enforce per-minute)
        self._extra: List[Union[SlidingWindow, MultiKeySlidingWindow]] = []
        for w in (additional_windows or []):
            lim = w.get("limit", limit)
            win = w.get("window", window)
            bst = w.get("burst", 0)
            if key_func:
                self._extra.append(MultiKeySlidingWindow(lim, win, bst))
            else:
                self._extra.append(SlidingWindow(lim, win, bst))

    def _get_key(self, args, kwargs) -> str:
        if self.key_func:
            return str(self.key_func(args, kwargs))
        return "default"

    def _acquire_all(self, key: str):
        """Try to acquire slots on all windows. Raises or waits on limit."""
        all_windows = [self._primary] + self._extra

        for win in all_windows:
            if isinstance(win, MultiKeySlidingWindow):
                allowed, remaining, retry_after = win.acquire(key)
            else:
                allowed, remaining, retry_after = win.acquire()

            if not allowed:
                if self.raise_on_limit:
                    raise RateLimitExceeded(
                        f"Rate limit exceeded: {win.limit}/{win.window}",
                        retry_after=retry_after,
                        key=key,
                    )
                else:
                    # Block until slot available
                    time.sleep(retry_after + 0.01)
                    # Retry once
                    if isinstance(win, MultiKeySlidingWindow):
                        allowed, _, _ = win.acquire(key)
                    else:
                        allowed, _, _ = win.acquire()
                    if not allowed:
                        raise RateLimitExceeded(
                            f"Rate limit exceeded after waiting: {win.limit}/{win.window}",
                            retry_after=0,
                            key=key,
                        )

    async def _acquire_all_async(self, key: str):
        """Async version of _acquire_all."""
        all_windows = [self._primary] + self._extra

        for win in all_windows:
            if isinstance(win, MultiKeySlidingWindow):
                allowed, remaining, retry_after = win.acquire(key)
            else:
                allowed, remaining, retry_after = win.acquire()

            if not allowed:
                if self.raise_on_limit:
                    raise RateLimitExceeded(
                        f"Rate limit exceeded: {win.limit}/{win.window}",
                        retry_after=retry_after,
                        key=key,
                    )
                else:
                    await asyncio.sleep(retry_after + 0.01)
                    if isinstance(win, MultiKeySlidingWindow):
                        allowed, _, _ = win.acquire(key)
                    else:
                        allowed, _, _ = win.acquire()
                    if not allowed:
                        raise RateLimitExceeded(
                            f"Rate limit exceeded after waiting: {win.limit}/{win.window}",
                            key=key,
                        )

    def __call__(self, func: Callable) -> Callable:
        """Use as decorator: @limiter or @limiter()"""
        if asyncio.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                key = self._get_key(args, kwargs)
                await self._acquire_all_async(key)
                return await func(*args, **kwargs)
            return async_wrapper
        else:
            @functools.wraps(func)
            def sync_wrapper(*args, **kwargs):
                key = self._get_key(args, kwargs)
                self._acquire_all(key)
                return func(*args, **kwargs)
            return sync_wrapper

    def check(self, key: str = "default") -> dict:
        """
        Check current rate limit status without consuming a slot.

        Returns dict with: allowed, remaining, retry_after.
        """
        if isinstance(self._primary, MultiKeySlidingWindow):
            allowed, remaining, retry_after = self._primary.check(key)
        else:
            allowed, remaining, retry_after = self._primary.check()
        return {"allowed": allowed, "remaining": remaining, "retry_after": retry_after}

    def reset(self, key: str = "default"):
        """Reset the rate limit counter for a key."""
        if isinstance(self._primary, MultiKeySlidingWindow):
            self._primary.reset(key)
            for w in self._extra:
                w.reset(key)
        else:
            self._primary.reset()
            for w in self._extra:
                w.reset()

    def stats(self, key: str = "default") -> dict:
        """Return usage statistics."""
        if isinstance(self._primary, MultiKeySlidingWindow):
            return self._primary.stats(key)
        return self._primary.stats()


def rate_limit(
    limit: int,
    window: str = WindowType.SECOND,
    burst: int = 0,
    key_func: Optional[Callable] = None,
    raise_on_limit: bool = True,
    additional_windows: Optional[List[dict]] = None,
) -> Callable:
    """
    Functional decorator factory for rate limiting.

    Usage
    -----
    @rate_limit(10, "second", burst=5)
    def my_func(): ...

    @rate_limit(100, "minute", key_func=lambda a, kw: kw["user_id"])
    def api_call(user_id): ...
    """
    limiter = RateLimiter(
        limit=limit,
        window=window,
        burst=burst,
        key_func=key_func,
        raise_on_limit=raise_on_limit,
        additional_windows=additional_windows,
    )
    return limiter
