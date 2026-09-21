"""
scrapers/goodinfo.py — Goodinfo 抓取器

Goodinfo 網址：https://goodinfo.tw/
- 董監事、加權平均、融資券、當沖比
- 反爬蟲機制：Cloudflare + TLS 指紋偵測 + 嚴格限流
- 必須用 Playwright + stealth +（可選）住宅代理

節流：15 秒/次（嚴格），單日上限 60 次。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from .base import (
    BrowserSession,
    RateLimiter,
    SourceHealth,
    CredentialManager,
    SessionStore,
    SessionNotFound,
    SessionExpired,
    write_json,
)


GOODINFO_BASE = "https://goodinfo.tw/tw/"


def create_goodinfo_session(
    cred: CredentialManager | None = None,
    headless: bool = True,
) -> BrowserSession:
    """建立 Goodinfo 用的 BrowserSession（需先 auth_setup.py 登入）。"""
    if cred is None:
        cred = CredentialManager()
    proxy_url = cred.goodinfo_proxy  # 可選住宅代理
    return BrowserSession(
        site="goodinfo",
        credential_manager=cred,
        session_store=SessionStore(),
        proxy_url=proxy_url,
        headless=headless,
    )


async def fetch_director_pledge(
    stock_code: str,
    session: BrowserSession | None = None,
) -> str:
    """抓取特定股票的董監事 + 質押資料。"""
    own_session = session is None
    if own_session:
        session = create_goodinfo_session()

    if own_session:
        await session.start()

    try:
        url = f"{GOODINFO_BASE}StockInfo/EquityDistributionClassHis/{stock_code}"
        html = await session.fetch(
            url,
            wait_selector="table.b1",
            min_delay=8.0,
            max_delay=15.0,
        )
        debug_dir = Path(__file__).resolve().parents[1] / "data" / "local" / "raw" / "goodinfo"
        debug_dir.mkdir(parents=True, exist_ok=True)
        (debug_dir / f"director_{stock_code}.html").write_text(html, encoding="utf-8")
        return html
    finally:
        if own_session:
            await session.close()


async def fetch_margin_short(
    stock_code: str,
    session: BrowserSession | None = None,
) -> str:
    """抓取特定股票的融資券資料。"""
    own_session = session is None
    if own_session:
        session = create_goodinfo_session()

    if own_session:
        await session.start()

    try:
        url = f"{GOODINFO_BASE}StockInfo/MarginPurchase/{stock_code}"
        html = await session.fetch(
            url,
            wait_selector="table.b1",
            min_delay=8.0,
            max_delay=15.0,
        )
        debug_dir = Path(__file__).resolve().parents[1] / "data" / "local" / "raw" / "goodinfo"
        debug_dir.mkdir(parents=True, exist_ok=True)
        (debug_dir / f"margin_{stock_code}.html").write_text(html, encoding="utf-8")
        return html
    finally:
        if own_session:
            await session.close()


async def fetch_daytrade(
    stock_code: str,
    session: BrowserSession | None = None,
) -> str:
    """抓取特定股票的當沖比資料。"""
    own_session = session is None
    if own_session:
        session = create_goodinfo_session()

    if own_session:
        await session.start()

    try:
        url = f"{GOODINFO_BASE}StockInfo/DayTrade/{stock_code}"
        html = await session.fetch(
            url,
            wait_selector="table.b1",
            min_delay=8.0,
            max_delay=15.0,
        )
        debug_dir = Path(__file__).resolve().parents[1] / "data" / "local" / "raw" / "goodinfo"
        debug_dir.mkdir(parents=True, exist_ok=True)
        (debug_dir / f"daytrade_{stock_code}.html").write_text(html, encoding="utf-8")
        return html
    finally:
        if own_session:
            await session.close()


def parse_director_html(html: str, stock_code: str) -> dict[str, Any]:
    """解析 Goodinfo 董監事 HTML → STOCK_UNIVERSE 欄位。"""
    # TODO: 實作
    raise NotImplementedError(
        "Goodinfo director parser needs tuning against actual HTML."
    )


def parse_margin_short_html(html: str, stock_code: str) -> dict[str, Any]:
    """解析 Goodinfo 融資券 HTML → margin_pct。"""
    # TODO: 實作
    raise NotImplementedError(
        "Goodinfo margin parser needs tuning against actual HTML."
    )


def parse_daytrade_html(html: str, stock_code: str) -> dict[str, Any]:
    """解析 Goodinfo 當沖比 HTML → dt_ratio。"""
    # TODO: 實作
    raise NotImplementedError(
        "Goodinfo daytrade parser needs tuning against actual HTML."
    )


def save_latest(out_dir: Path, dataset_name: str, parsed: list[dict[str, Any]], *, snapshot_date: str = "") -> dict[str, str]:
    """寫入 out_dir/goodinfo_<dataset>.json 與快照。"""
    from .base import taipei_today
    written = {}
    snapshot_date = snapshot_date or taipei_today()
    out_dir.mkdir(parents=True, exist_ok=True)
    # Save dated snapshot to data/<YYYY-MM-DD>/ (sibling of data/latest/)
    snapshot_dir = out_dir.parent.parent / snapshot_date
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    name = f"goodinfo_{dataset_name}.json"
    latest_path = out_dir / name
    snapshot_path = snapshot_dir / name
    write_json(latest_path, parsed)
    write_json(snapshot_path, parsed)
    written[name] = str(latest_path)
    return written


if __name__ == "__main__":
    async def _test():
        try:
            html = await fetch_director_pledge("2330")
            print(f"Got HTML, length = {len(html)} bytes")
        except SessionNotFound as e:
            print(f"[goodinfo] {e}")
            print("Please run: python -m backend.scripts.auth_setup --site goodinfo")

    asyncio.run(_test())