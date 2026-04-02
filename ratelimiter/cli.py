"""
ratelimiter CLI
---------------
Test your rate limit config interactively.

Usage:
    ratelimiter-test --limit 5 --window second
    ratelimiter-test --limit 10 --window minute --burst 3 --calls 15
"""

import argparse
import time
import sys

from .window import SlidingWindow, WindowType


def main():
    parser = argparse.ArgumentParser(
        prog="ratelimiter-test",
        description="Test a rate limit configuration interactively.",
    )
    parser.add_argument("--limit", "-l", type=int, required=True, help="Max calls per window")
    parser.add_argument("--window", "-w", default="second",
                        choices=["second", "minute", "hour", "day"],
                        help="Time window (default: second)")
    parser.add_argument("--burst", "-b", type=int, default=0,
                        help="Burst allowance above limit (default: 0)")
    parser.add_argument("--calls", "-c", type=int, default=None,
                        help="Number of calls to simulate (default: limit+burst+3)")
    parser.add_argument("--delay", "-d", type=float, default=0.05,
                        help="Delay between simulated calls in seconds (default: 0.05)")
    args = parser.parse_args()

    total_calls = args.calls or (args.limit + args.burst + 3)
    window = SlidingWindow(args.limit, args.window, args.burst)

    print(f"\n{'='*55}")
    print(f"  ratelimiter-test")
    print(f"  limit={args.limit}/{args.window}  burst={args.burst}  "
          f"total_allowed={args.limit + args.burst}")
    print(f"  Simulating {total_calls} calls with {args.delay}s delay each")
    print(f"{'='*55}\n")

    allowed_count = 0
    rejected_count = 0

    for i in range(1, total_calls + 1):
        allowed, remaining, retry_after = window.acquire()
        status = "✅ ALLOWED" if allowed else f"❌ BLOCKED  (retry in {retry_after:.3f}s)"
        bar = "█" * remaining + "░" * max(0, args.limit + args.burst - remaining)
        print(f"  Call {i:>3}/{total_calls}  {status}  remaining={remaining}  [{bar}]")
        if allowed:
            allowed_count += 1
        else:
            rejected_count += 1
        time.sleep(args.delay)

    print(f"\n{'─'*55}")
    stats = window.stats()
    print(f"  ✅ Allowed:  {allowed_count}")
    print(f"  ❌ Rejected: {rejected_count}")
    print(f"  📊 Total calls tracked in window: {stats['current_count']}")
    print(f"{'='*55}\n")


if __name__ == "__main__":
    main()
