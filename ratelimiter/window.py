"""
ratelimiter.window
------------------
Sliding window counter implementation for rate limiting.
"""

import time
import threading
from collections import deque
from enum import Enum
from typing import Deque, Dict, Optional, Tuple


class WindowType(str, Enum):
    SECOND = "second"
    MINUTE = "minute"
    HOUR   = "hour"
    DAY    = "day"


WINDOW_SECONDS: Dict[str, int] = {
    WindowType.SECOND: 1,
    WindowType.MINUTE: 60,
    WindowType.HOUR:   3600,
    WindowType.DAY:    86400,
}


class SlidingWindow:
    """
    Thread-safe sliding window rate limiter.

    Tracks call timestamps in a deque. On each call, evicts timestamps
    older than the window, then checks if the count is within the limit.

    Parameters
    ----------
    limit : int
        Maximum number of calls allowed per window.
    window : WindowType | str
        Time window: "second", "minute", "hour", "day".
    burst : int
        Extra calls allowed as a burst above the base limit.
        Total allowed = limit + burst.
    key : str
        Identifier for this limiter (used for multi-key scenarios).
    """

    def __init__(
        self,
        limit: int,
        window: str = WindowType.SECOND,
        burst: int = 0,
        key: str = "default",
    ):
        if limit < 1:
            raise ValueError("limit must be >= 1")
        if burst < 0:
            raise ValueError("burst must be >= 0")

        self.limit = limit
        self.burst = burst
        self.total_limit = limit + burst
        self.window_seconds = WINDOW_SECONDS[window]
        self.window = window
        self.key = key

        self._timestamps: Deque[float] = deque()
        self._lock = threading.Lock()
        self._total_calls = 0
        self._rejected_calls = 0

    def _evict_old(self, now: float):
        """Remove timestamps outside the current window."""
        cutoff = now - self.window_seconds
        while self._timestamps and self._timestamps[0] <= cutoff:
            self._timestamps.popleft()

    def check(self) -> Tuple[bool, int, float]:
        """
        Check if a call is allowed without consuming a slot.

        Returns
        -------
        (allowed, remaining, retry_after)
          allowed     : True if the call would be allowed
          remaining   : How many more calls are allowed in this window
          retry_after : Seconds to wait before retrying (0 if allowed)
        """
        with self._lock:
            now = time.monotonic()
            self._evict_old(now)
            count = len(self._timestamps)
            allowed = count < self.total_limit
            remaining = max(0, self.total_limit - count - (1 if allowed else 0))
            if allowed:
                retry_after = 0.0
            else:
                # Time until the oldest call exits the window
                retry_after = self.window_seconds - (now - self._timestamps[0])
            return allowed, remaining, retry_after

    def acquire(self) -> Tuple[bool, int, float]:
        """
        Try to consume a rate limit slot.

        Returns same tuple as check(), but also records the call if allowed.
        """
        with self._lock:
            now = time.monotonic()
            self._evict_old(now)
            self._total_calls += 1
            count = len(self._timestamps)

            if count < self.total_limit:
                self._timestamps.append(now)
                remaining = self.total_limit - count - 1
                return True, remaining, 0.0
            else:
                self._rejected_calls += 1
                retry_after = self.window_seconds - (now - self._timestamps[0])
                return False, 0, max(0.0, retry_after)

    def reset(self):
        """Clear all recorded timestamps."""
        with self._lock:
            self._timestamps.clear()

    def stats(self) -> dict:
        """Return usage statistics."""
        with self._lock:
            now = time.monotonic()
            self._evict_old(now)
            return {
                "key": self.key,
                "window": self.window,
                "limit": self.limit,
                "burst": self.burst,
                "total_limit": self.total_limit,
                "current_count": len(self._timestamps),
                "remaining": max(0, self.total_limit - len(self._timestamps)),
                "total_calls": self._total_calls,
                "rejected_calls": self._rejected_calls,
            }


class MultiKeySlidingWindow:
    """
    A collection of SlidingWindow instances keyed by an arbitrary string.
    Useful for per-user or per-IP rate limiting.
    """

    def __init__(self, limit: int, window: str, burst: int = 0):
        self.limit = limit
        self.window = window
        self.burst = burst
        self._windows: Dict[str, SlidingWindow] = {}
        self._lock = threading.Lock()

    def _get_or_create(self, key: str) -> SlidingWindow:
        with self._lock:
            if key not in self._windows:
                self._windows[key] = SlidingWindow(
                    self.limit, self.window, self.burst, key=key
                )
            return self._windows[key]

    def acquire(self, key: str) -> Tuple[bool, int, float]:
        return self._get_or_create(key).acquire()

    def check(self, key: str) -> Tuple[bool, int, float]:
        return self._get_or_create(key).check()

    def reset(self, key: str):
        self._get_or_create(key).reset()

    def stats(self, key: str) -> dict:
        return self._get_or_create(key).stats()

    def all_stats(self) -> Dict[str, dict]:
        with self._lock:
            keys = list(self._windows.keys())
        return {k: self._windows[k].stats() for k in keys}
