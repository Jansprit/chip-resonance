"""
Stage C — 真實瀏覽器（滑鼠移動 / 滾輪 / 點擊）驗證兩個「使用者明講過的免登入來源」
  1. 神秘金字塔 MoneyDJ 個股頁的「持股分級」多週歷史（使用者 9/22、9/23 兩次指認）
  2. 玩股網 融資券頁的「融資券使用率 / 當沖比」（使用者 9/22 指認）
"""
import asyncio
import json
import random
import re

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")


async def human_dance(page, rounds=5):
    vp = page.viewport_size
    for _ in range(rounds):
        await page.mouse.move(random.randint(80, vp["width"] - 80),
                             random.randint(80, vp["height"] - 80))
        await page.wait_for_timeout(random.randint(150, 450))
        await page.mouse.wheel(0, random.randint(200, 700))
        await page.wait_for_timeout(random.randint(250, 700))


async def dump_tables(page, label, limit=6):
    data = await page.evaluate(
        """(lim) => Array.from(document.querySelectorAll('table')).slice(0, lim).map((t, i) => {
            const heads = Array.from(t.querySelectorAll('tr')[0]?.querySelectorAll('th,td') || [])
                .map(x => x.innerText.trim().replace(/\\s+/g,' ')).filter(Boolean).slice(0, 14);
            const rows = Array.from(t.querySelectorAll('tbody tr, tr')).slice(1, 5).map(r =>
                Array.from(r.querySelectorAll('td,th')).map(x => x.innerText.trim().replace(/\\s+/g,' ')).slice(0, 14));
            return {i, heads, rows};
        })""",
        limit,
    )
    print(f"  [{label}] tables={len(data)}")
    for t in data:
        if not t["heads"] and not t["rows"]:
            continue
        print(f"    table{t['i']} heads={t['heads']}")
        for r in t["rows"]:
            if any(c for c in r):
                print(f"       row: {r}")
    return data


async def probe_moneydj(p):
    print("=" * 78)
    print("MoneyDJ 個股頁 — 持股分級（使用者 9/22、9/23 指認免登入可見多週歷史）")
    print("=" * 78)
    browser = await p.chromium.launch(headless=True)
    ctx = await browser.new_context(
        locale="zh-TW", timezone_id="Asia/Taipei",
        viewport={"width": 1440, "height": 900}, user_agent=UA,
        extra_http_headers={"Accept-Language": "zh-TW,zh;q=0.9"},
    )
    ctx.set_default_timeout(45000)
    page = await ctx.new_page()

    api = []
    page.on("response", lambda r: api.append((r.status, r.url[:120]))
            if "moneydj.com" in r.url and re.search(r"\.(do|jsp|ashx|json)|djbcd|api", r.url) else None)

    for code in ("2330", "2454"):
        api.clear()
        print(f"\n--- 個股頁 {code} ---")
        try:
            r = await page.goto(f"https://www.moneydj.com/Z/ZC/ZCX/ZCX_{code}.djhtm",
                                wait_until="domcontentloaded")
            print("  http:", r.status if r else "?", "| title:", (await page.title())[:50])
        except Exception as e:
            print("  nav ERR", type(e).__name__, str(e)[:100])
            continue
        await human_dance(page, 8)
        await page.wait_for_timeout(4000)
        # 找頁面上含「持股」的連結並點擊
        links = await page.evaluate(
            """() => Array.from(document.querySelectorAll('a')).map(a => ({
                    t: (a.innerText||'').replace(/\\s+/g,' ').trim(),
                    h: a.getAttribute('href')||''
               })).filter(x => /持股|分級|籌碼|三大法人|融資/.test(x.t)).slice(0, 12)"""
        )
        print("  相關連結:", json.dumps(links, ensure_ascii=False)[:400])
        for lk in links[:3]:
            try:
                await page.goto("https://www.moneydj.com" + lk["h"]
                                if lk["h"].startswith("/") else lk["h"],
                                wait_until="domcontentloaded")
                await human_dance(page, 4)
                await page.wait_for_timeout(2500)
                print(f"  → 點開 {lk['t'][:30]} / {lk['h'][:60]}")
                await dump_tables(page, lk["t"][:20], limit=5)
                break
            except Exception as e:
                print("   導覽失敗", type(e).__name__, str(e)[:70])
        if not links:
            await dump_tables(page, f"{code} 主頁", limit=6)
        print("  XHR:", api[:10])
    await ctx.close()
    await browser.close()


async def probe_wantgoo(p):
    print("\n" + "=" * 78)
    print("玩股網 — 融資券使用率 / 當沖比（使用者 9/22 指認免登入可取得）")
    print("=" * 78)
    browser = await p.chromium.launch(headless=True)
    ctx = await browser.new_context(
        locale="zh-TW", timezone_id="Asia/Taipei",
        viewport={"width": 1440, "height": 900}, user_agent=UA,
        extra_http_headers={"Accept-Language": "zh-TW,zh;q=0.9"},
    )
    ctx.set_default_timeout(45000)
    page = await ctx.new_page()

    api = []
    page.on("response", lambda r: api.append((r.status, len(r.content() or b""), r.url[:120]))
            if "wantgoo.com" in r.url and ("-data" in r.url or "/investrue/" in r.url) else None)

    url = "https://www.wantgoo.com/stock/2330/margin-trading/synopsis"
    await page.goto(url, wait_until="domcontentloaded")
    print("  title:", (await page.title())[:50])
    await human_dance(page, 6)
    await page.wait_for_timeout(6000)
    await dump_tables(page, "融資券變化", limit=6)

    # 點擊頁面上所有可點的元素,看有沒有觸發資料載入
    print("  點擊可互動元素以觸發 JS 載入…")
    for sel in ("a[href*='margin']", "a[href*='trading']", "button", ".tab", "li[role='tab']"):
        els = await page.query_selector_all(sel)
        for el in els[:4]:
            try:
                await el.scroll_into_view_if_needed()
                await el.click(timeout=2500)
                await page.wait_for_timeout(1200)
            except Exception:
                pass
    await page.wait_for_timeout(5000)
    await dump_tables(page, "互動後", limit=6)
    print("  API 呼叫:")
    for st, ln, u in api[:14]:
        print(f"    [{st}] len={ln} {u}")
    await ctx.close()
    await browser.close()


async def main():
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        for fn in (probe_moneydj, probe_wantgoo):
            try:
                await fn(p)
            except Exception as e:
                print(f"!! {fn.__name__}: {type(e).__name__}: {e}")


asyncio.run(main())
