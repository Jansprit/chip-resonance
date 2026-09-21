"""
scrapers/tpex.py — 櫃買中心（TPEx / OTC）OpenAPI 抓取器

資料源：https://www.tpex.org.tw/openapi/v1/
- tpex_mainboard_daily_close_quotes    上市櫃（含 ETN）每日收盤行情
- 注意：回應使用 Big5 編碼，需手動 decode

節流：3 秒/次，單日上限 500 次。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import (
    HttpClient,
    RateLimiter,
    RetryPolicy,
    SourceHealth,
    write_json,
    taipei_today,
)


TPEX_BASE = "https://www.tpex.org.tw/openapi/v1"
ENDPOINT_DAILY_QUOTES = f"{TPEX_BASE}/tpex_mainboard_daily_close_quotes"


def create_tpex_client() -> HttpClient:
    rl = RateLimiter(min_interval=3.0, source_name="tpex")
    health = SourceHealth(source_name="tpex", daily_quota=500)
    return HttpClient(rate_limiter=rl, health=health, retry=RetryPolicy())


def parse_daily_quotes(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    解析 TPEx daily quotes 回傳為標準結構。

    每筆回傳欄位（Big5 中文，解碼後）：
      Date, SecuritiesCompanyCode, CompanyName,
      Close, Change, Open, High, Low, Average,
      TradingShares (張), TransactionAmount (元), TransactionNumber (筆),
      Capitals, NextReferencePrice

    TPEx 主要包含上櫃股票（4 碼，1101-9999 範圍）+ 權證 + ETN。
    我們只保留 4 碼數字代號（普通股）。
    """
    if not raw or not isinstance(raw, list):
        return []

    parsed = []
    for row in raw:
        code = (row.get("SecuritiesCompanyCode") or "").strip()
        name = (row.get("CompanyName") or "").strip()
        if not code or not name:
            continue

        # 過濾掉權證（代號含字母，例如 03001P）與 ETN
        if not code.isdigit() or len(code) != 4:
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

        parsed.append({
            "code": code,
            "name": name,
            "exchange": "TPEx",
            "date": _roc_to_iso(row.get("Date", "")),
            "price": safe_float("Close"),
            "open": safe_float("Open"),
            "high": safe_float("High"),
            "low": safe_float("Low"),
            "change": safe_float("Change"),
            "volume_lots": safe_int("TradingShares"),
            "turnover": safe_int("TransactionAmount"),
            "transactions": safe_int("TransactionNumber"),
            # TPEx 獨有欄位
            "next_reference_price": safe_float("NextReferencePrice"),
        })
    return parsed


def _roc_to_iso(date_str: str) -> str:
    """TPEx 日期格式為 '1150918' (民國年)，轉 ISO YYYY-MM-DD。"""
    s = str(date_str).strip()
    if len(s) != 7 or not s.isdigit():
        return s
    roc_year = int(s[:3])
    return f"{roc_year + 1911:04d}-{s[3:5]}-{s[5:7]}"


def fetch_daily_quotes(client: HttpClient | None = None) -> list[dict[str, Any]]:
    """抓取 TPEx 每日收盤行情（含 Big5 → UTF-8 解碼）。"""
    client = client or create_tpex_client()
    # TPEx OpenAPI 回應是 Big5 編碼，需覆寫 encoding
    raw_bytes = client.session.get(
        ENDPOINT_DAILY_QUOTES,
        timeout=client.timeout,
    )
    raw_bytes.raise_for_status()
    raw_bytes.encoding = "utf-8"  # 嘗試 UTF-8 優先（部分時期的 TPEx API 也支援）
    try:
        text = raw_bytes.text
        import json
        return parse_daily_quotes(json.loads(text))
    except (UnicodeDecodeError, json.JSONDecodeError):
        # Fallback Big5
        text = raw_bytes.content.decode("big5", errors="replace")
        import json
        return parse_daily_quotes(json.loads(text))


def save_latest(out_dir: Path, parsed: list[dict[str, Any]], *, snapshot_date: str = "") -> dict[str, str]:
    """
    寫入 out_dir/tpex_prices.json 與快照。
    out_dir 應該已經是 data/latest/，所以這裡直接寫到 out_dir 即可。

    Note: taipei_today 與 write_json 在函式內 import，避免不同 entry point
    造成 module re-import 的問題（pipeline.py 與單獨 python -m 載入路徑不同）
    """
    from .base import taipei_today, write_json as _write_json
    written = {}
    snapshot_date = snapshot_date or taipei_today()
    out_dir.mkdir(parents=True, exist_ok=True)
    snapshot_dir = out_dir.parent / snapshot_date
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    name = "tpex_prices.json"
    latest_path = out_dir / name
    snapshot_path = snapshot_dir / name
    _write_json(latest_path, parsed)
    _write_json(snapshot_path, parsed)
    written[name] = str(latest_path)
    return written


if __name__ == "__main__":
    print("Fetching TPEx daily quotes ...")
    rows = fetch_daily_quotes()
    print(f"  Got {len(rows)} stocks")
    if rows:
        print(f"  Sample: {rows[0]['code']} {rows[0]['name']} = {rows[0]['price']}")