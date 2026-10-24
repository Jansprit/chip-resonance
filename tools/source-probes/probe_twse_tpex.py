"""
Stage B — TWSE 官方 RWD 端點（融資券/當沖/三大法人/月線）+ Finnhub + Yahoo 細節
"""
import json
import time
import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")
H = {"User-Agent": UA, "Accept": "application/json", "Referer": "https://www.twse.com.tw/"}


def show(label, r, n=300):
    b = r.content
    print(f"  {label:34s} http={r.status_code} len={len(b):8d} ct={r.headers.get('Content-Type','')[:32]}")
    try:
        j = r.json()
        if isinstance(j, list):
            print(f"      list[{len(j)}] {json.dumps(j[0], ensure_ascii=False)[:n] if j else '-'}")
        elif isinstance(j, dict):
            if "stat" in j:
                print(f"      stat={j.get('stat')} date={j.get('date')} title={str(j.get('title'))[:40]}")
                data = j.get("data") or []
                if isinstance(data, list) and data:
                    print(f"      fields={data[0] if isinstance(data[0], str) else json.dumps(data[0], ensure_ascii=False)[:n]}")
                    for row in data[1:3]:
                        print(f"      row: {json.dumps(row, ensure_ascii=False)[:n]}")
            else:
                print(f"      {json.dumps(j, ensure_ascii=False)[:n]}")
    except Exception:
        print(f"      raw: {b[:120]!r}")


print("=" * 78)
print("TWSE RWD 端點（F9 融資券/當沖、F3 法人、F5 基本面 的官方來源）")
print("=" * 78)
rwd = [
    ("MI_MARGN 融資券餘額", "https://www.twse.com.tw/rwd/zh/afterTrading/MI_MARGN?date=20261022&response=json"),
    ("TWT93U 當沖成交", "https://www.twse.com.tw/rwd/zh/afterTrading/TWT93U?date=20261022&response=json"),
    ("T86 三大法人", "https://www.twse.com.tw/rwd/zh/fund/T86?date=20261022&response=json"),
    ("BWIBBU_d 基本資料", "https://www.twse.com.tw/rwd/zh/afterTrading/BWIBBU_d?date=20261022&response=json"),
    ("TWT47U 週成交", "https://www.twse.com.tw/rwd/zh/afterTrading/TWT47U?date=20261022&response=json"),
    ("MI_INDEX 指數", "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date=20261022&type=ALL&response=json"),
    ("T86 法人(全) 近月", "https://www.twse.com.tw/rwd/zh/fund/T86?date=20261001&selectType=ALLBUT0999&response=json"),
]
for label, url in rwd:
    try:
        show(label, requests.get(url, timeout=30, headers=H))
    except Exception as e:
        print(f"  {label} ERR {type(e).__name__}: {str(e)[:80]}")
    time.sleep(1.5)

print("\n" + "=" * 78)
print("TWSE openapi 月線（每檔每月 1 個請求 → 價格歷史的官方替代）")
print("=" * 78)
for label, url in [
    ("STOCK_DAY 2330 202601", "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY?response=json&date=20260101&stockNo=2330"),
    ("STOCK_DAY 2454 202601", "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY?response=json&date=20260101&stockNo=2454"),
    ("BWIBBU_d 全市場", "https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_d"),
    ("TWTB4U 全部", "https://openapi.twse.com.tw/v1/exchangeReport/TWTB4U"),
    ("MI_MARGN openapi", "https://openapi.twse.com.tw/v1/exchangeReport/MI_MARGN"),
    ("TWT93U openapi", "https://openapi.twse.com.tw/v1/exchangeReport/TWT93U"),
    ("T86 openapi", "https://openapi.twse.com.tw/v1/fund/T86"),
    ("TWT49U 外資持股", "https://openapi.twse.com.tw/v1/fund/TWT49U"),
    ("TWT44U 融資融券", "https://openapi.twse.com.tw/v1/exchangeReport/TWT44U"),
    ("T86 三大法人股", "https://openapi.twse.com.tw/v1/fund/T86"),
]:
    try:
        show(label, requests.get(url, timeout=30, headers={"User-Agent": UA}), n=260)
    except Exception as e:
        print(f"  {label} ERR {type(e).__name__}: {str(e)[:80]}")
    time.sleep(1.2)

print("\n" + "=" * 78)
print("Finnhub（使用者提供的 key 是 Finnhub 的）")
print("=" * 78)
FK = "d94cru1r01qj2cibpru0d94cru1r01qj2cibprug"
for label, url in [
    ("quote 2330.TW", f"https://finnhub.io/api/v1/quote?symbol=2330.TW&token={FK}"),
    ("candle 2330.TW", f"https://finnhub.io/api/v1/stock/candle?symbol=2330.TW&resolution=D&from=1759000000&to=1792700000&token={FK}"),
    ("stock symbol TW", f"https://finnhub.io/api/v1/stock/symbol?exchange=TW&token={FK}"),
]:
    try:
        show(label, requests.get(url, timeout=30, headers={"User-Agent": UA}), n=240)
    except Exception as e:
        print(f"  {label} ERR {type(e).__name__}: {str(e)[:80]}")
    time.sleep(1.2)

print("\n" + "=" * 78)
print("Yahoo Finance 細節（欄位、能否一次多檔、能否取更長歷史）")
print("=" * 78)
for label, url in [
    ("2330.TW range=5y", "https://query1.finance.yahoo.com/v8/finance/chart/2330.TW?range=5y&interval=1d"),
    ("2330.TW range=10y", "https://query1.finance.yahoo.com/v8/finance/chart/2330.TW?range=10y&interval=1wk"),
    ("2454.TW range=1mo", "https://query1.finance.yahoo.com/v8/finance/chart/2454.TW?range=1mo&interval=1d"),
]:
    try:
        r = requests.get(url, timeout=30, headers={"User-Agent": UA})
        j = r.json()
        res = (j.get("chart", {}).get("result") or [None])[0]
        if res:
            q = (res.get("indicators", {}).get("quote") or [{}])[0]
            print(f"  {label:24s} http={r.status_code} bars={len(res.get('timestamp') or [])} "
                  f"quote_keys={list(q.keys())} adjclose={'adjclose' in res.get('indicators', {})}")
            for k, v in q.items():
                print(f"        {k}: {v[:3] if isinstance(v, list) else v}")
    except Exception as e:
        print(f"  {label} ERR {type(e).__name__}: {str(e)[:90]}")
    time.sleep(1.2)
