# ratelimiter

> Decorator-based rate limiter for Python — sliding window algorithm, burst allowance, per-key limits, multiple windows, and full async support. Zero dependencies.

[![PyPI version](https://img.shields.io/pypi/v/ratelimiter.svg)](https://pypi.org/project/ratelimiter/)
[![Python](https://img.shields.io/pypi/pyversions/ratelimiter.svg)](https://pypi.org/project/ratelimiter/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## Installation

```bash
pip install ratelimiter
```

No dependencies. Requires Python 3.8+.

---

## Quick Start

```python
from ratelimiter import rate_limit, RateLimitExceeded

@rate_limit(10, "second")
def call_api():
    return requests.get("https://api.example.com/data")
```

---

## Usage

### Basic Limiting

```python
from ratelimiter import RateLimiter, rate_limit

# As a reusable limiter object
limiter = RateLimiter(limit=10, window="second")

@limiter
def fetch(): ...

# As a one-off decorator
@rate_limit(100, "minute")
def send_email(): ...
```

### Windows

| Window | Value |
|---|---|
| `"second"` | 1 second |
| `"minute"` | 60 seconds |
| `"hour"` | 3600 seconds |
| `"day"` | 86400 seconds |

### Burst Allowance

Allow a temporary burst above the base limit:

```python
@rate_limit(10, "second", burst=5)
def fn(): ...
# Allows up to 15 calls/second in bursts, then enforces 10/sec
```

### Multiple Windows

Enforce multiple limits simultaneously:

```python
limiter = RateLimiter(
    limit=10, window="second",
    additional_windows=[
        {"limit": 100, "window": "minute"},
        {"limit": 1000, "window": "day"},
    ]
)

@limiter
def api_call(): ...
```

### Per-Key Rate Limiting (per user/IP)

```python
limiter = RateLimiter(
    limit=10, window="minute",
    key_func=lambda args, kwargs: kwargs.get("user_id")
)

@limiter
def create_post(user_id, content): ...

create_post(user_id="alice", content="hello")  # alice's limit
create_post(user_id="bob", content="hi")       # bob's own limit
```

### Async Support

Works transparently with `async def`:

```python
@rate_limit(50, "second")
async def async_fetch(url):
    async with aiohttp.ClientSession() as s:
        return await s.get(url)
```

### Wait Instead of Raise

```python
limiter = RateLimiter(5, "second", raise_on_limit=False)

@limiter
def fn(): ...
# Automatically waits for a slot instead of raising
```

### Handling Exceptions

```python
from ratelimiter import RateLimitExceeded

try:
    call_api()
except RateLimitExceeded as e:
    print(f"Limited! Retry after {e.retry_after:.2f}s")
    time.sleep(e.retry_after)
```

### Introspection

```python
# Check status without consuming a slot
status = limiter.check()
# {"allowed": True, "remaining": 8, "retry_after": 0}

# Usage stats
stats = limiter.stats()
# {"total_calls": 42, "rejected_calls": 3, "current_count": 7, ...}

# Reset
limiter.reset()
```

---

## CLI Tool

Test any rate limit configuration interactively:

```bash
ratelimiter-test --limit 5 --window second
ratelimiter-test --limit 10 --window minute --burst 3 --calls 15
```

Output:
```
  Call   1/15  ✅ ALLOWED  remaining=9  [█████████░]
  Call   2/15  ✅ ALLOWED  remaining=8  [████████░░]
  ...
  Call  11/15  ❌ BLOCKED  (retry in 0.823s)
```

---

## API Reference

### `RateLimiter`

```python
RateLimiter(
    limit,                  # Max calls per window
    window="second",        # "second", "minute", "hour", "day"
    burst=0,                # Extra burst calls above limit
    key_func=None,          # Callable(args, kwargs) -> str for per-key limiting
    raise_on_limit=True,    # False = wait instead of raise
    additional_windows=[],  # [{"limit": N, "window": "..."}]
)
```

| Method | Description |
|---|---|
| `__call__(func)` | Use as decorator |
| `check(key)` | Check status without consuming |
| `reset(key)` | Reset counter |
| `stats(key)` | Get usage statistics |

### `rate_limit`

Functional decorator factory — same parameters as `RateLimiter`.

---

## Running Tests

```bash
pip install pytest
pytest tests/ -v
```

---

## License

MIT © prabhay759
