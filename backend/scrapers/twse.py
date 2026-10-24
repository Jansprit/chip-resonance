"""
scrapers/twse.py — 台灣證券交易所 OpenAPI

資料源（皆為公開、不需 API key）：
- STOCK_DAY_ALL        每日個股收盤行情（上市、約 1100 檔）
- MI_INDEX             市場指數（TAIEX、各類股指數）
- MI_MARGN             融資融券餘額與限額 → F9 的 margin_pct / short_ratio
- BWIBBU_d             個股本益比、殖利率、股利年度 → F5 的 yield_now
- t187ap03_L           公司基本資料（含產業別 CID）→ F2 產業成分股清單的基礎
- t05_st10             暫停交易 / 全額交割 / 警示股清單（從 MOPS 取得）

另含 Yahoo Finance v8/finance/chart 的價格歷史解析（免 key、CI 友善），
作為 FinMind（付費牆）與 MoneyDJ（需會員）的替代來源。

節流：3 秒/次（避免被當作爬蟲），單日上限 500 次。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .base import (
    HttpClient,
    RateLimiter,
    RetryPolicy,
    SourceHealth,
    write_json,
    taipei_now_iso,
)


# TWSE OpenAPI 端點
TWSE_BASE = "https://openapi.twse.com.tw/v1"
ENDPOINT_STOCK_DAY_ALL = f"{TWSE_BASE}/exchangeReport/STOCK_DAY_ALL"
ENDPOINT_MI_INDEX = f"{TWSE_BASE}/exchangeReport/MI_INDEX"
ENDPOINT_MARGIN_BALANCE = f"{TWSE_BASE}/exchangeReport/MI_MARGN"
ENDPOINT_VALUATION = f"{TWSE_BASE}/exchangeReport/BWIBBU_d"
ENDPOINT_COMPANY_BASIC = f"{TWSE_BASE}/opendata/t187ap03_L"

# Yahoo Finance v8（免 key；2026-10-24 實測本機與 CI 皆可）
ENDPOINT_YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{code}.{suffix}"

# Yahoo 的台股代號後綴：
#   .TW  → 上市（TWSE）
#   .TWO → 上櫃（TPEx）
#
# ⚠️ 2026-10-25 實測：只試 .TW 會讓上櫃股（5347 / 4743 / 4128 等）
#    全部拿到 404 "symbol may be delisted"，
#    看起來像「股票下市了」，實際上只是後綴不對。
#    修好之後 43/43 檔都能取到歷史 K 線（原本 40/43）。
YAHOO_SUFFIXES = ("TW", "TWO")



def create_twse_client() -> HttpClient:
    """建立 TWSE 的 HttpClient，含節流與健康狀態。"""
    rl = RateLimiter(min_interval=3.0, source_name="twse")
    health = SourceHealth(source_name="twse", daily_quota=500)
    return HttpClient(rate_limiter=rl, health=health, retry=RetryPolicy())


def roc_date_to_iso(roc_date: str | int) -> str:
    """
    民國日期 (e.g. 1150918) 轉 ISO 8601 (e.g. 2026-09-18)。
    民國年份 = 西元年份 - 1911。
    """
    s = str(roc_date).strip()
    if len(s) != 7 or not s.isdigit():
        return str(roc_date)
    roc_year = int(s[:3])
    month = int(s[3:5])
    day = int(s[5:7])
    return f"{roc_year + 1911:04d}-{month:02d}-{day:02d}"


def parse_stock_daily_all(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    解析 STOCK_DAY_ALL 的回傳為標準 STOCK_UNIVERSE 相容的結構。

    回傳每筆的欄位：
        code           — 股票代號（字串）
        name           — 公司簡稱
        exchange       — "TWSE"（固定）
        date           — ISO 日期
        price          — 收盤價
        open / high / low
        change         — 漲跌點數
        volume_lots    — 成交量（張）
        turnover       — 成交金額（元）
        transactions   — 成交筆數
    """
    if not raw or not isinstance(raw, list):
        return []

    parsed = []
    for row in raw:
        code = (row.get("Code") or "").strip()
        name = (row.get("Name") or "").strip()
        if not code or not name:
            continue

        def safe_float(key, default=0.0):
            v = row.get(key, "")
            if v == "" or v is None:
                return default
            try:
                return float(v)
            except (ValueError, TypeError):
                return default

        def safe_int(key, default=0):
            v = row.get(key, "")
            if v == "" or v is None:
                return default
            try:
                return int(float(v))
            except (ValueError, TypeError):
                return default

        # 過濾掉非普通股（權證、特別股、ETN 等）
        if not code.isdigit() or len(code) != 4:
            continue
        # TWSE 上市股票代號通常是 1101~9999 開頭，< 1100 多為權證
        if int(code) < 1100:
            continue

        parsed.append({
            "code": code,
            "name": name,
            "exchange": "TWSE",
            "date": roc_date_to_iso(row.get("Date", "")),
            "price": safe_float("ClosingPrice"),
            "open": safe_float("OpeningPrice"),
            "high": safe_float("HighestPrice"),
            "low": safe_float("LowestPrice"),
            "change": safe_float("Change"),
            "volume_lots": safe_int("TradeVolume"),
            "turnover": safe_int("TradeValue"),
            "transactions": safe_int("Transaction"),
        })
    return parsed


