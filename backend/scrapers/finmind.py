"""
scrapers/finmind.py — FinMind REST API 客戶端

FinMind 提供台股的歷史價格、財報、月營收、股利等資料。
- 免費方案：每小時 600 次，無 token 仍可使用但有限速
- 付費方案：提高上限與速度

API: https://api.finmindtrade.com/api/v4/data

節流：5 秒/次，單日上限 200 次。
無 token 時：標記 disabled_until=never，pipeline 自動 skip（graceful degradation）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from .base import (
    HttpClient,
    RateLimiter,
    RetryPolicy,
    SourceHealth,
    CredentialManager,
    write_json,
)


FINMIND_BASE = "https://api.finmindtrade.com/api/v4/data"

# 常用 dataset（台股相關）
DATASETS = {
    "TaiwanStockPrice": "台股每日股價",
    "TaiwanStockMonthRevenue": "台股月營收",
    "TaiwanStockFinancialStatements": "台股財報",
    "TaiwanStockDividend": "台股股利",
    "TaiwanStockShareholding": "台股持股分級（需付費）",
}


def create_finmind_client(cred: Optional[CredentialManager] = None) -> HttpClient:
    rl = RateLimiter(min_interval=5.0, source_name="finmind")
    health = SourceHealth(source_name="finmind", daily_quota=200)
    client = HttpClient(rate_limiter=rl, health=health, retry=RetryPolicy())
    # 把 token 帶到 header
    if cred is None:
        cred = CredentialManager()
    token = cred.finmind_token
    if token:
        client.session.headers["Authorization"] = f"Bearer {token}"
    return client


def is_available(cred: Optional[CredentialManager] = None) -> bool:
    """是否可以使用 FinMind（有無 token）。"""
    if cred is None:
        cred = CredentialManager()
    return bool(cred.finmind_token)


def fetch_dataset(
    dataset: str,
    stock_id: str = "",
    start_date: str = "",
    end_date: str = "",
    client: Optional[HttpClient] = None,
) -> list[dict[str, Any]]:
    """
    通用 FinMind 抓取函式。

    參數:
        dataset: 例如 "TaiwanStockPrice"
        stock_id: 股票代號，例如 "2330"（留空 = 全市場）
        start_date: YYYY-MM-DD
        end_date: YYYY-MM-DD
    """
    if client is None:
        client = create_finmind_client()
    params = {"dataset": dataset}
    if stock_id:
        params["stock_id"] = stock_id
    if start_date:
        params["start_date"] = start_date
    if end_date:
        params["end_date"] = end_date
    return client.get_json(FINMIND_BASE, params=params)


def fetch_stock_prices(
    stock_ids: list[str],
    start_date: str,
    end_date: str,
    client: Optional[HttpClient] = None,
) -> list[dict[str, Any]]:
    """批次抓取多檔股票的歷史價格。"""
    all_rows = []
    for sid in stock_ids:
        rows = fetch_dataset(
            "TaiwanStockPrice",
            stock_id=sid,
            start_date=start_date,
            end_date=end_date,
            client=client,
        )
        all_rows.extend(rows)
    return all_rows


def fetch_month_revenue(
    stock_ids: list[str],
    start_date: str,
    end_date: str,
    client: Optional[HttpClient] = None,
) -> list[dict[str, Any]]:
    """批次抓取月營收。"""
    all_rows = []
    for sid in stock_ids:
        rows = fetch_dataset(
            "TaiwanStockMonthRevenue",
            stock_id=sid,
            start_date=start_date,
            end_date=end_date,
            client=client,
        )
        all_rows.extend(rows)
    return all_rows


def save_latest(out_dir: Path, dataset_name: str, parsed: list[dict[str, Any]], *, snapshot_date: str = "") -> dict[str, str]:
    """寫入 out_dir/finmind_<dataset>.json 與快照。"""
    written = {}
    snapshot_date = snapshot_date or ""  # taipei_today 不需要，這裡只是 placeholder
    out_dir.mkdir(parents=True, exist_ok=True)
    name = f"finmind_{dataset_name}.json"
    latest_path = out_dir / name
    write_json(latest_path, parsed)
    written[name] = str(latest_path)
    return written


if __name__ == "__main__":
    cred = CredentialManager()
    if not cred.finmind_token:
        print("[finmind] FINMIND_TOKEN not set; skipping smoke test.")
    else:
        print("Fetching FinMind TaiwanStockPrice for 2330 ...")
        rows = fetch_dataset("TaiwanStockPrice", stock_id="2330")
        print(f"  Got {len(rows)} rows")
        if rows:
            print(f"  Sample: {rows[0]}")