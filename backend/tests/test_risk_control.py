"""
test_risk_control.py — Tests for the central risk control module

驗證：
- 每日配額計數正確
- 403/429 自動 disable
- 連續錯誤觸發熔斷
- 半開啟恢復邏輯
- 跨日重置
- 風控拒絕時拋出 PermissionError
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.scrapers.risk_control import (
    ThrottleConfig,
    CircuitState,
    RiskState,
    RiskController,
    RiskAwareRateLimiter,
)


def test_can_request_initial_state():
    """新建立的 source 應為 closed、可請求。"""
    rc = RiskController()
    state = rc.get_state("new_source")
    assert state.state == CircuitState.CLOSED
    assert state.daily_count == 0
    allowed, reason = state.can_request()
    assert allowed is True
    assert reason == ""


def test_record_success_increments_count():
    rc = RiskController()
    state = rc.get_state("test_source")
    for _ in range(5):
        state.record_success()
    assert state.daily_count == 5
    assert state.success_count == 5
    assert state.consecutive_errors == 0


def test_quota_blocks_after_exceeded():
    """daily_quota 達到後應拒絕請求。"""
    rc = RiskController()
    state = rc.get_state("test_source")
    state.config = ThrottleConfig(min_interval_sec=1.0, daily_quota=3)
    # 3 次成功
    for _ in range(3):
        state.record_success()
    allowed, reason = state.can_request()
    assert allowed is False
    assert "quota" in reason.lower()


def test_403_disables_source():
    """403 應自動暫停該來源。"""
    rc = RiskController()
    state = rc.get_state("test_403_source")
    state.config = ThrottleConfig(min_interval_sec=1.0, daily_quota=100, cooldown_after_error_sec=60)
    state.record_failure("Forbidden", http_status=403)
    assert state.disabled_until is not None
    allowed, reason = state.can_request()
    assert allowed is False
    # reason 可能是 "disabled until..." 或 "circuit breaker open"，都表示暫停
    assert "disabled" in reason.lower() or "circuit" in reason.lower()


def test_429_disables_source():
    """429 應自動暫停該來源。"""
    rc = RiskController()
    state = rc.get_state("test_429_source")
    state.config = ThrottleConfig(min_interval_sec=1.0, daily_quota=100, cooldown_after_error_sec=60)
    state.record_failure("Too Many Requests", http_status=429)
    assert state.disabled_until is not None
    allowed, _ = state.can_request()
    assert allowed is False


def test_circuit_breaker_opens_after_consecutive_errors():
    """達到 max_consecutive_errors 應開啟熔斷。"""
    rc = RiskController()
    state = rc.get_state("test_circuit_source")
    state.config = ThrottleConfig(
        min_interval_sec=1.0, daily_quota=100,
        max_consecutive_errors=3, circuit_breaker_cooldown_sec=60,
    )
    for _ in range(3):
        state.record_failure("error")
    assert state.state == CircuitState.OPEN
    assert state.consecutive_errors == 3
    allowed, reason = state.can_request()
    assert allowed is False
    assert "circuit" in reason.lower()


def test_half_open_recovers_on_success():
    """熔斷冷卻後半開啟，單次成功應完全恢復。"""
    rc = RiskController()
    state = rc.get_state("test_source")
    state.config = ThrottleConfig(
        min_interval_sec=1.0, daily_quota=100,
        max_consecutive_errors=3, circuit_breaker_cooldown_sec=0,  # 立即冷卻
    )
    for _ in range(3):
        state.record_failure("error")
    assert state.state == CircuitState.OPEN
    # 等冷卻時間過
    time.sleep(0.1)
    # 觸發 can_request（應進入半開啟）
    allowed, _ = state.can_request()
    assert state.state == CircuitState.HALF_OPEN
    # 單次成功應完全恢復
    state.record_success()
    assert state.state == CircuitState.CLOSED
    assert state.consecutive_errors == 0


def test_daily_reset():
    """daily_reset_if_new_day 應在隔日重置計數。"""
    rc = RiskController()
    state = rc.get_state("test_source")
    state.config = ThrottleConfig(min_interval_sec=1.0, daily_quota=100)
    state.daily_count = 50
    state.disabled_until = time.time() + 100
    state.last_reset_date = "2020-01-01"  # 假裝很久以前
    # 觸發 reset
    state.reset_if_new_day()
    assert state.daily_count == 0
    assert state.disabled_until is None
    assert state.last_reset_date != "2020-01-01"


def test_risk_aware_rate_limiter_raises_when_blocked():
    """RiskAwareRateLimiter 在熔斷時應拋 PermissionError。"""
    rc = RiskController()
    state = rc.get_state("test_source")
    state.config = ThrottleConfig(
        min_interval_sec=1.0, daily_quota=100,
        max_consecutive_errors=2, circuit_breaker_cooldown_sec=60,
    )
    for _ in range(2):
        state.record_failure("err")
    limiter = RiskAwareRateLimiter("test_source", controller=rc)
    try:
        limiter.wait()
        assert False, "應該拋 PermissionError"
    except PermissionError as e:
        assert "circuit" in str(e).lower() or "blocked" in str(e).lower()


def test_cross_source_independence():
    """一個 source 被 ban 不應影響其他 source。"""
    rc = RiskController()
    for _ in range(3):
        rc.get_state("source_a").record_failure("err", http_status=403)
    # source_b 仍可請求
    allowed, _ = rc.check_can_request("source_b")
    assert allowed is True


def test_status_dict_for_meta_json():
    """get_status_dict 應回傳乾淨 dict，可寫入 meta.json。"""
    rc = RiskController()
    state = rc.get_state("test_source")
    state.daily_count = 10
    state.failure_count = 2
    status = state.get_status_dict()
    assert status["source"] == "test_source"
    assert status["daily_count"] == 10
    assert status["state"] == "closed"
    assert "disabled_until" in status


if __name__ == "__main__":
    test_can_request_initial_state()
    print("PASS: test_can_request_initial_state")
    test_record_success_increments_count()
    print("PASS: test_record_success_increments_count")
    test_quota_blocks_after_exceeded()
    print("PASS: test_quota_blocks_after_exceeded")
    test_403_disables_source()
    print("PASS: test_403_disables_source")
    test_429_disables_source()
    print("PASS: test_429_disables_source")
    test_circuit_breaker_opens_after_consecutive_errors()
    print("PASS: test_circuit_breaker_opens_after_consecutive_errors")
    test_half_open_recovers_on_success()
    print("PASS: test_half_open_recovers_on_success")
    test_daily_reset()
    print("PASS: test_daily_reset")
    test_risk_aware_rate_limiter_raises_when_blocked()
    print("PASS: test_risk_aware_rate_limiter_raises_when_blocked")
    test_cross_source_independence()
    print("PASS: test_cross_source_independence")
    test_status_dict_for_meta_json()
    print("PASS: test_status_dict_for_meta_json")
    print("\nAll 11 risk_control tests passed.")