"""
scrapers/twse.py — 台灣證券交易所 OpenAPI

資料源（皆為公開、不需 API key）：
- STOCK_DAY_ALL        每日個股收盤行情（上市、約 1100 檔）
- MI_INDEX             市場指數（TAIEX、各類股指數）
- t05_st10             暫停交易 / 全額交割 / 警示股清單（從 MOPS 取得）

節流：3 秒/次（避免被當作爬蟲），單日上限 500 次。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .base import (
    HttpClient,
    RateLimiter,
    RetryPolicy,
    SourceHealth,
    write_json,
    taipei_now_iso,
)


# TWSE OpenAPI 端點
TWSE_BASE = "https://openapi.twse.com.tw/v1"
ENDPOINT_STOCK_DAY_ALL = f"{TWSE_BASE}/exchangeReport/STOCK_DAY_ALL"
ENDPOINT_MI_INDEX = f"{TWSE_BASE}/exchangeReport/MI_INDEX"


def create_twse_client() -> HttpClient:
    """建立 TWSE 的 HttpClient，含節流與健康狀態。"""
    rl = RateLimiter(min_interval=3.0, source_name="twse")
    health = SourceHealth(source_name="twse", daily_quota=500)
    return HttpClient(rate_limiter=rl, health=health, retry=RetryPolicy())


def roc_date_to_iso(roc_date: str | int) -> str:
    """
    民國日期 (e.g. 1150918) 轉 ISO 8601 (e.g. 2026-09-18)。
    民國年份 = 西元年份 - 1911。
    """
    s = str(roc_date).strip()
    if len(s) != 7 or not s.isdigit():
        return str(roc_date)
    roc_year = int(s[:3])
    month = int(s[3:5])
    day = int(s[5:7])
    return f"{roc_year + 1911:04d}-{month:02d}-{day:02d}"


def parse_stock_daily_all(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    解析 STOCK_DAY_ALL 的回傳為標準 STOCK_UNIVERSE 相容的結構。

    回傳每筆的欄位：
        code           — 股票代號（字串）
        name           — 公司簡稱
        exchange       — "TWSE"（固定）
        date           — ISO 日期
        price          — 收盤價
        open / high / low
        change         — 漲跌點數
        volume_lots    — 成交量（張）
        turnover       — 成交金額（元）
        transactions   — 成交筆數
    """
    if not raw or not isinstance(raw, list):
        return []

    parsed = []
    for row in raw:
        code = (row.get("Code") or "").strip()
        name = (row.get("Name") or "").strip()
        if not code or not name:
            continue

        def safe_float(key, default=0.0):
            v = row.get(key, "")
            if v == "" or v is None:
                return default
            try:
                return float(v)
            except (ValueError, TypeError):
                return default

        def safe_int(key, default=0):
            v = row.get(key, "")
            if v == "" or v is None:
                return default
            try:
                return int(float(v))
            except (ValueError, TypeError):
                return default

        # 過濾掉非普通股（權證、特別股、ETN 等）
        if not code.isdigit() or len(code) != 4:
            continue
        # TWSE 上市股票代號通常是 1101~9999 開頭，< 1100 多為權證
        if int(code) < 1100:
            continue

        parsed.append({
            "code": code,
            "name": name,
            "exchange": "TWSE",
            "date": roc_date_to_iso(row.get("Date", "")),
            "price": safe_float("ClosingPrice"),
            "open": safe_float("OpeningPrice"),
            "high": safe_float("HighestPrice"),
            "low": safe_float("LowestPrice"),
            "change": safe_float("Change"),
            "volume_lots": safe_int("TradeVolume"),
            "turnover": safe_int("TradeValue"),
            "transactions": safe_int("Transaction"),
        })
    return parsed


def parse_market_index(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """解析 MI_INDEX，回傳指數列表（去除「報酬」與「反向」相關衍生指數）。"""
    if not raw:
        return []
    parsed = []
    for row in raw:
        name = row.get("指數", "")
        # 只要主指數與類股指數，不要衍生（包含「報酬」「反向」「兩倍」「槓桿」）
        if any(x in name for x in ["報酬", "反向", "兩倍", "槓桿", "正2", "反1"]):
            continue
        try:
            value = float(str(row.get("收盤指數", "")).replace(",", ""))
            change_pct = float(str(row.get("漲跌百分比", "")).replace(",", ""))
        except ValueError:
            continue
        parsed.append({
            "date": roc_date_to_iso(row.get("日期", "")),
            "name": name,
            "value": value,
            "change_pct": change_pct,
        })
    return parsed


# ============ 高階函式：抓 + 寫 ============

def fetch_prices(client: HttpClient | None = None) -> list[dict[str, Any]]:
    """抓取當日 TWSE 上市股票行情。"""
    client = client or create_twse_client()
    raw = client.get_json(ENDPOINT_STOCK_DAY_ALL)
    return parse_stock_daily_all(raw)


def fetch_market_index(client: HttpClient | None = None) -> list[dict[str, Any]]:
    """抓取當日 TWSE 主要指數。"""
    client = client or create_twse_client()
    raw = client.get_json(ENDPOINT_MI_INDEX)
    return parse_market_index(raw)


def save_latest(
    data_dir: Path,
    prices: list[dict[str, Any]],
    market_index: list[dict[str, Any]],
    *,
    snapshot_date: str = "",
) -> dict[str, str]:
    """
    把抓到的資料寫到 data_dir/latest/ 與 data_dir/<YYYY-MM-DD>/。
    data_dir 應為 repo/data/（pipeline.py 傳入 repo/data）。
    回傳寫入的檔案路徑。
    """
    from .base import taipei_today
    written = {}
    snapshot_date = snapshot_date or taipei_today()

    latest_dir = data_dir / "latest"
    snapshot_dir = data_dir / snapshot_date
    latest_dir.mkdir(parents=True, exist_ok=True)
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    files = {
        "prices.json": prices,
        "market_index.json": market_index,
    }
    for name, data in files.items():
        latest_path = latest_dir / name
        snapshot_path = snapshot_dir / name
        write_json(latest_path, data)
        write_json(snapshot_path, data)
        written[name] = str(latest_path)

    return written


if __name__ == "__main__":
    # 直接執行這個檔（python -m scrapers.twse）做 smoke test
    print("Fetching TWSE STOCK_DAY_ALL …")
    prices = fetch_prices()
    print(f"  Got {len(prices)} stocks")
    if prices:
        print(f"  Sample: {prices[0]['code']} {prices[0]['name']} = {prices[0]['price']}")

    print("Fetching TWSE MI_INDEX …")
    idx = fetch_market_index()
    print(f"  Got {len(idx)} indices")