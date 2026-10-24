import json
import re
import time
import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")
H = {"User-Agent": UA, "Accept": "application/json", "Referer": "https://www.twse.com.tw/"}
OUT = []


def j(label, r, n=300):
    b = r.content
    line = f"  {label:32s} http={r.status_code} len={len(b):8d}"
    try:
        o = r.json()
        if isinstance(o, dict) and "stat" in o:
            line += f" stat={o.get('stat')} title={str(o.get('title'))[:40]}"
            d = o.get("data") or []
            if isinstance(d, list) and d:
                line += f"\n      fields={d[0] if isinstance(d[0],str) else json.dumps(d[0],ensure_ascii=False)[:n]}"
                for row in d[1:3]:
                    line += f"\n      {json.dumps(row, ensure_ascii=False)[:n]}"
        elif isinstance(o, list):
            line += f" list[{len(o)}] {json.dumps(o[0], ensure_ascii=False)[:n] if o else '-'}"
        else:
            line += f" {json.dumps(o, ensure_ascii=False)[:n]}"
    except Exception:
        t = re.sub(r"<[^>]+>", " ", b[:160].decode("utf-8", errors="replace"))
        line += f" :: {re.sub(chr(92)+'s+',' ',t).strip()[:80]}"
    OUT.append(line)


print("1. 證交所 市場當沖統計")
for label, url in [
    ("FMTQIK 成交統計", "https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK?date=20261022&response=json"),
    ("FMTQIK 月", "https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK?date=20261001&response=json"),
    ("MI_INDEX 類別", "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date=20261022&type=ALLBUT0999&response=json"),
]:
    try:
        j(label, requests.get(url, timeout=40, headers=H))
    except Exception as e:
        OUT.append(f"  {label} ERR {e}")
    time.sleep(1.5)

print("2. TPEx 官方 API（融資券/當沖/法人）")
for label, url in [
    ("t187ap03_L 融資券", "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_L"),
    ("t187ap05_L 當沖", "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_L"),
    ("mopsfin_t187ap11_L", "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap11_L"),
    ("t187ap01_L 基本", "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap01_L"),
    ("每日收盤行情", "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"),
]:
    try:
        j(label, requests.get(url, timeout=40, headers={"User-Agent": UA}))
    except Exception as e:
        OUT.append(f"  {label} ERR {e}")
    time.sleep(1.5)

print("3. 集保 6-1 股東人數 欄位確認")
r = requests.get("https://opendata.tdcc.com.tw/getOD.ashx?id=6-1&type=csv",
                 timeout=40, headers={"User-Agent": UA})
txt = r.content.decode("utf-8-sig", errors="replace")
lines = txt.splitlines()
OUT.append(f"  6-1 rows={len(lines)} header={lines[0]}")
for l in lines[1:4]:
    OUT.append("    " + l)
# 找 2330
for l in lines:
    if l.startswith("2026") and ",2330," in l:
        OUT.append("    2330 → " + l)
        break

open(r"E:\MiniMax_Desktop\Work01\chip_resonance\backend\data\local\_src4.txt",
     "w", encoding="utf-8").write("\n".join(OUT))
print("done")
