"""
scrapers/pyramid.py — 神秘金字塔（MoneyDJ / 基金會）大戶持股分級抓取器

神秘金字塔網址：https://www.moneydj.com/ 或 https://funddj.com/

**重要修正（2026-09-22）**：先前以為神秘金字塔需登入會員才能看，**這是錯的**。
400/600/800/1000 張大戶分級與董監持股歷史在瀏覽器中**免登入即可看到**。

但因 MoneyDJ 有 Cloudflare 與 anti-bot 機制，純 requests / web_fetch 會被擋。
必須用 **Playwright + stealth** 才能成功抓取（這就是「瀏覽器代理工具」的實作）。

提供：
- 400/600/800/1000 張大戶持股分級（F1, F4, F6, F8, F10 來源）
- 董監持股歷史（F3 來源）
- 連續多週變化趨勢

節流：10 秒/次，單日上限 200 次。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from .base import (
    BrowserSession,
    CredentialManager,
    SessionStore,
    write_json,
    taipei_today,
)


# 神秘金字塔相關網址
PYRAMID_BASE = "https://www.moneydj.com"


def create_pyramid_session(
    cred: CredentialManager | None = None,
    headless: bool = True,
) -> BrowserSession:
    """建立神秘金字塔用的 BrowserSession（**免登入**——只要有 Playwright + Chromium 就能跑）。"""
    if cred is None:
        cred = CredentialManager()
    return BrowserSession(
        site="pyramid",
        credential_manager=cred,
        session_store=SessionStore(),
        headless=headless,
        require_session=False,  # 神秘金字塔免登入
    )


def is_available() -> bool:
    """神秘金字塔基本資料免登入；只要 Playwright + Chromium 就能跑。

    若日後需要用到付費會員限定資料（更深層歷史），再改為檢查 session。
    """
    return True


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
        await session.start()
    try:
        codes = stock_codes or []
        results = {}
        for code in codes:
            url = f"{PYRAMID_BASE}/funddj/individual/holder/{code}"
            html = await session.fetch(
                url,
                wait_selector="table.holder-data",
                min_delay=8.0,
                max_delay=15.0,
            )
            results[code] = html
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

    預期回傳：
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

    注意：神秘金字塔 DOM 結構需實際測試後調整。
    """
    raise NotImplementedError(
        "Pyramid HTML parser needs tuning. "
        "Run a sample scrape, inspect data/local/raw/pyramid/<code>.html, "
        "and update this function."
    )


def save_latest(out_dir: Path, parsed: list[dict[str, Any]], *, snapshot_date: str = "") -> dict[str, str]:
    """寫入 out_dir/pyramid_chip.json 與快照。"""
    written = {}
    snapshot_date = snapshot_date or taipei_today()
    out_dir.mkdir(parents=True, exist_ok=True)
    snapshot_dir = out_dir.parent / snapshot_date
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
        except Exception as e:
            print(f"[pyramid] {e}")

    print(f"is_available: {is_available()}")
    asyncio.run(_test())