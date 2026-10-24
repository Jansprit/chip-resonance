"""
Stage G — 真實瀏覽器（Playwright）測 MoneyDJ 對「非熱門股」是否也會被 SSO
這是使用者 9/22 明講的驗證方式：「你要用瀏覽器代理工具就可以驗證」
"""
import asyncio
import random
import re
import time

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")
BASE = "https://www.moneydj.com"
OUT = []


async def human(page, rounds=6):
    vp = page.viewport_size
    for _ in range(rounds):
        await page.mouse.move(random.randint(80, vp["width"] - 80),
                             random.randint(80, vp["height"] - 80))
        await page.wait_for_timeout(random.randint(200, 600))
        await page.mouse.wheel(0, random.randint(200, 700))
        await page.wait_for_timeout(random.randint(300, 800))


async def probe(p, code, gap):
    browser = await p.chromium.launch(headless=True)
    ctx = await browser.new_context(
        locale="zh-TW", timezone_id="Asia/Taipei",
        viewport={"width": 1440, "height": 900}, user_agent=UA,
        extra_http_headers={"Accept-Language": "zh-TW,zh;q=0.9"},
    )
    ctx.set_default_timeout(45000)
    page = await ctx.new_page()
    results = []
    try:
        # 先開個股頁（模擬真人從個股頁點進籌碼頁）
        await page.goto(f"{BASE}/Z/ZC/ZCX/ZCX_{code}.djhtm", wait_until="domcontentloaded")
        await human(page, 5)
        for label, path in [
            ("籌碼分佈 zcj", f"/z/zc/zcj/zcj_{code}.djhtm"),
            ("董監持股 zck", f"/z/zc/zck/zck_{code}.djhtm"),
            ("融資融券 zcn", f"/z/zc/zcn/zcn_{code}.djhtm"),
            ("持股分級 zcw", f"/z/zc/zcw/zcw_{code}.djhtm"),
        ]:
            await page.goto(BASE + path, wait_until="domcontentloaded")
            await human(page, 3)
            await page.wait_for_timeout(1500)
            url = page.url
            sso = "sso/signin" in url
            tables = await page.evaluate(
                """() => Array.from(document.querySelectorAll('table')).length"""
            )
            rows = await page.evaluate(
                """() => Array.from(document.querySelectorAll('tbody tr'))
                       .filter(tr => (tr.innerText||'').trim().length>0).length"""
            )
            results.append((label, sso, tables, rows))
            OUT.append(f"  {code} {label:14s} SSO={sso} tables={tables} rows={rows}")
            await asyncio.sleep(gap)
    except Exception as e:
        OUT.append(f"  {code} ERR {type(e).__name__}: {str(e)[:120]}")
    finally:
        await ctx.close()
        await browser.close()
    return results


async def main():
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        OUT.append("=" * 74)
        OUT.append("A. 瀏覽器 2330（熱門股,先前 requests 也成功）")
        await probe(p, "2330", 4)
        OUT.append("")
        OUT.append("=" * 74)
        OUT.append("B. 瀏覽器 2454（先前 requests 全部 SSO）— 決定性測試")
        await probe(p, "2454", 4)
        OUT.append("")
        OUT.append("=" * 74)
        OUT.append("C. 瀏覽器 5880（另一檔非熱門股）")
        await probe(p, "5880", 4)
    open(r"E:\MiniMax_Desktop\Work01\chip_resonance\backend\data\local\_mdj4.txt",
         "w", encoding="utf-8").write("\n".join(OUT))
    print("done")


asyncio.run(main())
