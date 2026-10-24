"""
Stage A — 純 HTTP 快速驗證（不用瀏覽器）
1. Yahoo Finance v8/finance/chart（使用者 9/21 提供的憑證註解「已驗證可用,無需 key」）
2. TWSE 官方信用交易（融資券/當沖）API
3. FinMind TaiwanStockShareholding 免費管道
4. TPEx 官方融資券 API
"""
import json
import time
import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")


def show(label, r, keys=None, n=260):
    body = r.content
    ct = r.headers.get("Content-Type", "")
    print(f"  {label:38s} http={r.status_code} len={len(body):9d} ct={ct[:40]}")
    try:
        j = r.json()
        if isinstance(j, list):
            print(f"      list[{len(j)}] first={json.dumps(j[0], ensure_ascii=False)[:n] if j else '-'}")
        elif isinstance(j, dict):
            ks = list(j.keys())
            print(f"      dict keys={ks[:8]}")
            if "chart" in j:
                ch = j["chart"]
                err = ch.get("error")
                res = (ch.get("result") or [None])[0]
                if err:
                    print(f"      chart.error={err}")
                if res:
                    ts = res.get("timestamp") or []
                    q = (res.get("indicators", {}).get("quote") or [{}])[0]
                    cl = q.get("close") or []
                    print(f"      bars={len(ts)} first_ts={ts[0] if ts else '-'} "
                          f"last_ts={ts[-1] if ts else '-'} closes={len(cl)}")
                    print(f"      meta={json.dumps(res.get('meta', {}), ensure_ascii=False)[:n]}")
            else:
                print(f"      {json.dumps(j, ensure_ascii=False)[:n]}")
    except Exception:
        print(f"      raw: {body[:160]!r}")


print("=" * 78)
print("1. Yahoo Finance v8/finance/chart（免 key）")
print("=" * 78)
for host in ("query1.finance.yahoo.com", "query2.finance.yahoo.com"):
    for sym in ("2330.TW", "2454.TW"):
        url = f"https://{host}/v8/finance/chart/{sym}?range=2y&interval=1d"
        try:
            r = requests.get(url, timeout=30, headers={"User-Agent": UA})
            show(f"{host} {sym}", r)
        except Exception as e:
            print(f"  {host} {sym} ERR {type(e).__name__}: {str(e)[:80]}")
        time.sleep(1.5)

print("\n" + "=" * 78)
print("2. TWSE 官方 API（各種）")
print("=" * 78)
twse = [
    ("STOCK_DAY_ALL", "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"),
    ("MI_INDEX", "https://openapi.twse.com.tw/v1/exchangeReport/MI_INDEX"),
    ("BWIBBU_d 融資券", "https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_d"),
    ("TWTB4U 當沖", "https://openapi.twse.com.tw/v1/exchangeReport/TWTB4U"),
    ("BFI82U 分線", "https://openapi.twse.com.tw/v1/exchangeReport/BFI82U"),
    ("T86 三大法人", "https://openapi.twse.com.tw/v1/fund/T86"),
    ("TWT47U 週成交", "https://openapi.twse.com.tw/v1/exchangeReport/TWT47U"),
]
for label, url in twse:
    try:
        r = requests.get(url, timeout=30, headers={"User-Agent": UA})
        show(label, r, n=200)
    except Exception as e:
        print(f"  {label} ERR {type(e).__name__}: {str(e)[:80]}")
    time.sleep(1.2)

print("\n" + "=" * 78)
print("3. TPEx 官方 API")
print("=" * 78)
for label, url in [
    ("融資券", "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_L"),
    ("當沖", "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_L"),
    ("三大法人", "https://www.tpex.org.tw/openapi/v1/fund/T86"),
    ("基本資料", "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_L"),
]:
    try:
        r = requests.get(url, timeout=30, headers={"User-Agent": UA})
        show(label, r, n=200)
    except Exception as e:
        print(f"  {label} ERR {type(e).__name__}: {str(e)[:80]}")
    time.sleep(1.2)

print("\n" + "=" * 78)
print("4. FinMind TaiwanStockShareholding（使用者 9/23 提過的免費管道）")
print("=" * 78)
for label, qs in [
    ("shareholding+token", "dataset=TaiwanStockShareholding&stock_id=2330&start_date=2026-01-01&end_date=2026-10-24&token=d94cru1r01qj2cibpru0d94cru1r01qj2cibprug"),
    ("shareholding no-token", "dataset=TaiwanStockShareholding&stock_id=2330&start_date=2026-01-01&end_date=2026-10-24"),
    ("price+token", "dataset=TaiwanStockPrice&stock_id=2330&start_date=2026-01-01&end_date=2026-10-24&token=d94cru1r01qj2cibpru0d94cru1r01qj2cibprug"),
]:
    try:
        r = requests.get(f"https://api.finmindtrade.com/api/v4/data?{qs}",
                         timeout=30, headers={"User-Agent": UA})
        show(label, r, n=220)
    except Exception as e:
        print(f"  {label} ERR {type(e).__name__}: {str(e)[:80]}")
    time.sleep(1.2)
