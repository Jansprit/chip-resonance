"""
scrapers/us_markets.py — 美股 / 全球股 hook（空殼，預留擴充）

預期用途：
- 從 .env 讀 FINNHUB_API_KEY / ALPHA_VANTAGE_API_KEY / TWELVE_DATA_API_KEY / FRED_API_KEY
- 提供簡單的報價與基本面 API（讓使用者可以在 dashboard 上加 US ticker）
- 不影響台股 pipeline

目前狀態：純空殼，所有 method 拋 NotImplementedError，避免使用者誤以為可用。
未來實作：
- fetch_quote_finnhub(symbol)
- fetch_fundamentals_alpha_vantage(symbol)
- fetch_risk_free_rate_fred() → 用於 WACC 計算
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import (
    CredentialManager,
    HttpClient,
    RateLimiter,
    RetryPolicy,
    SourceHealth,
)


def credentials_status(cred: CredentialManager | None = None) -> dict[str, bool]:
    """回傳各美股 API key 是否已設定。"""
    if cred is None:
        cred = CredentialManager()
    return {
        "FINNHUB_API_KEY": bool(cred.finnhub_key),
        "ALPHA_VANTAGE_API_KEY": bool(cred.alpha_vantage_key),
        "TWELVE_DATA_API_KEY": bool(cred.twelve_data_key),
        "FRED_API_KEY": bool(cred.fred_key),
        "SEC_USER_AGENT": bool(cred.sec_user_agent),
    }


def is_available(cred: CredentialManager | None = None) -> bool:
    """是否至少有一個美股 API 可用。"""
    status = credentials_status(cred)
    return any(status.values())


# 未來實作的函式（先留空殼 + 明確錯誤）

def fetch_quote_finnhub(symbol: str) -> dict[str, Any]:
    """從 Finnhub 抓報價。"""
    raise NotImplementedError(
        "us_markets.py is a stub. "
        "Set FINNHUB_API_KEY in .env and implement this method when needed."
    )


def fetch_fundamentals_alpha_vantage(symbol: str) -> dict[str, Any]:
    """從 Alpha Vantage 抓基本面。"""
    raise NotImplementedError("us_markets.py is a stub. Set ALPHA_VANTAGE_API_KEY in .env.")


def fetch_risk_free_rate_fred() -> float:
    """從 FRED 抓 10 年期殖利率（rf），預設 fallback 4.5%。"""
    raise NotImplementedError("us_markets.py is a stub. Set FRED_API_KEY in .env.")


if __name__ == "__main__":
    status = credentials_status()
    print("=== US Markets Credentials Status ===\n")
    for key, present in status.items():
        marker = "✓" if present else "✗"
        print(f"  {marker} {key}")
    print(f"\n  Pipeline available: {is_available()}")