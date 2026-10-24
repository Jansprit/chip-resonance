"""
Stage E — MoneyDJ 籌碼頁面精準解析（去 script 汙染、完整欄位、多週歷史參數）
"""
import re
import time
import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")
BASE = "https://www.moneydj.com"
OUT = []


def clean(t):
    t = re.sub(r"<script.*?</script>", " ", t, flags=re.S | re.I)
    t = re.sub(r"<style.*?</style>", " ", t, flags=re.S | re.I)
    t = re.sub(r"<!--.*?-->", " ", t, flags=re.S)
    t = re.sub(r"<[^>]+>", " ", t)
    t = t.replace("&nbsp;", " ").replace("&amp;", "&")
    return re.sub(r"\s+", " ", t).strip()


def get_tables(html):
    html2 = re.sub(r"<script.*?</script>", " ", html, flags=re.S | re.I)
    out = []
    for m in re.finditer(r"<table[^>]*>(.*?)</table>", html2, re.S | re.I):
        block = m.group(1)
        rows = []
        for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", block, re.S | re.I):
            cells = [clean(c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S | re.I)]
            if any(cells):
                rows.append(cells)
        if rows:
            out.append(rows)
    return out


def show(label, url, referer, max_rows=14):
    s = requests.Session()
    s.headers.update({
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        "Accept-Language": "zh-TW,zh;q=0.9",
        "Referer": referer,
    })
    try:
        r = s.get(url, timeout=30)
    except Exception as e:
        OUT.append(f"{label} ERR {e}")
        return
    html = r.content.decode("utf-8", errors="replace")
    OUT.append("=" * 74)
    OUT.append(f"{label}\n  http={r.status_code} len={len(r.content)} final={r.url}")
    if "sso/signin" in r.url:
        OUT.append("  !! SSO")
        return
    ts = get_tables(html)
    OUT.append(f"  tables={len(ts)}")
    for i, rows in enumerate(ts[:3]):
        OUT.append(f"  --- table{i} ({len(rows)} rows) ---")
        for row in rows[:max_rows]:
            OUT.append("    " + " | ".join(row[:14]))


stock2330 = f"{BASE}/Z/ZC/ZCX/ZCX_2330.djhtm"
for code in ("2330", "2454"):
    stock = f"{BASE}/Z/ZC/ZCX/ZCX_{code}.djhtm"
    show(f"{code} 籌碼分佈 zcj", f"{BASE}/z/zc/zcj/zcj_{code}.djhtm", stock)
    time.sleep(3)
    show(f"{code} 董監持股 zck", f"{BASE}/z/zc/zck/zck_{code}.djhtm", stock)
    time.sleep(3)
    show(f"{code} 融資融券 zcn", f"{BASE}/z/zc/zcn/zcn_{code}.djhtm", stock)
    time.sleep(3)
    show(f"{code} 法人持股 zcl", f"{BASE}/z/zc/zcl/zcl_{code}.djhtm", stock)
    time.sleep(3)

# 多週歷史?試日期參數
show("zcj 加日期參數", f"{BASE}/z/zc/zcj/zcj_2330.djhtm?date=20230901", stock2330)
time.sleep(3)
show("zcj 歷史頁 ZCJ_2330", f"{BASE}/Z/ZC/ZCJ/ZCJ_2330.djhtm", stock2330)
time.sleep(3)
show("融資使用率排行 ZG_EI", f"{BASE}/Z/ZG/ZG_EI.djhtm", f"{BASE}/")

open(r"E:\MiniMax_Desktop\Work01\chip_resonance\backend\data\local\_mdj2.txt",
     "w", encoding="utf-8").write("\n".join(OUT))
print("lines:", len(OUT))
