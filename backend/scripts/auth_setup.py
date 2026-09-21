"""
scripts/auth_setup.py — CLI 工具，用 Playwright 開瀏覽器讓使用者手動登入

使用情境：
    python -m backend.scripts.auth_setup --site pyramid
    python -m backend.scripts.auth_setup --site goodinfo
    python -m backend.scripts.auth_setup --site tdcc
    python -m backend.scripts.auth_setup --site all
    python -m backend.scripts.auth_setup --status

登入後的 storage_state（含 cookies + localStorage）會存到
backend/.sessions/<site>.json，供後續 pipeline 自動讀取。
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# 確保 backend/ 在 import path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scrapers.base import (
    BrowserSession,
    CredentialManager,
    SessionStore,
    SessionNotFound,
    SessionExpired,
    TAIPEI_TZ,
    write_json,
)


SITE_LOGIN_URL = {
    # 各站點的登入頁 URL（需依實際情況調整）
    "pyramid": "https://www.moneydj.com/login",
    "goodinfo": "https://goodinfo.tw/tw/Account/Login",
    "tdcc": "https://www.tdcc.com.tw/portal/zh-tw/login.html",
}


async def login_one_site(site: str, headless: bool = False) -> None:
    """開啟 headed browser 讓使用者登入單一站點。"""
    if site not in SITE_LOGIN_URL:
        raise SystemExit(f"Unknown site: {site}")

    login_url = SITE_LOGIN_URL[site]
    store = SessionStore()

    print(f"[{site}] Opening browser at {login_url} ...")
    print(f"[{site}] Please log in manually in the browser window.")
    print(f"[{site}] After successful login, the script will save cookies automatically.")
    print(f"[{site}] Press Ctrl+C in this terminal to abort.\n")

    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(
            locale="zh-TW",
            timezone_id="Asia/Taipei",
            viewport={"width": 1366, "height": 768},
        )
        page = await context.new_page()
        await page.goto(login_url, wait_until="domcontentloaded")

        # 等待使用者登入（用 polling 偵測登入後的特徵，例如 URL 變更或某個元素出現）
        print(f"[{site}] Waiting for login completion ...")
        logged_in = await _wait_for_login(page, site)

        if not logged_in:
            print(f"[{site}] Login timeout (5 min). Aborted.")
            await browser.close()
            return

        # 儲存 storage_state
        storage_state = await context.storage_state()
        store.save(site, storage_state)
        print(f"[{site}] ✓ Session saved to {store._path(site)}")
        print(f"[{site}]   cookies: {len(storage_state.get('cookies', []))}")
        print(f"[{site}]   origins: {len(storage_state.get('origins', []))}")
        print(f"[{site}]   expires: {store._path(site).exists() and store.status(site).get('expires_at', '?')}")

        await browser.close()


async def _wait_for_login(page, site: str, timeout_sec: int = 300) -> bool:
    """
    偵測登入完成的簡單實作：
    - pyramid: 進入 moneydj.com/account 頁面
    - goodinfo: 出現會員中心連結
    - tdcc: 不一定要登入（公開資料）；這裡偵測主頁是否正常 loading
    """
    # 簡化版：每 5 秒檢查一次頁面 URL 變化，或檢查某個關鍵 element
    import time
    start = time.time()
    while time.time() - start < timeout_sec:
        await asyncio.sleep(5)
        url = page.url
        # 各站點的「登入後」URL 特徵（請依登入後實際情況調整）
        if site == "pyramid" and "/account" in url:
            return True
        if site == "goodinfo" and "Member" in url:
            return True
        if site == "tdcc":
            # 集保可不登入，跳過等待
            return True
        # 顯示進度
        elapsed = int(time.time() - start)
        print(f"  ...still waiting ({elapsed}s elapsed, current URL: {url})", end="\r")
    return False


def show_status() -> None:
    """列出所有站點 session 狀態。"""
    store = SessionStore()
    cred = CredentialManager()
    print("=== Session Status ===\n")
    for site in ("pyramid", "goodinfo", "tdcc"):
        st = store.status(site)
        print(f"[{site}] {st}")
    print("\n=== Credentials (from .env) ===\n")
    summary = cred.summary()
    for key, present in summary.items():
        marker = "✓" if present else "✗"
        print(f"  {marker} {key}")


def main():
    p = argparse.ArgumentParser(description="Auth setup for browser-based scrapers")
    p.add_argument("--site", choices=["pyramid", "goodinfo", "tdcc", "all", "status"],
                   default="status",
                   help="要登入的站點；status = 只看狀態")
    p.add_argument("--headless", action="store_true",
                   help="無頭模式（debug 用，預設為 headed）")
    args = p.parse_args()

    if args.site == "status":
        show_status()
        return

    if args.site == "all":
        for site in ("pyramid", "goodinfo", "tdcc"):
            try:
                asyncio.run(login_one_site(site, headless=args.headless))
            except KeyboardInterrupt:
                print(f"\n[{site}] Aborted by user.")
                return
        return

    asyncio.run(login_one_site(args.site, headless=args.headless))


if __name__ == "__main__":
    main()