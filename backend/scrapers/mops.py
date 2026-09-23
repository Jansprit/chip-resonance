"""
scrapers/mops.py — 公開資訊觀測站 (MOPS) 抓取器

MOPS 提供：
- 董監事持股（每月公告）
- 月營收
- 質押情形
- 各類財務報表

**2026-09 重要修正**：先前我以為 MOPS 2024 改版後端點失效需要登入，這是錯的。
**實際上**：
- 公開資訊觀測站有公開的董監事/財務資料
- ajax 端點會回 security error 給非瀏覽器請求
- 必須用 Playwright 才能抓到（如同其他 Playwright 源）

新網域：mops.twse.com.tw（不是舊的 mopsov.twse.com.tw）
- 舊端點（t146sb05）已 404
- 需研究新端點（可能在 /mops/web/ 下）

節流：8 秒/次，單日上限 100 次。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from .base import (
    BrowserSession,
    CredentialManager,
    SessionStore,
    RateLimiter,
    SourceHealth,
    RetryPolicy,
    write_json,
    taipei_today,
)


# MOPS 2024 改版後新網域
MOPS_BASE = "https://mops.twse.com.tw"
# 公開資訊觀測站的「董監事」搜尋頁
MOPS_DIRECTOR_SEARCH = f"{MOPS_BASE}/mops/web/t146sb05"
# 公開資訊觀測站的「質押」搜尋頁
MOPS_PLEDGE_SEARCH = f"{MOPS_BASE}/mops/web/t05bd09"


def is_available() -> bool:
    """MOPS 公開資訊觀測站的董監事與財務資料**免登入**可看，只是 ajax 需 Playwright 過 anti-bot。

    修正（2026-09）：先前標 False（graceful skip）導致 F3 因子一直用預設值。
    修正後改為 True，pipeline 會用 Playwright 嘗試抓取。
    """
    return True


def create_mops_session(cred: CredentialManager | None = None) -> BrowserSession:
    """建立 MOPS 用的 BrowserSession（**免登入**——只要 Playwright 過 anti-bot）。"""
    if cred is None:
        cred = CredentialManager()
    return BrowserSession(
        site="mops",
        credential_manager=cred,
        session_store=SessionStore(),
        headless=True,
        require_session=False,  # MOPS 免登入
    )


async def fetch_director_holding(
    stock_id: str,
    year: int,
    session: BrowserSession | None = None,
) -> str:
    """
    抓取特定股票某年的董監事持股申報資料（HTML）。

    URL: https://mops.twse.com.tw/mops/web/t146sb05?co_id=<stock_id>&year=<year>
    回傳原始 HTML（由 normalize.mops_director 解析）。
    """
    own_session = session is None
    if own_session:
        session = create_mops_session()
        await session.start()
    try:
        params = {
            "first": "true",
            "step": "1",
            "off": "1",
            "keyword4": "",
            "code1": "",
            "TYPEK2": "",
            "check": "",
            "queryName": "co_id",
            "inpuType": "co_id",
            "co_id": stock_id,
            "year": str(year),
        }
        url = f"{MOPS_DIRECTOR_SEARCH}?{urlencode(params)}"
        html = await session.fetch(
            url,
            wait_selector="table",
            min_delay=5.0,
            max_delay=10.0,
        )
        debug_dir = Path(__file__).resolve().parents[1] / "data" / "local" / "raw" / "mops"
        debug_dir.mkdir(parents=True, exist_ok=True)
        (debug_dir / f"director_{stock_id}_{year}.html").write_text(html, encoding="utf-8")
        return html
    finally:
        if own_session:
            await session.close()


async def fetch_pledge(
    stock_id: str,
    session: BrowserSession | None = None,
) -> str:
    """
    抓取特定股票的董監質押資料（HTML）。

    URL: https://mops.twse.com.tw/mops/web/t05bd09?co_id=<stock_id>
    """
    own_session = session is None
    if own_session:
        session = create_mops_session()
        await session.start()
    try:
        params = {
            "first": "true",
            "step": "1",
            "off": "1",
            "queryName": "co_id",
            "inpuType": "co_id",
            "co_id": stock_id,
        }
        url = f"{MOPS_PLEDGE_SEARCH}?{urlencode(params)}"
        html = await session.fetch(
            url,
            wait_selector="table",
            min_delay=5.0,
            max_delay=10.0,
        )
        debug_dir = Path(__file__).resolve().parents[1] / "data" / "local" / "raw" / "mops"
        debug_dir.mkdir(parents=True, exist_ok=True)
        (debug_dir / f"pledge_{stock_id}.html").write_text(html, encoding="utf-8")
        return html
    finally:
        if own_session:
            await session.close()


# ============ 解析函式（待 HTML 觀察後實作）============

def parse_director_holding_html(html: str, stock_id: str) -> dict[str, Any]:
    """
    解析 MOPS 董監事持股 HTML → director_holding_change_3m 與 director_pledge。

    注意：MOPS 2024 改版後 DOM 結構需觀察 data/local/raw/mops/director_*.html 後 tune。
    """
    raise NotImplementedError(
        "MOPS director HTML parser needs tuning. "
        "Run a sample fetch and inspect data/local/raw/mops/director_*.html."
    )


def parse_pledge_html(html: str, stock_id: str) -> dict[str, Any]:
    """
    解析 MOPS 質押 HTML → director_pledge_pct。
    """
    raise NotImplementedError(
        "MOPS pledge HTML parser needs tuning. "
        "Run a sample fetch and inspect data/local/raw/mops/pledge_*.html."
    )


# ============ 寫入輔助 ============

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
    print(f"is_available: {is_available()}")
    print(f"MOPS_BASE: {MOPS_BASE}")
    print(f"MOPS_DIRECTOR_SEARCH: {MOPS_DIRECTOR_SEARCH}")
    print()
    print("Note: ajax endpoints return security error for non-browser requests.")
    print("Must use Playwright. Run via pipeline to test.")