"""
scrapers/pyramid.py — 神秘金字塔（MoneyDJ / 基金會）大戶持股分級抓取器

神秘金字塔網址：https://www.moneydj.com/ 或 https://funddj.com/
- 需登入會員（免費或付費）
- 提供 400/600/800/1000 張以上持股分級 + 連續多週歷史
- 屬於反爬蟲敏感站（會偵測 bot、限流嚴格），必須 Playwright + stealth

節流：10 秒/次，單日上限 200 次。
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


# 神秘金字塔相關網址（實際 URL 取決於登入後看到的）
PYRAMID_BASE = "https://www.moneydj.com"


def create_pyramid_session(
    cred: CredentialManager | None = None,
    headless: bool = True,
) -> BrowserSession:
    """建立神秘金字塔用的 BrowserSession（需先 auth_setup.py 登入）。"""
    if cred is None:
        cred = CredentialManager()
    return BrowserSession(
        site="pyramid",
        credential_manager=cred,
        session_store=SessionStore(),
        headless=headless,
    )


async def fetch_chip_holders(
    stock_codes: list[str] | None = None,
    session: BrowserSession | None = None,
) -> dict[str, str]:
    """
    抓取多檔股票的 400/600/800/1000 張大戶持股分級 HTML。

    回傳：{ stock_code: html_content }
    """
    own_session = session is None
    if own_session:
        session = create_pyramid_session()

    if own_session:
        await session.start()

    results = {}
    try:
        codes = stock_codes or []
        for code in codes:
            # 神秘金字塔的個股大戶頁面結構（需依登入後實際頁面調整）
            url = f"{PYRAMID_BASE}/funddj/individual/holder/{code}"
            html = await session.fetch(
                url,
                wait_selector="table.holder-data",
                min_delay=8.0,
                max_delay=15.0,
            )
            results[code] = html
            # 存 debug HTML
            debug_dir = Path(__file__).resolve().parents[1] / "data" / "local" / "raw" / "pyramid"
            debug_dir.mkdir(parents=True, exist_ok=True)
            (debug_dir / f"{code}.html").write_text(html, encoding="utf-8")
        return results
    finally:
        if own_session:
            await session.close()


def parse_chip_holders_html(html: str, stock_code: str) -> dict[str, Any]:
    """
    解析神秘金字塔個股大戶持股 HTML。

    預期回傳（每檔）：
        {
            'code': '2330',
            'date': '2026-09-15',
            'pct_1000up_now': 67.5,
            'pct_1000up_w1': 67.2, 'pct_1000up_w2': 67.0, 'pct_1000up_w3': 66.8,
            'pct_400up': 82.1,
            'pct_400up_52w_high': False,
            'holder_cnt_change_8w': -2.1,
            'avg_lot_change_8w': 3.5,
        }

    注意：神秘金字塔的 DOM 結構需實際測試後調整。
    """
    # TODO: 實作解析（用 BeautifulSoup）
    # 預留 placeholder
    raise NotImplementedError(
        "Pyramid HTML parser needs tuning. Run auth_setup.py to log in, "
        "then inspect data/local/raw/pyramid/<code>.html and update this function."
    )


def save_latest(out_dir: Path, parsed: list[dict[str, Any]], *, snapshot_date: str = "") -> dict[str, str]:
    """寫入 out_dir/pyramid_chip.json 與快照。"""
    from .base import taipei_today
    written = {}
    snapshot_date = snapshot_date or taipei_today()
    out_dir.mkdir(parents=True, exist_ok=True)
    # Save dated snapshot to data/<YYYY-MM-DD>/ (sibling of data/latest/)
    snapshot_dir = out_dir.parent.parent / snapshot_date
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    name = "pyramid_chip.json"
    latest_path = out_dir / name
    snapshot_path = snapshot_dir / name
    write_json(latest_path, parsed)
    write_json(snapshot_path, parsed)
    written[name] = str(latest_path)
    return written


if __name__ == "__main__":
    async def _test():
        try:
            htmls = await fetch_chip_holders(["2330", "2454"])
            for code, html in htmls.items():
                print(f"  {code}: {len(html)} bytes")
        except SessionNotFound as e:
            print(f"[pyramid] {e}")
            print("Please run: python -m backend.scripts.auth_setup --site pyramid")

    asyncio.run(_test())