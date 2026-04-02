"""
ratelimiter — Decorator-based rate limiter with sliding window,
burst allowance, per-window limits, and async support.
"""

from .core import RateLimiter, RateLimitExceeded, rate_limit
from .window import WindowType

__all__ = ["RateLimiter", "RateLimitExceeded", "rate_limit", "WindowType"]
__version__ = "1.0.0"
__author__ = "prabhay759"
