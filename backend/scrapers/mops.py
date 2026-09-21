"""
scrapers/mops.py — 公開資訊觀測站（MOPS）爬蟲

MOPS 提供：
- 董監事持股（每月公告）
- 月營收
- 質押情形
- 各類財務報表

注意：MOPS 在 2024 年改版，URL 結構由 /server-java/ 改為 /mops/web/。
舊端點 (t146sb05) 已失效。新的 director holding endpoint 需要 ajax 呼叫，
本檔案先暫存 placeholder 與 graceful skip；待確認新 URL 後再實作。

節流：8 秒/次（HTML 解析較慢，且 MOPS 對 bot 有相當防禦），單日上限 100 次。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from .base import (
    HttpClient,
    RateLimiter,
    RetryPolicy,
    SourceHealth,
    write_json,
    taipei_today,
)


# MOPS 自 2024 年改版
MOPS_BASE = "https://mopsov.twse.com.tw"
# 新版 director holding 端點（待確認；先用舊版占位以利 graceful skip）
ENDPOINT_DIRECTOR_HOLDING = f"{MOPS_BASE}/mops/web/t146sb05"  # 預期 404
ENDPOINT_PLEDGE = f"{MOPS_BASE}/mops/web/t05bd09"


def create_mops_client() -> HttpClient:
    rl = RateLimiter(min_interval=8.0, source_name="mops")
    health = SourceHealth(source_name="mops", daily_quota=100)
    client = HttpClient(rate_limiter=rl, health=health, retry=RetryPolicy())
    client.session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
        "Referer": MOPS_BASE,
    })
    return client


def is_available() -> bool:
    """MOPS 自 2024 改版後舊端點失效，本檔案目前 graceful skip。"""
    return False  # 等新 URL 確認後改為 True


def fetch_director_holding(
    stock_id: str,
    year: int,
    client: HttpClient | None = None,
) -> str:
    """
    抓取特定股票某年的董監事持股申報資料（HTML）。

    警告：MOPS 2024 改版後此端點已失效；呼叫前請先 is_available() 檢查。
    """
    raise NotImplementedError(
        "MOPS director holding endpoint has been migrated in 2024. "
        "The old t146sb05 returns 404. Please investigate the new endpoint at "
        "https://mopsov.twse.com.tw/mops/web/ and update this function."
    )


def fetch_pledge(
    stock_id: str,
    client: HttpClient | None = None,
) -> str:
    """
    抓取特定股票的董監質押資料（HTML）。
    警告：同上，目前未實作。
    """
    raise NotImplementedError(
        "MOPS pledge endpoint has been migrated in 2024. "
        "See fetch_director_holding for details."
    )


def save_latest(out_dir: Path, dataset_name: str, parsed: list[dict[str, Any]], *, snapshot_date: str = "") -> dict[str, str]:
    """寫入 out_dir/mops_<dataset>.json 與快照。"""
    written = {}
    snapshot_date = snapshot_date or taipei_today()
    out_dir.mkdir(parents=True, exist_ok=True)
    snapshot_dir = out_dir.parent / snapshot_date
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    name = f"mops_{dataset_name}.json"
    latest_path = out_dir / name
    snapshot_path = snapshot_dir / name
    write_json(latest_path, parsed)
    write_json(snapshot_path, parsed)
    written[name] = str(latest_path)
    return written


if __name__ == "__main__":
    print("MOPS scraper: 目前 graceful skip（2024 改版後端點失效）")
    print("  請到 https://mopsov.twse.com.tw/mops/web/ 找新端點")
    print(f"  is_available() = {is_available()}")