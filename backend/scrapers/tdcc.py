"""
scrapers/tdcc.py — 集保中心（TDCC）週股權分散表抓取器

資料源：https://www.tdcc.com.tw/
- 週五收盤後公布，次週才可得（必須標記 T+3 紀律）
- 表格為伺服器端 PHP 動態生成，需用 Playwright 渲染

節流：20 秒/次（HTML 大，伺服器有限流），單日上限 30 次。
"""

from __future__ import annotations

import asyncio
import re
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
    random_delay,
    write_json,
)


TDCC_URL = "https://www.tdcc.com.tw/portal/zh-tw/dl-page.html"
TDCC_DATA_URL = "https://www.tdcc.com.tw/portal/zh-tw/page-data-download"


def create_tdcc_session(
    cred: CredentialManager | None = None,
    headless: bool = True,
) -> BrowserSession:
    """建立 TDCC 用的 BrowserSession（**免登入**——集保週資料公開可下載，只需 Playwright 過 Cloudflare）。"""
    if cred is None:
        cred = CredentialManager()
    return BrowserSession(
        site="tdcc",
        credential_manager=cred,
        session_store=SessionStore(),
        headless=headless,
        require_session=False,  # 集保基本週資料免登入
    )


async def fetch_daily_range(
    week: str = "",
    session: BrowserSession | None = None,
) -> str:
    """
    抓取集保某週的股權分散表 HTML。

    week: YYYYMMDD（民國年）；留空 = 最新
    回傳：原始 HTML（由 normalize.tdcc() 解析）
    """
    own_session = session is None
    if own_session:
        session = create_tdcc_session()

    if own_session:
        await session.start()
    try:
        url = TDCC_DATA_URL + (f"?week={week}" if week else "")
        html = await session.fetch(
            url,
            wait_selector="table.data-table",
            min_delay=5.0,
            max_delay=12.0,
        )
        # 存原始 HTML 供 debug
        debug_dir = Path(__file__).resolve().parents[1] / "data" / "local" / "raw" / "tdcc"
        debug_dir.mkdir(parents=True, exist_ok=True)
        (debug_dir / f"{week or 'latest'}.html").write_text(html, encoding="utf-8")
        return html
    finally:
        if own_session:
            await session.close()


def parse_daily_range_html(html: str) -> list[dict[str, Any]]:
    """
    解析集保 HTML 為結構化資料。

    回傳每筆：
        {
            'code': str,
            'date': str,         # ISO YYYY-MM-DD
            'pct_400up_now': float,   # 400 張以上持股比例
            'pct_400up_w1': float,
            'pct_1000up_now': float,
            'pct_1000up_w1': float,
            'pct_1000up_w2': float,
            'pct_1000up_w3': float,
            'pct_600up_now': float,   # 600 張以上
            'pct_800up_now': float,   # 800 張以上
            'holder_cnt_change_8w': float,
            'avg_lot_change_8w': float,
            'pct_400up_52w_high': bool,
        }

    注意：此函數需要實際的 HTML 結構才能驗證。
    集保的格式每年可能略改，建議在 normalize.tdcc() 階段做容錯處理。
    """
    # TODO: 實際 HTML 結構解析
    # 預留 placeholder：實際實作時請用 BeautifulSoup4 + 容錯 selector
    raise NotImplementedError(
        "TDCC HTML parser needs to be tuned against real HTML. "
        "See docs/sandbox.md for the format spec."
    )


def save_latest(out_dir: Path, parsed: list[dict[str, Any]], *, snapshot_date: str = "") -> dict[str, str]:
    """寫入 out_dir/tdcc_chip.json 與快照。"""
    from .base import taipei_today
    written = {}
    snapshot_date = snapshot_date or taipei_today()
    out_dir.mkdir(parents=True, exist_ok=True)
    # Save dated snapshot to data/<YYYY-MM-DD>/ (sibling of data/latest/)
    snapshot_dir = out_dir.parent.parent / snapshot_date
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    name = "tdcc_chip.json"
    latest_path = out_dir / name
    snapshot_path = snapshot_dir / name
    write_json(latest_path, parsed)
    write_json(snapshot_path, parsed)
    written[name] = str(latest_path)
    return written


if __name__ == "__main__":
    async def _test():
        try:
            html = await fetch_daily_range()
            print(f"Got HTML, length = {len(html)}")
        except SessionNotFound as e:
            print(f"[tdcc] {e}")
            print("Please run: python -m backend.scripts.auth_setup --site tdcc")

    asyncio.run(_test())