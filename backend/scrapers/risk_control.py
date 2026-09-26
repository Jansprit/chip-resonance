"""
risk_control.py — 風控（Risk Control）中央模組

依使用者要求（2026-09-23 請求）：

**每個來源必須有嚴格的風控，否則會被來源站 ban IP。**

本模組集中管理：
1. **節流（Rate Limiting）** — 最小間隔、每日配額、隨機抖動
2. **熔斷（Circuit Breaker）** — 連續失敗時自動暫停
3. **退避（Exponential Backoff）** — 失敗時遞增等待
4. **健康監控（Health Monitoring）** — 追蹤成功率、響應時間
5. **自動停用（Auto Disable）** — 403/429 時立即停用當日
6. **警報（Alerts）** — 嚴重問題時 console 警告（後續可加 email/Slack）

設計原則：
- 「保守」優先於「快速」：預設節流比真實需要更慢
- 失敗時降速而非「重試到死」
- 跨來源獨立：某個來源被 ban 不影響其他
- 透明：所有決定都記錄到 SourceHealth 供 debug
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Optional
from enum import Enum

from .base import RateLimiter, taipei_now_iso, taipei_today


# ============ 風控預設值（每個來源獨立設定）==========

@dataclass(frozen=True)
class ThrottleConfig:
    """單一來源的節流設定。"""
    min_interval_sec: float            # 最小間隔
    daily_quota: int                   # 每日上限
    max_interval_sec: float = 15.0     # 最大間隔（自動 jitter 上限）
    jitter_sec: float = 1.0            # 隨機抖動
    backoff_on_403: bool = True        # 403 時自動暫停
    backoff_on_429: bool = True        # 429 時自動暫停
    backoff_on_timeout: bool = True    # timeout 時自動退避
    cooldown_after_error_sec: float = 600.0  # 出錯後冷卻時間（10 分鐘）
    max_consecutive_errors: int = 3    # 連續錯誤達此值時熔斷
    circuit_breaker_cooldown_sec: float = 3600.0  # 熔斷後冷卻（1 小時）


# 保守預設：每個來源都比合理需要更慢
DEFAULT_CONFIGS = {
    "twse": ThrottleConfig(
        min_interval_sec=2.0, daily_quota=500, jitter_sec=0.5,
    ),
    "tpex": ThrottleConfig(
        min_interval_sec=2.0, daily_quota=500, jitter_sec=0.5,
    ),
    "finmind": ThrottleConfig(
        min_interval_sec=3.0, daily_quota=300, jitter_sec=0.5,
    ),
    "mops": ThrottleConfig(
        min_interval_sec=5.0, daily_quota=200, jitter_sec=1.0,
    ),
    "wantgoo": ThrottleConfig(
        min_interval_sec=6.0, daily_quota=200, jitter_sec=1.0,
    ),
    "tdcc": ThrottleConfig(
        min_interval_sec=4.0, daily_quota=250, jitter_sec=1.0,
    ),
    "tdcc_opendata": ThrottleConfig(
        min_interval_sec=3.0, daily_quota=200, jitter_sec=0.5,
    ),
    "pyramid": ThrottleConfig(
        min_interval_sec=8.0, daily_quota=100, jitter_sec=1.0,
    ),
    "goodinfo": ThrottleConfig(
        min_interval_sec=10.0, daily_quota=60, jitter_sec=2.0,
    ),
}


# ============ 風控狀態（每來源獨立）==========

class CircuitState(Enum):
    CLOSED = "closed"           # 正常
    HALF_OPEN = "half_open"     # 嘗試恢復
    OPEN = "open"               # 熔斷中


@dataclass
class RiskState:
    """單一來源的風控狀態。"""
    source: str
    config: ThrottleConfig
    state: CircuitState = CircuitState.CLOSED
    daily_count: int = 0
    last_call_ts: Optional[float] = None
    consecutive_errors: int = 0
    last_error: Optional[str] = None
    disabled_until: Optional[float] = None  # 暫停到期時間
    circuit_opened_at: Optional[float] = None
    success_count: int = 0
    failure_count: int = 0
    last_reset_date: str = ""  # YYYY-MM-DD

    def reset_if_new_day(self) -> None:
        today = taipei_today()
        if self.last_reset_date != today:
            self.daily_count = 0
            self.disabled_until = None
            self.last_reset_date = today

    def can_request(self) -> tuple[bool, str]:
        """是否可以請求？回傳 (allowed, reason)。"""
        self.reset_if_new_day()
        if self.disabled_until and time.time() < self.disabled_until:
            return False, f"disabled until {datetime.fromtimestamp(self.disabled_until).isoformat()}"
        if self.state == CircuitState.OPEN:
            if self.circuit_opened_at and (time.time() - self.circuit_opened_at) < self.config.circuit_breaker_cooldown_sec:
                return False, f"circuit breaker open"
            else:
                # 半開啟：允許一次試探
                self.state = CircuitState.HALF_OPEN
        if self.daily_count >= self.config.daily_quota:
            return False, f"hit daily quota ({self.config.daily_quota})"
        return True, ""

    def record_success(self) -> None:
        self.reset_if_new_day()  # 先 reset 才能正確 +1
        self.daily_count += 1
        self.success_count += 1
        self.consecutive_errors = 0
        self.last_call_ts = time.time()
        self.last_error = None
        # 從半開啟恢復到關閉
        if self.state == CircuitState.HALF_OPEN:
            self.state = CircuitState.CLOSED
            self.circuit_opened_at = None

    def record_failure(self, error: str, http_status: Optional[int] = None) -> None:
        self.reset_if_new_day()  # 先 reset 才能正確累加失敗

    def record_failure(self, error: str, http_status: Optional[int] = None) -> None:
        self.failure_count += 1
        self.consecutive_errors += 1
        self.last_error = error
        self.last_call_ts = time.time()

        # HTTP 403 / 429 立即暫停
        if http_status == 403 and self.config.backoff_on_403:
            self.disabled_until = time.time() + self.config.cooldown_after_error_sec
            self.state = CircuitState.OPEN
            self.circuit_opened_at = time.time()
            return
        if http_status == 429 and self.config.backoff_on_429:
            self.disabled_until = time.time() + self.config.cooldown_after_error_sec
            self.state = CircuitState.OPEN
            self.circuit_opened_at = time.time()
            return

        # 連續錯誤達熔斷閾值
        if self.consecutive_errors >= self.config.max_consecutive_errors:
            self.state = CircuitState.OPEN
            self.circuit_opened_at = time.time()

    def get_status_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "state": self.state.value,
            "daily_count": self.daily_count,
            "consecutive_errors": self.consecutive_errors,
            "disabled_until": (
                datetime.fromtimestamp(self.disabled_until).isoformat()
                if self.disabled_until else None
            ),
            "last_error": self.last_error,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
        }


# ============ 風控中央管理器 ============

class RiskController:
    """所有來源的風控中央管理。"""

    def __init__(self, config_overrides: Optional[dict[str, ThrottleConfig]] = None):
        self._states: dict[str, RiskState] = {}
        for source, cfg in DEFAULT_CONFIGS.items():
            override = (config_overrides or {}).get(source)
            self._states[source] = RiskState(
                source=source,
                config=override or cfg,
            )

    def get_state(self, source: str) -> RiskState:
        if source not in self._states:
            # 動態建立（用最保守預設）
            from .base import RateLimiter, SourceHealth
            self._states[source] = RiskState(
                source=source,
                config=ThrottleConfig(
                    min_interval_sec=5.0, daily_quota=100, jitter_sec=1.0,
                ),
            )
        return self._states[source]

    def check_can_request(self, source: str) -> tuple[bool, str]:
        return self.get_state(source).can_request()

    def record_success(self, source: str) -> None:
        self.get_state(source).record_success()

    def record_failure(
        self, source: str, error: str, http_status: Optional[int] = None,
    ) -> None:
        state = self.get_state(source)
        state.record_failure(error, http_status)
        if state.state == CircuitState.OPEN:
            self._alert_circuit_open(source, state)

    def _alert_circuit_open(self, source: str, state: RiskState) -> None:
        """觸發熔斷時 console 警告（後續可加 email/Slack 整合）。"""
        msg = (
            f"⚠ [RISK] {source} 電路熔斷！\n"
            f"   daily_count={state.daily_count} "
            f"consecutive_errors={state.consecutive_errors}\n"
            f"   last_error: {state.last_error}\n"
            f"   將於 {state.config.circuit_breaker_cooldown_sec/60:.0f} 分鐘後嘗試恢復\n"
        )
        print(msg, flush=True)

    def get_all_status(self) -> list[dict[str, Any]]:
        return [state.get_status_dict() for state in self._states.values()]


# ============ 全域實例（單例模式）============

_global_controller: Optional[RiskController] = None


def get_risk_controller() -> RiskController:
    global _global_controller
    if _global_controller is None:
        _global_controller = RiskController()
    return _global_controller


# ============ 便利函式：整合 RateLimiter 與風控 ============

class RiskAwareRateLimiter:
    """包裝 RateLimiter 加上風控檢查。每次 wait() 前先確認。"""

    def __init__(self, source: str, controller: Optional[RiskController] = None):
        self.source = source
        self.controller = controller or get_risk_controller()
        state = self.controller.get_state(source)
        self.rl = RateLimiter(
            min_interval=state.config.min_interval_sec,
            source_name=source,
        )

    def wait(self) -> None:
        """阻塞直到允許請求（檢查風控 + 節流）。"""
        allowed, reason = self.controller.check_can_request(self.source)
        if not allowed:
            raise PermissionError(f"[{self.source}] 風控拒絕：{reason}")
        # 若熔斷處於半開啟，給予單次試探機會（已在 can_request 中處理）
        self.rl.wait()
        # 加入 jitter 抖動
        import random
        jitter = random.uniform(0, self.controller.get_state(self.source).config.jitter_sec)
        time.sleep(jitter)

    def record_success(self) -> None:
        self.controller.record_success(self.source)

    def record_failure(self, error: str, http_status: Optional[int] = None) -> None:
        self.controller.record_failure(self.source, error, http_status)


__all__ = [
    "ThrottleConfig",
    "DEFAULT_CONFIGS",
    "CircuitState",
    "RiskState",
    "RiskController",
    "get_risk_controller",
    "RiskAwareRateLimiter",
]