def parse_market_index(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """解析 MI_INDEX，回傳指數列表（去除「報酬」與「反向」相關衍生指數）。"""
    if not raw:
        return []
    parsed = []
    for row in raw:
        name = row.get("指數", "")
        # 只要主指數與類股指數，不要衍生（包含「報酬」「反向」「兩倍」「槓桿」）
        if any(x in name for x in ["報酬", "反向", "兩倍", "槓桿", "正2", "反1"]):
            continue
        try:
            value = float(str(row.get("收盤指數", "")).replace(",", ""))
            change_pct = float(str(row.get("漲跌百分比", "")).replace(",", ""))
        except ValueError:
            continue
        parsed.append({
            "date": roc_date_to_iso(row.get("日期", "")),
            "name": name,
            "value": value,
            "change_pct": change_pct,
        })
    return parsed


# ============ 高階函式：抓 + 寫 ============

def fetch_prices(client: HttpClient | None = None) -> list[dict[str, Any]]:
    """抓取當日 TWSE 上市股票行情。"""
    client = client or create_twse_client()
    raw = client.get_json(ENDPOINT_STOCK_DAY_ALL)
    return parse_stock_daily_all(raw)


def fetch_market_index(client: HttpClient | None = None) -> list[dict[str, Any]]:
    """抓取當日 TWSE 主要指數。"""
    client = client or create_twse_client()
    raw = client.get_json(ENDPOINT_MI_INDEX)
    return parse_market_index(raw)


def save_latest(
    data_dir: Path,
    prices: list[dict[str, Any]],
    market_index: list[dict[str, Any]],
    *,
    snapshot_date: str = "",
) -> dict[str, str]:
    """
    把抓到的資料寫到 data_dir/latest/ 與 data_dir/<YYYY-MM-DD>/。
    data_dir 應為 repo/data/（pipeline.py 傳入 repo/data）。
    回傳寫入的檔案路徑。
    """
    from .base import taipei_today
    written = {}
    snapshot_date = snapshot_date or taipei_today()

    latest_dir = data_dir / "latest"
    snapshot_dir = data_dir / snapshot_date
    latest_dir.mkdir(parents=True, exist_ok=True)
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    files = {
        "prices.json": prices,
        "market_index.json": market_index,
    }
    for name, data in files.items():
        latest_path = latest_dir / name
        snapshot_path = snapshot_dir / name
        write_json(latest_path, data)
        write_json(snapshot_path, data)
        written[name] = str(latest_path)

    return written


# ============ 官方端點：融資融券 / 基本資料 / 產業別 ============
# 2026-10-24 實測：以下三個端點皆為政府開放 API，單一請求涵蓋全市場，
# 且不擋 datacenter IP → 可以放進 CI 的 public 集合。

def _to_float(value: Any) -> float | None:
    """把 API 的字串欄位轉 float；空字串/非數字回 None（不可回 0）。"""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).replace(",", "").replace("%", "").strip()
    if not s or s in {"--", "-", "---"}:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def parse_margin_balance(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """
    解析 MI_MARGN（融資融券餘額）→ F9 所需的欄位。

    回傳 {code: {margin_balance, margin_limit, margin_pct, short_balance,
                 short_limit, short_pct}}

    **限額為 0 時 *_pct 必須是 None 而不是 0** ——
    0% 會讓 F9 誤判為「完全零槓桿」，比沒有資料更糟。
    """
    out: dict[str, dict[str, Any]] = {}
    for row in rows or []:
        code = str(row.get("股票代號", "")).strip()
        if not code:
            continue
        margin_balance = _to_float(row.get("融資今日餘額"))
        margin_limit = _to_float(row.get("融資限額"))
        short_balance = _to_float(row.get("融券今日餘額"))
        short_limit = _to_float(row.get("融券限額"))
        if margin_balance is None and short_balance is None:
            continue
        margin_pct = (margin_balance / margin_limit * 100) if (
            margin_balance is not None and margin_limit
        ) else None
        short_pct = (short_balance / short_limit * 100) if (
            short_balance is not None and short_limit
        ) else None
        out[code] = {
            "margin_balance": margin_balance,
            "margin_limit": margin_limit,
            "margin_pct": margin_pct,
            "short_balance": short_balance,
            "short_limit": short_limit,
            "short_pct": short_pct,
        }
    return out


def parse_valuation(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """
    解析 BWIBBU_d（本益比 / 殖利率 / 股利年度）→ F5 的 yield_now。

    回傳 {code: {close_price, yield_now, dividend_year, pe_ratio, pb_ratio}}

    **沒有殖利率時 yield_now 必須是 None**（0 會讓 F5 誤判為低殖利率）。
    """
    out: dict[str, dict[str, Any]] = {}
    for row in rows or []:
        code = str(row.get("Code", "")).strip()
        if not code:
            continue
        yield_now = _to_float(row.get("DividendYield"))
        dividend_year = _to_float(row.get("DividendYear"))
        entry = {
            "close_price": _to_float(row.get("ClosePrice")),
            "yield_now": yield_now,
            "dividend_year": int(dividend_year) if dividend_year else None,
            "pe_ratio": _to_float(row.get("PEratio")),
            "pb_ratio": _to_float(row.get("PBratio")),
        }
        if yield_now is None and entry["close_price"] is None:
            continue
        out[code] = entry
    return out


def parse_industry(rows: list[dict[str, Any]]) -> dict[str, str]:
    """
    解析 t187ap03_L（公司基本資料）→ 產業別 CID 清單。

    這是 F2「個股所屬 CID 的全體成分股」的成分股清單來源 ——
    原始需求文件指定由「金字塔 CID 參數」取得，
    而 TWSE 官方這份是同樣的分類編號且免費穩定。
    """
    out: dict[str, str] = {}
    for row in rows or []:
        code = str(row.get("公司代號", "")).strip()
        industry = str(row.get("產業別", "")).strip()
        if not code or not industry:
            continue
        out[code] = industry
    return out


# ============ 價格歷史（Yahoo Finance v8，免 key）============

def parse_yahoo_chart(
    payload: dict[str, Any],
    code: str,
) -> list[dict[str, Any]]:
    """
    解析 Yahoo Finance v8/finance/chart 回應 → 統一格式的日 K 線。

    回傳 [{date, open, high, low, close, volume}]，**依日期升冪**。
    原始回應是倒序（最新在前），這裡翻正。
    沒有收盤價的列（停牌 / 無成交）會被跳過。
    """
    try:
        chart = (payload or {}).get("chart") or {}
        if chart.get("error"):
            return []
        result = (chart.get("result") or [None])[0]
        if not result:
            return []
        timestamps = result.get("timestamp") or []
        quote = ((result.get("indicators") or {}).get("quote") or [{}])[0] or {}
    except (AttributeError, TypeError, IndexError):
        return []

    from datetime import datetime, timedelta, timezone
    tpe = timezone(timedelta(hours=8))

    def series(key: str) -> list[Any]:
        values = quote.get(key)
        return values if isinstance(values, list) else []

    opens = series("open")
    highs = series("high")
    lows = series("low")
    closes = series("close")
    volumes = series("volume")

    bars: list[dict[str, Any]] = []
    for i, ts in enumerate(timestamps):
        close = _to_float(closes[i]) if i < len(closes) else None
        if close is None:
            continue
        try:
            raw_ts = float(ts)
        except (TypeError, ValueError):
            continue
        # Yahoo 的 timestamp 是**秒**；但有些代理/端點會回毫秒。
        # 用量級判斷：1e11 秒 ≈ 公元 5138 年，1e11 毫秒 ≈ 1973 年，
        # 因此 < 1e11 視為秒、>= 1e11 視為毫秒。
        seconds = raw_ts / 1000 if raw_ts >= 1e11 else raw_ts
        try:
            day = datetime.fromtimestamp(seconds, tpe).strftime("%Y-%m-%d")
        except (TypeError, ValueError, OSError):
            continue
        bars.append({
            "date": day,
            "open": _to_float(opens[i]) if i < len(opens) else None,
            "high": _to_float(highs[i]) if i < len(highs) else None,
            "low": _to_float(lows[i]) if i < len(lows) else None,
            "close": close,
            "volume": _to_float(volumes[i]) if i < len(volumes) else None,
        })
    bars.sort(key=lambda b: b["date"])
    return bars


def fetch_margin_balance(client: HttpClient | None = None) -> dict[str, dict[str, Any]]:
    """抓融資融券餘額（單一請求涵蓋全市場）。"""
    client = client or create_twse_client()
    return parse_margin_balance(client.get_json(ENDPOINT_MARGIN_BALANCE))


def fetch_valuation(client: HttpClient | None = None) -> dict[str, dict[str, Any]]:
    """抓個股本益比 / 殖利率（單一請求涵蓋全市場）。"""
    client = client or create_twse_client()
    return parse_valuation(client.get_json(ENDPOINT_VALUATION))


def fetch_industry_map(client: HttpClient | None = None) -> dict[str, str]:
    """抓上市櫃公司基本資料 → 產業別 CID 清單。"""
    client = client or create_twse_client()
    return parse_industry(client.get_json(ENDPOINT_COMPANY_BASIC))


def create_yahoo_client() -> HttpClient:
    """Yahoo Finance 專用客戶端（快速失敗策略）。

    為什麼不用預設的指數退避？
    價格歷史是「每檔股票各打一次」的來源，單檔失敗只代表該檔沒資料。
    若沿用預設的 60s/300s/900s 退避，43 檔各失敗一次就會拖到數小時。
    這裡改成：失敗等 5 秒重試一次就不放棄，並把逾時壓到 20 秒。
    """
    rl = RateLimiter(min_interval=2.5, source_name="yahoo")
    health = SourceHealth(source_name="yahoo", daily_quota=500)
    return HttpClient(
        rate_limiter=rl,
        health=health,
        retry=RetryPolicy(max_retries=1, schedule=(5,)),
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
        ),
        timeout=20,
    )


def fetch_price_history(
    code: str,
    client: HttpClient | None = None,
    range_: str = "2y",
    interval: str = "1d",
) -> list[dict[str, Any]]:
    """
    抓單一股票的日 K 線（Yahoo v8，免 key）。

    風控：走 yahoo 專用的節流閥（2.5 秒/次、每日 500 次、快速失敗），
    43 檔約需 2 分鐘。

    **上市 / 上櫃兩種後綴都會試**（.TW → .TWO）：
    只試 .TW 會讓上櫃股整批 404，看起來像「股票下市」，
    實際上只是後綴不對（2026-10-25 實測：修好後 40/43 → 43/43）。
    """
    client = client or create_yahoo_client()
    for suffix in YAHOO_SUFFIXES:
        url = (f"{ENDPOINT_YAHOO_CHART.format(code=code, suffix=suffix)}"
               f"?range={range_}&interval={interval}")
        try:
            payload = client.get_json(url)
        except Exception:
            continue
        bars = parse_yahoo_chart(payload, code)
        if bars:
            return bars
    return []


if __name__ == "__main__":
    # 直接執行這個檔（python -m scrapers.twse）做 smoke test
    print("Fetching TWSE STOCK_DAY_ALL …")
    prices = fetch_prices()
    print(f"  Got {len(prices)} stocks")
    if prices:
        print(f"  Sample: {prices[0]['code']} {prices[0]['name']} = {prices[0]['price']}")

    print("Fetching TWSE MI_INDEX …")
    idx = fetch_market_index()
    print(f"  Got {len(idx)} indices")