"""
Stage D — 純 HTTP 驗證 MoneyDJ 籌碼頁面（使用者 9/22、9/23 指認的免登入來源）
  zcj = 籌碼分佈（400/600/800/1000 張大戶分級，多週歷史）
  zck = 董監持股
  zcn = 融資融券
  ZG_EI = 融資使用率排行
"""
import re
import time
import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")
BASE = "https://www.moneydj.com"


def get(url, referer=None):
    s = requests.Session()
    s.headers.update({
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        "Accept-Language": "zh-TW,zh;q=0.9",
    })
    if referer:
        s.headers["Referer"] = referer
    r = s.get(url, timeout=30)
    return r


def tables(html):
    """把 HTML 表格抓成 (表頭, 前幾列)。"""
    out = []
    for m in re.finditer(r"<table[^>]*>(.*?)</table>", html, re.S | re.I):
        block = m.group(1)
        rows = []
        for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", block, re.S | re.I):
            cells = []
            for cm in re.finditer(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S | re.I):
                t = re.sub(r"<[^>]+>", " ", cm.group(1))
                t = re.sub(r"&nbsp;|&#160;", " ", t)
                t = re.sub(r"\s+", " ", t).strip()
                cells.append(t)
            if any(c for c in cells):
                rows.append(cells)
        if rows:
            out.append(rows)
    return out


def report(label, url, referer):
    try:
        r = get(url, referer)
    except Exception as e:
        print(f"  {label:22s} ERR {type(e).__name__}: {str(e)[:80]}")
        return
    html = r.content.decode("utf-8", errors="replace")
    print(f"\n  === {label} ===")
    print(f"  http={r.status_code} len={len(r.content)} final={r.url[:80]}")
    if "sso/signin" in r.url or "Sign in Page" in html[:3000]:
        print("  !! 導向 SSO 登入頁")
        return
    ts = tables(html)
    print(f"  tables={len(ts)}")
    for i, rows in enumerate(ts[:3]):
        print(f"    table{i}: rows={len(rows)}")
        for row in rows[:4]:
            print(f"      {row[:13]}")


print("=" * 78)
print("MoneyDJ 籌碼頁面（純 requests，免登入、免 Playwright）")
print("=" * 78)
for code in ("2330", "2454"):
    stock = f"{BASE}/Z/ZC/ZCX/ZCX_{code}.djhtm"
    report(f"{code} 籌碼分佈 zcj", f"{BASE}/z/zc/zcj/zcj_{code}.djhtm", stock)
    time.sleep(3)
    report(f"{code} 董監持股 zck", f"{BASE}/z/zc/zck/zck_{code}.djhtm", stock)
    time.sleep(3)
    report(f"{code} 融資融券 zcn", f"{BASE}/z/zc/zcn/zcn_{code}.djhtm", stock)
    time.sleep(3)
    report(f"{code} 法人持股 zcl", f"{BASE}/z/zc/zcl/zcl_{code}.djhtm", stock)
    time.sleep(3)

report("融資使用率排行 ZG_EI", f"{BASE}/Z/ZG/ZG_EI.djhtm", f"{BASE}/")
time.sleep(3)
report("K線歷史頁 ZCW_2330", f"{BASE}/Z/ZC/ZCW/ZCW_2330.djhtm", f"{BASE}/Z/ZC/ZCX/ZCX_2330.djhtm")
