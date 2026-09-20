"""
test_rate_limiter.py — 驗證節流閥的最小間隔保證

對 RateLimiter 連發 N 次呼叫，記錄每兩次之間的真實間隔，
確保**沒有任何一對**間隔小於 min_interval。
"""

from __future__ import annotations

import time
from pathlib import Path
import sys

# 允許從 tests/ 目錄執行
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scrapers.base import RateLimiter  # noqa: E402


def test_no_call_below_min_interval():
    """連發 10 次 wait()，最小間隔不應低於 min_interval。"""
    min_interval = 0.5  # 用最小允許值以加速測試
    rl = RateLimiter(min_interval=min_interval, source_name="test")

    timestamps = []
    for _ in range(10):
        rl.wait()
        timestamps.append(time.monotonic())

    # 任兩次間隔 < min_interval 就失敗（扣掉一點容差給浮點誤差）
    violations = []
    for i in range(1, len(timestamps)):
        gap = timestamps[i] - timestamps[i - 1]
        if gap < min_interval - 0.05:  # 50ms 容差
            violations.append((i, gap))

    assert not violations, (
        f"RateLimiter violated min_interval {min_interval}s "
        f"on {len(violations)} call(s): {violations[:3]}"
    )


def test_constructor_rejects_too_low_interval():
    """min_interval < 0.5 應拋 ValueError（保護站點）。"""
    import pytest
    with pytest.raises(ValueError):
        RateLimiter(min_interval=0.1)


def test_thread_safe_under_concurrent_calls():
    """多執行緒同時呼叫 wait()，所有實際間隔都應 ≥ min_interval。"""
    import threading

    min_interval = 0.5
    rl = RateLimiter(min_interval=min_interval, source_name="concurrent-test")

    timestamps = []
    lock = threading.Lock()

    def worker():
        for _ in range(5):
            rl.wait()
            t = time.monotonic()
            with lock:
                timestamps.append(t)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    timestamps.sort()
    violations = []
    for i in range(1, len(timestamps)):
        gap = timestamps[i] - timestamps[i - 1]
        if gap < min_interval - 0.05:
            violations.append((i, gap))

    assert not violations, (
        f"Concurrent RateLimiter had {len(violations)} interval violations"
    )


if __name__ == "__main__":
    test_no_call_below_min_interval()
    print("PASS: test_no_call_below_min_interval")
    test_constructor_rejects_too_low_interval()
    print("PASS: test_constructor_rejects_too_low_interval")
    test_thread_safe_under_concurrent_calls()
    print("PASS: test_thread_safe_under_concurrent_calls")
    print("\nAll 3 tests passed.")