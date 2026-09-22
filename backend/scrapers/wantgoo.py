"""
scrapers/wantgoo.py — 玩股網 (wantgoo.com.tw) 抓取器

資料源：https://www.wantgoo.com/stock/<code>/...
- 融資券變化 → F9 價籌背離懲罰
- 當沖比 → F9 價籌背離懲罰
- 法人買賣超 → F8 回調籌碼守穩 / F10 利空籌碼修復

注意：玩股網使用 Cloudflare，純 requests 會被擋。必須用 Playwright + stealth。
**免登入**即可取得上述資料；本系統不需任何登入憑證。

節流：8 秒/次（HTML 較大），單日上限 200 次。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from .base import (
    BrowserSession,
    SessionStore,
    SessionNotFound,
    SessionExpired,
    CredentialManager,
    write_json,
    taipei_today,
    random_delay,
)


# 玩股網個股頁面
WANTAOO_BASE = "https://www.wantgoo.com/stock"
# 三大類頁面
PAGE_BALANCE_SHEET = "balance-sheet"        # 融資券餘額
PAGE_INSTITUTIONAL = "institutional-investors"  # 法人買賣超
# 當沖比在主個股頁的「籌碼」區塊內，無單獨 URL；需要從主頁解析

# 玩股網個股首頁（含當沖比與籌碼概要）
WANTAOO_MAIN = "{base}/{code}"


def create_wantgoo_session(cred: CredentialManager | None = None) -> BrowserSession:
    """玩股網不需要登入，但需要 Playwright 過 Cloudflare。"""
    if cred is None:
        cred = CredentialManager()
    return BrowserSession(
        site="wantgoo",
        credential_manager=cred,
        session_store=SessionStore(),
        headless=True,
        require_session=False,  # 玩股網免登入
    )


def is_available() -> bool:
    """玩股網資料全部免登入；只要有 Playwright + Chromium 就能跑。"""
    return True


async def fetch_balance_sheet(
    stock_code: str,
    session: BrowserSession | None = None,
) -> str:
    """
    抓取特定股票的融資券餘額頁 HTML。

    URL: https://www.wantgoo.com/stock/{code}/balance-sheet
    """
    own_session = session is None
    if own_session:
        session = create_wantgoo_session()
        await session.start()
    try:
        url = f"{WANTAOO_BASE}/{stock_code}/{PAGE_BALANCE_SHEET}"
        html = await session.fetch(
            url,
            wait_selector="table",
            min_delay=5.0,
            max_delay=10.0,
        )
        debug_dir = Path(__file__).resolve().parents[1] / "data" / "local" / "raw" / "wantgoo"
        debug_dir.mkdir(parents=True, exist_ok=True)
        (debug_dir / f"balance_{stock_code}.html").write_text(html, encoding="utf-8")
        return html
    finally:
        if own_session:
            await session.close()


async def fetch_institutional(
    stock_code: str,
    session: BrowserSession | None = None,
) -> str:
    """
    抓取特定股票的法人買賣超頁 HTML。

    URL: https://www.wantgoo.com/stock/{code}/institutional-investors
    """
    own_session = session is None
    if own_session:
        session = create_wantgoo_session()
        await session.start()
    try:
        url = f"{WANTAOO_BASE}/{stock_code}/{PAGE_INSTITUTIONAL}"
        html = await session.fetch(
            url,
            wait_selector="table",
            min_delay=5.0,
            max_delay=10.0,
        )
        debug_dir = Path(__file__).resolve().parents[1] / "data" / "local" / "raw" / "wantgoo"
        debug_dir.mkdir(parents=True, exist_ok=True)
        (debug_dir / f"institutional_{stock_code}.html").write_text(html, encoding="utf-8")
        return html
    finally:
        if own_session:
            await session.close()


async def fetch_main_page(
    stock_code: str,
    session: BrowserSession | None = None,
) -> str:
    """
    抓取特定股票的主頁（含當沖比 / 籌碼概要）。

    URL: https://www.wantgoo.com/stock/{code}
    """
    own_session = session is None
    if own_session:
        session = create_wantgoo_session()
        await session.start()
    try:
        url = WANTAOO_MAIN.format(base=WANTAOO_BASE, code=stock_code)
        html = await session.fetch(
            url,
            wait_selector="table",
            min_delay=5.0,
            max_delay=10.0,
        )
        debug_dir = Path(__file__).resolve().parents[1] / "data" / "local" / "raw" / "wantgoo"
        debug_dir.mkdir(parents=True, exist_ok=True)
        (debug_dir / f"main_{stock_code}.html").write_text(html, encoding="utf-8")
        return html
    finally:
        if own_session:
            await session.close()


# ============ 解析函式（待 HTML 觀察後實作 selector）============

def parse_balance_sheet_html(html: str, stock_code: str) -> dict[str, Any]:
    """
    解析融資券餘額 HTML → margin_pct 與 short_ratio。
    公式：margin_pct = (融資餘額 / 融資限額) * 100
    """
    # TODO: 觀察 data/local/raw/wantgoo/balance_<code>.html 後 tune selector
    raise NotImplementedError(
        "parse_balance_sheet_html needs tuning. "
        "Run once with sample stock and inspect data/local/raw/wantgoo/balance_*.html"
    )


def parse_institutional_html(html: str, stock_code: str) -> dict[str, Any]:
    """
    解析法人買賣超 HTML → 三大法人近 N 日買賣超（張數）。
    用於 F8（回調時法人是否接手）與 F10（利空時法人是否轉買）。
    """
    # TODO: tune selector
    raise NotImplementedError(
        "parse_institutional_html needs tuning. "
        "Run once with sample stock and inspect data/local/raw/wantgoo/institutional_*.html"
    )


def parse_main_page_html(html: str, stock_code: str) -> dict[str, Any]:
    """
    解析主頁 → 當沖比 (dt_ratio)。
    """
    # TODO: tune selector
    raise NotImplementedError(
        "parse_main_page_html needs tuning. "
        "Run once with sample stock and inspect data/local/raw/wantgoo/main_*.html"
    )


# ============ 寫入輔助 ============

def save_latest(out_dir: Path, dataset_name: str, parsed: list[dict[str, Any]], *, snapshot_date: str = "") -> dict[str, str]:
    """寫入 out_dir/wantgoo_<dataset>.json 與快照。"""
    written = {}
    snapshot_date = snapshot_date or taipei_today()
    out_dir.mkdir(parents=True, exist_ok=True)
    snapshot_dir = out_dir.parent / snapshot_date
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    name = f"wantgoo_{dataset_name}.json"
    latest_path = out_dir / name
    snapshot_path = snapshot_dir / name
    write_json(latest_path, parsed)
    write_json(snapshot_path, parsed)
    written[name] = str(latest_path)
    return written


if __name__ == "__main__":
    async def _test():
        html = await fetch_balance_sheet("2330")
        print(f"balance_sheet: {len(html)} bytes")

    print(f"is_available: {is_available()}")
    asyncio.run(_test())