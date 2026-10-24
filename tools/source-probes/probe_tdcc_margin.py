"""
Stage H — 補齊 F5/F6/F9 缺口
  1. 集保開放資料其他 dataset id（股東人數 → F6）
  2. 證交所當沖成交（→ F9 dt_ratio）
  3. TWSE RWD 月線（官方價格歷史）
  4. TWSE 集保股東人數
"""
import json
import re
import time
import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")
H = {"User-Agent": UA, "Accept": "application/json", "Referer": "https://www.twse.com.tw/"}
OUT = []


def j(label, r, n=280):
    b = r.content
    line = f"  {label:36s} http={r.status_code} len={len(b):8d}"
    try:
        o = r.json()
        if isinstance(o, list):
            line += f" list[{len(o)}] {json.dumps(o[0], ensure_ascii=False)[:n] if o else '-'}"
        elif isinstance(o, dict):
            if "stat" in o:
                line += f" stat={o.get('stat')} title={str(o.get('title'))[:36]}"
                d = o.get("data") or []
                if isinstance(d, list) and d:
                    line += f"\n      fields={d[0] if isinstance(d[0],str) else json.dumps(d[0],ensure_ascii=False)[:n]}"
                    if len(d) > 1:
                        line += f"\n      row1={json.dumps(d[1], ensure_ascii=False)[:n]}"
            else:
                line += f" {json.dumps(o, ensure_ascii=False)[:n]}"
    except Exception:
        t = re.sub(r"<[^>]+>", " ", b[:200].decode("utf-8", errors="replace"))
        line += f" :: {re.sub(chr(92)+'s+',' ',t).strip()[:90]}"
    OUT.append(line)


print("1. 集保開放資料 dataset id 清單")
for i in list(range(1, 12)):
    url = f"https://opendata.tdcc.com.tw/getOD.ashx?id={i}&type=csv"
    try:
        r = requests.get(url, timeout=40, headers={"User-Agent": UA})
        head = r.content[:120].decode("utf-8", errors="replace").replace("\r", "").replace("\n", " | ")
        OUT.append(f"  id={i:<3d} http={r.status_code} len={len(r.content):9d} :: {head[:110]}")
    except Exception as e:
        OUT.append(f"  id={i:<3d} ERR {type(e).__name__}: {str(e)[:60]}")
    time.sleep(1.5)

print("2. 證交所 當沖 / 市場成交統計")
for label, url in [
    ("RWD TWT93U", "https://www.twse.com.tw/rwd/zh/afterTrading/TWT93U?date=20261022&response=json"),
    ("RWD MI_DAY", "https://www.twse.com.tw/rwd/zh/afterTrading/MI_DAY?date=20261022&response=json"),
    ("RWD MI_MARGN2", "https://www.twse.com.tw/rwd/zh/afterTrading/MI_MARGN?date=20261022&selectType=ALL&response=json"),
    ("RWD STOCK_DAY 月線", "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?date=20260101&stockNo=2330&response=json"),
    ("RWD TWT47U 週", "https://www.twse.com.tw/rwd/zh/afterTrading/TWT47U?date=20261022&response=json"),
    ("openapi TWT93U", "https://openapi.twse.com.tw/v1/exchangeReport/TWT93U"),
    ("openapi MI_MARGN 日", "https://openapi.twse.com.tw/v1/exchangeReport/MI_MARGN"),
    ("RWD 個股當沖 TWT93U", "https://www.twse.com.tw/rwd/zh/afterTrading/TWT93U?date=20261022&selectType=ALLBUT0999&response=json"),
    ("RWD ST43 成交統計", "https://www.twse.com.tw/rwd/zh/fund/BFI82U?date=20261022&response=json"),
    ("RWD 每日成交金額", "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date=20261022&type=ALL&response=json"),
]:
    try:
        j(label, requests.get(url, timeout=40, headers=H), n=200)
    except Exception as e:
        OUT.append(f"  {label:36s} ERR {type(e).__name__}: {str(e)[:70]}")
    time.sleep(1.5)

print("3. 集保 股東人數 / 週分析（openapi 其他路徑）")
for label, url in [
    ("集保 1-1 全市場", "https://opendata.tdcc.com.tw/getOD.ashx?id=1-1&type=csv"),
    ("集保 1-3", "https://opendata.tdcc.com.tw/getOD.ashx?id=1-3&type=csv"),
    ("集保 1-4", "https://opendata.tdcc.com.tw/getOD.ashx?id=1-4&type=csv"),
    ("集保 1-5 持股分級", "https://opendata.tdcc.com.tw/getOD.ashx?id=1-5&type=csv"),
    ("集保 6-1 股東人數", "https://opendata.tdcc.com.tw/getOD.ashx?id=6-1&type=csv"),
    ("集保 id=1 list", "https://opendata.tdcc.com.tw/api/v1/datastore"),
]:
    try:
        r = requests.get(url, timeout=40, headers={"User-Agent": UA})
        head = r.content[:140].decode("utf-8", errors="replace").replace("\r", "").replace("\n", " | ")
        OUT.append(f"  {label:26s} http={r.status_code} len={len(r.content):9d} :: {head[:120]}")
    except Exception as e:
        OUT.append(f"  {label:26s} ERR {type(e).__name__}: {str(e)[:60]}")
    time.sleep(1.5)

open(r"E:\MiniMax_Desktop\Work01\chip_resonance\backend\data\local\_src3.txt",
     "w", encoding="utf-8").write("\n".join(OUT))
print("done")
