"""
scrapers/base.py — 共用基礎模組

提供：
- RateLimiter：每次請求的最低時間間隔（單一來源單執行緒）
- RetryPolicy：指數退避重試策略
- SourceHealth：追蹤單一來源的當日請求次數、停用狀態
- HttpClient：包裝 requests，注入 rate limit 與 retry 邏輯
- BrowserSession：Playwright 包裝，含 anti-detection 與 session 持久化
- CredentialManager：讀 .env 並提供型別化 API
- SessionStore：把 Playwright storage_state 存到 .sessions/<site>.json
- 共通常數：User-Agent、合理預設 timeout

設計約束（請勿繞過）：
1. RateLimiter 必須在**任何**對外請求前呼叫 wait()
2. 對同一 source 的請求必須共用同一個 RateLimiter 實例
3. 失敗時 RetryPolicy 會 sleep 至少 60s，請勿降低
4. BrowserSession 必須從 .sessions/<site>.json 載入 session，
   不允許無 session 直接連線（會被偵測為 bot）
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, date, timezone, timedelta
from pathlib import Path
from typing import Any, Callable, Optional

import requests


# ============ 常數 ============

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (compatible; ChipResonanceBot/1.0; "
    "+https://github.com/Jansprit/chip-resonance)"
)

# 真實常見瀏覽器 UA（用於 Playwright），隨機抽取讓 fingerprint 看起來自然
COMMON_BROWSER_UAS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:130.0) Gecko/20100101 Firefox/130.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
]

DEFAULT_TIMEOUT = 30  # seconds

# .env 預設位置（可被環境變數覆寫）
DEFAULT_ENV_PATH = Path(__file__).resolve().parents[1] / ".env"

# session storage 預設位置
DEFAULT_SESSION_DIR = Path(__file__).resolve().parents[1] / ".sessions"

TAIPEI_TZ = timezone(timedelta(hours=8))


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
                    jitter = float(os.environ.get("RL_JITTER", "0.5"))
                    sleep_for += random.uniform(0, jitter)
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
        last_error = None

        for attempt in range(1, self.retry.max_retries + 2):
            if not self.health.can_request():
                raise SourceDisabledError(
                    f"Source {self.health.source_name} disabled: "
                    f"{self.health.disabled_reason}"
                )

            try:
                self.rl.wait()
                response = self.session.get(url, timeout=self.timeout, **kwargs)

                if response.status_code in (403, 429):
                    err = f"HTTP {response.status_code} (likely banned / rate-limited)"
                    self.health.record_failure(err, disable=True)
                    raise SourceBannedError(err)

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
                    time.sleep(sleep_s)
                else:
                    self.health.record_failure(str(e))
                    raise

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
    return datetime.now(TAIPEI_TZ).isoformat()


def taipei_today() -> str:
    """取得台北時區的 YYYY-MM-DD 日期字串。"""
    return datetime.now(TAIPEI_TZ).date().isoformat()


# ============ 認證管理（讀 .env，不入 git）============

class CredentialManager:
    """
    從 .env 讀取所有可選憑證。

    用法：
        cred = CredentialManager()
        if cred.finnhub_key:
            ...

    不存在的 key 回傳 None，不拋例外。呼叫端自行決定要不要 skip。
    """

    ENV_PATH_ENV = "CHIP_RESONANCE_ENV"

    def __init__(self, env_path: Optional[Path] = None):
        self.env_path = env_path or Path(
            os.environ.get(self.ENV_PATH_ENV, DEFAULT_ENV_PATH)
        )
        self._values: dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        if not self.env_path.exists():
            return
        # 簡單的 .env parser（不依賴 python-dotenv）
        for line in self.env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            m = re.match(r"^([A-Z_][A-Z0-9_]*)\s*=\s*(.*)$", line)
            if not m:
                continue
            key, value = m.group(1), m.group(2).strip()
            # 去引號
            if (value.startswith('"') and value.endswith('"')) or (
                value.startswith("'") and value.endswith("'")
            ):
                value = value[1:-1]
            self._values[key] = value

    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        # 優先讀環境變數（容器化時常用），fallback 到 .env
        return os.environ.get(key) or self._values.get(key) or default

    def require(self, key: str) -> str:
        v = self.get(key)
        if not v:
            raise RuntimeError(f"Missing required credential: {key} (set in .env)")
        return v

    @property
    def finnhub_key(self) -> Optional[str]:
        return self.get("FINNHUB_API_KEY")

    @property
    def finmind_token(self) -> Optional[str]:
        return self.get("FINMIND_TOKEN")

    @property
    def alpha_vantage_key(self) -> Optional[str]:
        return self.get("ALPHA_VANTAGE_API_KEY")

    @property
    def twelve_data_key(self) -> Optional[str]:
        return self.get("TWELVE_DATA_API_KEY")

    @property
    def fred_key(self) -> Optional[str]:
        return self.get("FRED_API_KEY")

    @property
    def sec_user_agent(self) -> Optional[str]:
        return self.get("SEC_USER_AGENT")

    @property
    def goodinfo_proxy(self) -> Optional[str]:
        return self.get("GOODINFO_PROXY_URL")

    @property
    def pyramid_username(self) -> Optional[str]:
        return self.get("PYRAMID_USERNAME")

    @property
    def pyramid_password(self) -> Optional[str]:
        return self.get("PYRAMID_PASSWORD")

    @property
    def goodinfo_username(self) -> Optional[str]:
        return self.get("GOODINFO_USERNAME")

    @property
    def goodinfo_password(self) -> Optional[str]:
        return self.get("GOODINFO_PASSWORD")

    def summary(self) -> dict[str, bool]:
        """回傳各憑據是否存在的摘要（給 meta.json 與 debug 用）。"""
        return {
            "finnhub": bool(self.finnhub_key),
            "finmind": bool(self.finmind_token),
            "alpha_vantage": bool(self.alpha_vantage_key),
            "twelve_data": bool(self.twelve_data_key),
            "fred": bool(self.fred_key),
            "sec_user_agent": bool(self.sec_user_agent),
            "goodinfo_proxy": bool(self.goodinfo_proxy),
            "pyramid_credentials": bool(self.pyramid_username and self.pyramid_password),
            "goodinfo_credentials": bool(self.goodinfo_username and self.goodinfo_password),
        }


# ============ Session 持久化（Playwright storage_state）============

class SessionStore:
    """
    把 Playwright 的 storage_state（含 cookies、localStorage）存到 .sessions/<site>.json。

    設計：
    - 檔案存在 → 載入
    - 檔案不存在 → 拋 SessionNotFound（呼叫端應跑 auth_setup.py 互動登入）
    - 過期檢查：每個站點的 session 預設 30 天有效
    """

    def __init__(self, session_dir: Optional[Path] = None):
        self.session_dir = session_dir or DEFAULT_SESSION_DIR
        self.session_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, site: str) -> Path:
        return self.session_dir / f"{site}.json"

    def exists(self, site: str) -> bool:
        return self._path(site).exists()

    def load(self, site: str) -> dict:
        """載入 session state。若不存在或過期，拋例外。"""
        path = self._path(site)
        if not path.exists():
            raise SessionNotFound(f"No session for {site}; run auth_setup.py first")
        state = json.loads(path.read_text(encoding="utf-8"))
        # 過期檢查（若有 expires_at 欄位）
        expires_at = state.get("_meta", {}).get("expires_at")
        if expires_at:
            try:
                exp_dt = datetime.fromisoformat(expires_at)
                if datetime.now(TAIPEI_TZ) > exp_dt:
                    raise SessionExpired(f"Session for {site} expired at {expires_at}")
            except ValueError:
                pass
        return state

    def save(self, site: str, storage_state: dict, expires_in_days: int = 30) -> None:
        """存 session state（會加 _meta 用於過期檢查）。"""
        storage_state["_meta"] = {
            "site": site,
            "saved_at": taipei_now_iso(),
            "expires_at": (
                datetime.now(TAIPEI_TZ) + timedelta(days=expires_in_days)
            ).isoformat(),
        }
        write_json(self._path(site), storage_state)

    def remove(self, site: str) -> None:
        path = self._path(site)
        if path.exists():
            path.unlink()

    def status(self, site: str) -> dict:
        """回傳 session 狀態摘要。"""
        path = self._path(site)
        if not path.exists():
            return {"exists": False}
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
            meta = state.get("_meta", {})
            return {
                "exists": True,
                "saved_at": meta.get("saved_at"),
                "expires_at": meta.get("expires_at"),
                "cookies_count": len(state.get("cookies", [])),
            }
        except Exception as e:
            return {"exists": True, "error": str(e)}


class SessionNotFound(Exception):
    pass

class SessionExpired(Exception):
    pass


# ============ Browser Session（Playwright + anti-detection）============

class BrowserSession:
    """
    包裝 Playwright，提供：
    - 隨機 User-Agent + viewport（anti-fingerprint）
    - 自動從 .sessions/<site>.json 載入 storage_state
    - 支援住宅代理（GOODINFO_PROXY_URL）
    - fetch() 含節流 + 隨機延遲

    用法（呼叫端必須先確保 session 已登入）：
        session = BrowserSession(site="pyramid", cred=cred)
        try:
            await session.load()
            html = await session.fetch(url, wait_selector=".data-table")
        except SessionNotFound:
            print("請執行 python -m backend.scripts.auth_setup --site pyramid")

    Anti-detection 設計：
    - 隨機 UA（從 COMMON_BROWSER_UAS 抽）
    - 隨機 viewport（1366×768 ~ 1920×1080）
    - 隨機延遲 5-15 秒（介於真實人類瀏覽節奏）
    - 隨機滑鼠軌跡（fetch 時加上）
    - 不開啟 webdriver feature（Playwright 預設就有，但 stealth 更穩）
    """

    def __init__(
        self,
        site: str,
        credential_manager: Optional[CredentialManager] = None,
        session_store: Optional[SessionStore] = None,
        proxy_url: Optional[str] = None,
        headless: bool = True,
    ):
        self.site = site
        self.cred = credential_manager or CredentialManager()
        self.store = session_store or SessionStore()
        self.proxy_url = proxy_url
        self.headless = headless
        self._playwright = None
        self._browser = None
        self._context = None
        self._storage_state = None

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.close()

    async def start(self) -> None:
        """啟動 Playwright + Chromium。"""
        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()
        launch_kwargs = {"headless": self.headless}
        if self.proxy_url:
            launch_kwargs["proxy"] = {"server": self.proxy_url}
        self._browser = await self._playwright.chromium.launch(**launch_kwargs)

        # 載入 session
        try:
            self._storage_state = self.store.load(self.site)
        except (SessionNotFound, SessionExpired) as e:
            await self._browser.close()
            await self._playwright.stop()
            self._browser = None
            self._playwright = None
            raise

        # 隨機指紋
        ua = random.choice(COMMON_BROWSER_UAS)
        viewport = {
            "width": random.choice([1366, 1440, 1536, 1920]),
            "height": random.choice([768, 900, 1024, 1080]),
        }

        context_kwargs = {
            "user_agent": ua,
            "viewport": viewport,
            "locale": "zh-TW",
            "timezone_id": "Asia/Taipei",
            "storage_state": self._storage_state,
        }
        self._context = await self._browser.new_context(**context_kwargs)

    async def close(self) -> None:
        """關閉瀏覽器與 Playwright。"""
        try:
            if self._context:
                await self._context.close()
        except Exception:
            pass
        try:
            if self._browser:
                await self._browser.close()
        except Exception:
            pass
        try:
            if self._playwright:
                await self._playwright.stop()
        except Exception:
            pass
        self._context = None
        self._browser = None
        self._playwright = None

    async def fetch(
        self,
        url: str,
        wait_selector: Optional[str] = None,
        min_delay: float = 3.0,
        max_delay: float = 8.0,
    ) -> str:
        """
        抓取 URL 並回傳 HTML。會自動：
        1. 隨機延遲（min_delay ~ max_delay 秒）
        2. 模擬人類行為（goto → 隨機 scroll → wait selector）
        3. 隨機滑鼠軌跡
        """
        if not self._context:
            raise RuntimeError("BrowserSession not started; call start() first")

        page = await self._context.new_page()
        try:
            # 隨機延遲（讓流量節奏像人）
            await asyncio.sleep(random.uniform(min_delay, max_delay))

            await page.goto(url, wait_until="domcontentloaded", timeout=DEFAULT_TIMEOUT * 1000)

            # 隨機 scroll（模擬讀頁面）
            for _ in range(random.randint(1, 3)):
                scroll_y = random.randint(100, 800)
                await page.evaluate(f"window.scrollBy(0, {scroll_y})")
                await asyncio.sleep(random.uniform(0.2, 0.8))

            # 等 selector
            if wait_selector:
                await page.wait_for_selector(wait_selector, timeout=DEFAULT_TIMEOUT * 1000)

            # 隨機滑鼠移動
            await page.mouse.move(
                random.randint(100, 800),
                random.randint(100, 600),
            )

            html = await page.content()
            return html
        finally:
            await page.close()


# ============ 反 IP ban 工具 ============

def random_delay(min_s: float = 3.0, max_s: float = 8.0) -> None:
    """隨機 sleep 一段時間，模擬人類瀏覽節奏。"""
    time.sleep(random.uniform(min_s, max_s))


def get_random_ua() -> str:
    """隨機抽一個常見瀏覽器 User-Agent。"""
    return random.choice(COMMON_BROWSER_UAS)


# Re-export playwright-friendly errors
__all__ = [
    "RateLimiter",
    "RetryPolicy",
    "SourceHealth",
    "HttpClient",
    "SourceBannedError",
    "SourceDisabledError",
    "write_json",
    "read_json",
    "taipei_now_iso",
    "taipei_today",
    "CredentialManager",
    "SessionStore",
    "SessionNotFound",
    "SessionExpired",
    "BrowserSession",
    "random_delay",
    "get_random_ua",
    "DEFAULT_USER_AGENT",
    "COMMON_BROWSER_UAS",
    "DEFAULT_TIMEOUT",
    "DEFAULT_ENV_PATH",
    "DEFAULT_SESSION_DIR",
    "TAIPEI_TZ",
]