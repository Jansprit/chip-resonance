"""
scrapers/base.py — 共用基礎模組

提供：
- RateLimiter：每次請求的最低時間間隔（單一來源單執行緒）
- RetryPolicy：指數退避重試策略
- SourceHealth：追蹤單一來源的當日請求次數、停用狀態
- HttpClient：包裝 requests，注入 rate limit 與 retry 邏輯
- 共通常數：User-Agent、合理預設 timeout

設計約束（請勿繞過）：
1. RateLimiter 必須在**任何**對外請求前呼叫 wait()
2. 對同一 source 的請求必須共用同一個 RateLimiter 實例
3. 失敗時 RetryPolicy 會 sleep 至少 60s，請勿降低
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, date
from pathlib import Path
from typing import Any, Callable, Optional

import requests

# ============ 常數 ============

# 用來自 GitHub Actions 的官方 IP 沒問題；這組 User-Agent 是公開的 GitHub Action runner。
# 真實使用時可考慮輪換多個常見的 User-Agent，避免被針對性 ban。
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (compatible; ChipResonanceBot/1.0; "
    "+https://github.com/Jansprit/chip-resonance)"
)

DEFAULT_TIMEOUT = 30  # seconds

# 預設每日 UTC offset +8 的台北時區，方便跨日計算
# 使用 taipei_now_iso() / taipei_today() 函式取得當地時間


# ============ 節流閥 ============

class RateLimiter:
    """
    單一來源的節流閥，確保連續請求之間至少有 min_interval 秒。

    使用方式：
        rl = RateLimiter(min_interval=3.0)
        for url in urls:
            rl.wait()                       # 阻塞直到允許發出請求
            response = requests.get(url)

    Thread-safe：若多執行緒呼叫 wait()，會序列排隊。

    不要繞過 wait()，這是保護站點與自己 IP 的唯一手段。
    """

    def __init__(self, min_interval: float, source_name: str = "unknown"):
        if min_interval < 0.5:
            raise ValueError(
                f"min_interval={min_interval}s 太低，禁止低於 0.5s "
                f"以免對來源站點造成負擔"
            )
        self.min_interval = float(min_interval)
        self.source_name = source_name
        self._lock = threading.Lock()
        self._last_call_ts: Optional[float] = None

    def wait(self) -> None:
        """阻塞直到距離上次呼叫至少 min_interval 秒。"""
        with self._lock:
            now = time.monotonic()
            if self._last_call_ts is not None:
                elapsed = now - self._last_call_ts
                if elapsed < self.min_interval:
                    sleep_for = self.min_interval - elapsed
                    # 加一點隨機抖動，避免週期性 fingerprint
                    sleep_for += float(os.environ.get("RL_JITTER", "0.5"))
                    time.sleep(sleep_for)
            self._last_call_ts = time.monotonic()


# ============ 退避策略 ============

@dataclass(frozen=True)
class RetryPolicy:
    """
    指數退避重試：第 n 次失敗後 sleep schedule[n-1] 秒再試。

    預設：最多 3 次，間隔 60s / 300s（5 分鐘）。總計最長 sleep 6 分鐘。
    """

    max_retries: int = 3
    schedule: tuple = (60, 300, 900)  # seconds

    def sleep_for_attempt(self, attempt: int) -> float:
        """回傳第 attempt 次（從 1 開始）失敗後應 sleep 幾秒。"""
        if attempt < 1 or attempt > len(self.schedule):
            return 0.0
        return self.schedule[attempt - 1]


# ============ 來源健康狀態 ============

@dataclass
class SourceHealth:
    """
    追蹤單一資料源的當日狀態：累計請求次數、最後成功時間、被停用原因。

    每天 00:00（台北時間）會自動 reset count。
    """

    source_name: str
    daily_quota: int
    count: int = 0
    disabled_reason: Optional[str] = None
    last_success_ts: Optional[float] = None
    last_error: Optional[str] = None

    def reset_if_new_day(self) -> None:
        today = date.today().isoformat()
        if not hasattr(self, "_last_date"):
            self._last_date = today
            return
        if self._last_date != today:
            self.count = 0
            self.disabled_reason = None
            self._last_date = today

    def can_request(self) -> bool:
        self.reset_if_new_day()
        if self.disabled_reason:
            return False
        if self.count >= self.daily_quota:
            self.disabled_reason = f"hit daily quota ({self.daily_quota})"
            return False
        return True

    def record_success(self) -> None:
        self.last_success_ts = time.time()
        self.count += 1
        self.last_error = None

    def record_failure(self, error: str, *, disable: bool = False) -> None:
        self.last_error = error
        if disable:
            self.disabled_reason = error


# ============ HTTP 客戶端 ============

class HttpClient:
    """
    包裝 requests，加入 RateLimiter 與 RetryPolicy。

    用法：
        client = HttpClient(
            rate_limiter=RateLimiter(min_interval=3.0, source_name="twse"),
            retry=RetryPolicy(),
            health=SourceHealth("twse", daily_quota=500),
        )

        data = client.get_json("https://openapi.twse.com.tw/v1/...")
        # 或自訂錯誤處理
        data = client.fetch(url, on_403="disable_source")
    """

    def __init__(
        self,
        rate_limiter: RateLimiter,
        health: SourceHealth,
        retry: RetryPolicy = RetryPolicy(),
        user_agent: str = DEFAULT_USER_AGENT,
        timeout: int = DEFAULT_TIMEOUT,
    ):
        self.rl = rate_limiter
        self.health = health
        self.retry = retry
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": user_agent,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-TW,zh;q=0.9",
        })
        self.timeout = timeout

    def get_json(self, url: str, **kwargs) -> Any:
        """GET 並 parse JSON。失敗時拋例外。"""
        response = self._fetch_with_retry(url, **kwargs)
        return response.json()

    def _fetch_with_retry(self, url: str, **kwargs) -> requests.Response:
        """執行 GET 含節流、退避、重試。"""
        last_error = None

        for attempt in range(1, self.retry.max_retries + 2):  # initial + retries
            if not self.health.can_request():
                raise SourceDisabledError(
                    f"Source {self.health.source_name} disabled: "
                    f"{self.health.disabled_reason}"
                )

            try:
                self.rl.wait()
                response = self.session.get(url, timeout=self.timeout, **kwargs)

                # 429 (rate limit) / 403 (forbidden) — 立即停用來源，不重試
                if response.status_code in (403, 429):
                    err = f"HTTP {response.status_code} (likely banned / rate-limited)"
                    self.health.record_failure(err, disable=True)
                    raise SourceBannedError(err)

                # 5xx — 重試
                if 500 <= response.status_code < 600:
                    raise requests.HTTPError(
                        f"HTTP {response.status_code}", response=response
                    )

                response.raise_for_status()
                self.health.record_success()
                return response

            except (requests.Timeout, requests.ConnectionError, requests.HTTPError) as e:
                last_error = e
                sleep_s = self.retry.sleep_for_attempt(attempt)
                if sleep_s > 0:
                    print(
                        f"[{self.health.source_name}] attempt {attempt} failed: {e}. "
                        f"Sleeping {sleep_s}s before retry…"
                    )
                    time.sleep(sleep_s)
                else:
                    # 已超出 max_retries，標記失敗但不 disable（可能只是暫時性）
                    self.health.record_failure(str(e))
                    raise

        # 所有重試都失敗
        self.health.record_failure(f"max retries: {last_error}")
        raise RuntimeError(
            f"[{self.health.source_name}] exhausted retries for {url}: {last_error}"
        )


# ============ 例外 ============

class SourceBannedError(Exception):
    """來源站點回 403/429，可能已被 ban 或 rate-limited，應停止當日抓取。"""

class SourceDisabledError(Exception):
    """來源已手動或自動停用，呼叫端應跳過這個來源。"""


# ============ 寫入輔助 ============

def write_json(path: Path, data: Any) -> None:
    """原子寫入 JSON：先寫到 .tmp 再 rename，避免半寫狀態。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp.replace(path)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def taipei_now_iso() -> str:
    """取得台北時區的 ISO 8601 時間字串（含時區標記）。"""
    import datetime as _dt
    tz = _dt.timezone(_dt.timedelta(hours=8))
    return _dt.datetime.now(tz).isoformat()


def taipei_today() -> str:
    """取得台北時區的 YYYY-MM-DD 日期字串。"""
    import datetime as _dt
    tz = _dt.timezone(_dt.timedelta(hours=8))
    return _dt.datetime.now(tz).date().isoformat()