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

# 免費層（無 token）可用的 dataset —— 2026-10-25 實測：
#   TaiwanStockPrice        → 200，資料回溯到 2016-01-04
#   TaiwanStockDayTrading   → 200，資料回溯到 2016-01-04
#   TaiwanStockShareholding → 400 "Your level is free"（**這個才需要付費**）
#
# 過去的結論「FinMind 是付費牆」其實只對持股分級成立；
# 價格與當沖資料集免 token 就能拿，這直接影響 pipeline 該不該跑 FinMind。
FREE_DATASETS = ("TaiwanStockPrice", "TaiwanStockDayTrading", "TaiwanStockInfo")


def create_finmind_client(cred: Optional[CredentialManager] = None) -> HttpClient:
    """
    FinMind 客戶端（**快速失敗**，不要用全域的 60/300/900 秒退避）。

    2026-10-25 實測：FinMind 免費層會**間歇性**回
    `400 {"msg": "Your level is free"}` —— 同一個 URL 在 30 秒內
    可以「成功 → 失敗 → 又成功」。

    用全域退避（60 s → 300 s → 900 s）會讓 pipeline 整整卡掉 15 分鐘，
    而且最後還是失敗（那是配額／路由層的問題，不是暫時性的網路抖動）。
    這裡改成：最多重試 2 次、間隔 3 / 8 秒，然後就放棄這一個來源，
    讓合併層退回 Yahoo 的價格資料。
    """
    rl = RateLimiter(min_interval=5.0, source_name="finmind")
    health = SourceHealth(source_name="finmind", daily_quota=200)
    client = HttpClient(
        rate_limiter=rl,
        health=health,
        retry=RetryPolicy(max_retries=2, schedule=(3, 8)),
        timeout=30,
    )
    # 把 token 帶到 header（有的話）。沒有 token 也能用免費資料集。
    if cred is None:
        cred = CredentialManager()
    token = cred.finmind_token
    if token:
        client.session.headers["Authorization"] = f"Bearer {token}"
    return client


def is_available(cred: Optional[CredentialManager] = None) -> bool:
    """
    FinMind 免費層可用（2026-10-25 實測：無 token 也能取 TaiwanStockPrice）。

    舊版回傳 `bool(finmind_token)`，導致 pipeline 在沒有 token 時
    **整個跳過** FinMind —— 等於白白放棄一個免費、CI 可用的價格來源。
    需要 token 的只有付費資料集（如 TaiwanStockShareholding），
    那部分由呼叫端另外判斷。
    """
    return True



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

    ⚠️ **參數名稱的坑（2026-10-25 抓到的根因）**：
    FinMind v4 的股票代號參數是 **`data_id`**，不是 `stock_id`。
    傳 `stock_id=2330` 會回：

        400 {"msg": "Your level is free. Please update your user level."}

    這個錯誤訊息**完全誤導** —— 它看起來像「免費層沒有這個資料集」，
    於是本專案好一段時間都認為 FinMind 是付費牆、把它整個放棄。
    實際上只是參數名稱寫錯；改成 `data_id` 立刻 200，
    而且免 token 就能拿到 2016-01-04 起的歷史資料。

    這是「見樹不見林」的典型：錯誤訊息指向「付費牆」，
    真因卻只是一個參數名。
    """
    if client is None:
        client = create_finmind_client()
    params = {"dataset": dataset}
    if stock_id:
        params["data_id"] = stock_id          # ← 必須是 data_id，不是 stock_id
    if start_date:
        params["start_date"] = start_date
    if end_date:
        params["end_date"] = end_date
    payload = client.get_json(FINMIND_BASE, params=params)

    # FinMind 的回應是一層 envelope：{"msg":"success","status":200,"data":[...]}
    # 舊版直接把整個 envelope 當成資料回傳，於是呼叫端拿到的是
    # ["msg", "status", "data"] 這三個 key 的字串陣列 —— 資料完全沒進來。
    # 這個 bug 之所以能藏這麼久，正是因為 FinMind 從來沒被成功執行過
    # （沒 token → 整個來源被 skip）。
    if isinstance(payload, dict):
        status = payload.get("status")
        if status != 200:
            raise RuntimeError(
                f"FinMind {dataset} 回 {status}：{payload.get('msg')!r}"
            )
        rows = payload.get("data")
        return rows if isinstance(rows, list) else []
    return payload if isinstance(payload, list) else []


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