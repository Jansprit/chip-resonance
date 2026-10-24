"""
test_wantgoo.py — Tests for the Wantgoo (玩股網) scraper

對應 docs/2026-10-21-專案體檢報告.md BUG-03

BUG-03 根因：4 個頁面 URL 全錯（全部 404）
    /stock/{code}/balance-sheet            → 404
    /stock/{code}/financial/BS             → 404
    /stock/{code}/finance/balance_sheet    → 404
    /stock/{code}/institutional-investors  → 404

驗證：
- 頁面 URL 是對的（回歸防護，避免又改回 404 的路徑）
- 兩層表頭（colspan / rowspan）正確壓平
- 融資使用率 / 融券使用率 / 當沖率 解析正確
- 表格沒有資料列時必須回 error，**不得回 0**（0 是比沒有資料更糟的假訊號）

執行：python backend/tests/test_wantgoo.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.scrapers import wantgoo


# ===== before 參數契約（2026-10-25 實測）=====

def test_price_history_before_candidates_are_ordered_newest_first():
    """
    `before` 候選值必須由新到舊排列。

    實測（2026-10-25 01:30 TPE）：`before = 今天 00:00 台北` 會回 HTTP 400，
    但往前 1 天（昨天）就正常。伺服器的接受規則不透明，
    所以不能只押一個值，必須準備一串候選依序試。
    """
    cands = wantgoo.price_history_before_candidates()
    assert len(cands) >= 2, "至少要有今天與昨天兩個候選"
    assert cands == sorted(cands, reverse=True), "候選必須由新到舊"
    assert len(set(cands)) == len(cands), "候選不可重複"


def test_price_history_before_candidates_cover_multiple_days():
    """候選必須涵蓋多天（週末 / 連假都可能讓今天不成立）。"""
    cands = wantgoo.price_history_before_candidates()
    assert len(cands) >= 8, f"只準備了 {len(cands)} 個候選，不足以涵蓋連假"


def test_price_history_before_candidates_are_midnight_taipei():
    """每個候選都必須是「某一天 00:00 台北」的毫秒時間戳。"""
    from datetime import datetime, timedelta, timezone

    tpe = timezone(timedelta(hours=8))
    for ms in wantgoo.price_history_before_candidates():
        d = datetime.fromtimestamp(ms / 1000, tpe)
        assert (d.hour, d.minute, d.second, d.microsecond) == (0, 0, 0, 0), \
            f"{d.isoformat()} 不是 00:00"


def test_fetch_price_history_falls_back_when_first_candidate_is_rejected():
    """
    第一個候選被伺服器拒絕（400）時，必須自動往下一個候選試。

    這是實際發生過的故障：v0.3.1 固定用「今天 00:00」，
    在 2026-10-25 凌晨執行時整個玩股網價格來源直接失效。
    """
    attempted: list[str] = []

    class _FakeResponse:
        status_code = 200
        text = '[{"time": 1792598400000, "close": 2385.0}]'

    class _FakeClient:
        def get_text(self, url):
            attempted.append(url)
            if len(attempted) == 1:
                class _Bad:
                    status_code = 400
                    text = "400 - BadRequest"
                return _Bad().text
            return _FakeResponse.text

    result = wantgoo.fetch_price_history("2330", client=_FakeClient())
    assert len(attempted) >= 2, "第一個候選被拒後必須再試第二個"
    assert attempted[0] != attempted[1]
    assert result, "fallback 之後應該有拿到資料"


def test_fetch_price_history_raises_when_all_candidates_rejected():
    """所有候選都被拒時必須明確報錯（不可回空資料冒充成功）。"""
    class _FakeClient:
        def get_text(self, url):
            raise RuntimeError("400 - BadRequest")

    try:
        wantgoo.fetch_price_history("2330", client=_FakeClient())
    except Exception:
        return
    raise AssertionError("所有候選都失敗時必須拋例外")


# ===== 真實結構的 fixture（兩層表頭 + rowspan）=====

MARGIN_HTML = """
<html><body>
<table>
  <tr>
    <th rowspan=2>日期</th>
    <th colspan=3>融資</th>
    <th colspan=3>融券</th>
    <th rowspan=2>收盤價</th>
  </tr>
  <tr>
    <th>餘額</th><th>限額</th><th>使用率%</th>
    <th>餘額</th><th>限額</th><th>使用率%</th>
  </tr>
  <tr>
    <td>2026/10/22</td><td>100,000</td><td>500,000</td><td>20.00%</td>
    <td>5,000</td><td>200,000</td><td>2.50%</td><td>2420</td>
  </tr>
</table>
<table>
  <tr>
    <th>日期</th><th>資餘</th><th>資增</th><th>券餘</th><th>券增</th>
    <th>券資比%</th><th>資券互抵</th><th>當沖率%</th>
    <th>收盤價</th><th>漲跌%</th><th>成交量</th>
  </tr>
  <tr>
    <td>2026/10/22</td><td>100,000</td><td>-500</td><td>5,000</td><td>0</td>
    <td>5.00</td><td>0</td><td>38.50%</td><td>2420</td><td>0.50%</td><td>30,000</td>
  </tr>
</table>
</body></html>
"""

INSTITUTIONAL_HTML = """
<html><body>
<table>
  <tr>
    <th rowspan=2>日期</th>
    <th colspan=4>法人買賣超(張)</th>
    <th colspan=4>估計持股</th>
    <th colspan=3>持股比重(%)</th>
  </tr>
  <tr>
    <th>外資</th><th>投信</th><th>自營商</th><th>總合</th>
    <th>外資</th><th>投信</th><th>自營商</th><th>三大法人</th>
    <th>外資</th><th>投信</th><th>自營商</th>
  </tr>
  <tr>
    <td>2026/10/22</td><td>-12695</td><td>1350</td><td>-289</td><td>-11634</td>
    <td>68.58</td><td>8.10</td><td>0.30</td><td>76.98</td>
    <td>68.58</td><td>8.10</td><td>0.30</td>
  </tr>
</table>
</body></html>
"""

MAIN_HTML = """
<html><body>
<table>
  <tr>
    <th>日期</th><th>收盤價</th><th>買賣超</th>
    <th>家數差</th><th>5日集中</th><th>20日集中</th>
  </tr>
  <tr>
    <td>2026/10/22</td><td>2385</td><td>-9108</td>
    <td>722</td><td>-0.30838</td><td>-0.12345</td>
  </tr>
</table>
</body></html>
"""

# 只有表頭、沒有資料列（= 站方 API 被擋時的實際狀況）
EMPTY_HTML = """
<html><body>
<table>
  <tr><th>日期</th><th>資餘</th><th>當沖率%</th></tr>
  <tr><td>日期</td><td>資餘</td><td>當沖率%</td></tr>
</table>
</body></html>
"""


# ============ URL 回歸防護 ============

def test_page_urls_are_not_the_old_404_paths():
    """舊的 4 個路徑全部 404，不可再用。"""
    for dead in ("balance-sheet", "financial/BS", "finance/balance_sheet"):
        assert dead not in wantgoo.PAGE_MARGIN, f"{dead} 是 404 舊路徑"
    assert wantgoo.PAGE_MARGIN == "margin-trading/synopsis"
    assert wantgoo.PAGE_INSTITUTIONAL == "institutional-investors/trend"
    assert wantgoo.PAGE_MAIN == "major-investors/main-trend"


def test_api_paths_match_site_bundle():
    """API 路徑必須跟站方 JS 裡實際使用的完全一致。"""
    assert wantgoo.API_INSTITUTIONAL == \
        "/stock/{code}/institutional-investors/trend-data?topdays=60"
    assert wantgoo.API_MAIN == "/stock/{code}/major-investors/main-trend-data"


def test_is_available_true():
    assert wantgoo.is_available() is True


# ============ 表頭壓平 ============

def test_flatten_two_level_headers():
    tables = wantgoo._tables(MARGIN_HTML)
    headers = tables[0]["headers"]
    assert "日期" in headers
    assert "融資使用率%" in headers
    assert "融券使用率%" in headers
    # 融資的三個子欄位必須各自帶上前綴，不能都叫「使用率%」
    assert headers.count("使用率%") == 0


def test_rows_are_not_header_rows():
    """第二層表頭不可被當成資料列。"""
    tables = wantgoo._tables(MARGIN_HTML)
    assert len(tables[0]["rows"]) == 1
    assert tables[0]["rows"][0][0] == "2026/10/22"


# ============ 融資券解析 ============

def test_parse_balance_sheet():
    r = wantgoo.parse_balance_sheet_html(MARGIN_HTML, "2330")
    assert r["margin_pct"] == 20.0
    assert r["short_ratio"] == 2.5
    assert r["dt_ratio"] == 38.5
    assert "error" not in r


def test_parse_balance_sheet_without_rows_returns_error():
    """沒有資料列 → 回 error，不得回 0（0 會讓 F9 誤判為零槓桿）。"""
    r = wantgoo.parse_balance_sheet_html(EMPTY_HTML, "2330")
    assert "error" in r
    assert r.get("margin_pct") is None
    assert r.get("dt_ratio") is None


# ============ 法人解析 ============

def test_parse_institutional():
    r = wantgoo.parse_institutional_html(INSTITUTIONAL_HTML, "2330")
    assert "error" not in r
    rows = r["rows"]
    assert len(rows) == 1
    row = rows[0]
    assert row["date"] == "2026/10/22"
    assert row["foreign"] == -12695.0
    assert row["investment_trust"] == 1350.0
    assert row["dealer"] == -289.0
    assert row["total"] == -11634.0


def test_parse_institutional_without_rows_returns_error():
    r = wantgoo.parse_institutional_html(EMPTY_HTML, "2330")
    assert "error" in r
    assert "rows" not in r


# ============ 主力解析 ============

def test_parse_main_page():
    r = wantgoo.parse_main_page_html(MAIN_HTML, "2330")
    assert "error" not in r
    row = r["rows"][0]
    assert row["date"] == "2026/10/22"
    assert row["close"] == 2385.0
    assert row["net"] == -9108.0
    assert row["broker_diff"] == 722.0
    assert abs(row["conc5"] - (-0.30838)) < 1e-6


def test_parse_main_page_without_rows_returns_error():
    r = wantgoo.parse_main_page_html(EMPTY_HTML, "2330")
    assert "error" in r


# ============ 數字解析 ============

def test_to_float_handles_formatting():
    assert wantgoo._to_float("20.00%") == 20.0
    assert wantgoo._to_float("100,000") == 100000.0
    assert wantgoo._to_float("-1,265") == -1265.0
    assert wantgoo._to_float("--") is None
    assert wantgoo._to_float("") is None
    assert wantgoo._to_float(None) is None


# ============ 價格歷史（純 HTTP，免登入）============

# 真實回應格式（2026-10-24 實測，/investrue/2330/historical-daily-candlesticks）
PRICE_HISTORY_RAW = [
    {"time": 1792080000000, "tradeDate": 1792080000000,
     "open": 2430.0, "high": 2445.0, "low": 2420.0, "close": 2420.0,
     "volume": 33389, "millionAmount": 81100.73},
    {"time": 1791993600000, "tradeDate": 1791993600000,
     "open": 2420.0, "high": 2450.0, "low": 2420.0, "close": 2440.0,
     "volume": 48032, "millionAmount": 90123.45},
    {"time": 1791907200000, "tradeDate": 1791907200000,
     "open": 2505.0, "high": 2535.0, "low": 2490.0, "close": 2490.0,
     "volume": 23175, "millionAmount": 55555.55},
]


def test_price_history_contract_constants():
    """端點參數契約（踩過坑，別亂改）。"""
    assert wantgoo.PRICE_HISTORY_TOP == 490
    assert wantgoo.PRICE_HISTORY_PATH == \
        "/investrue/{code}/historical-daily-candlesticks"
    # 必須走站點根目錄，不是 /stock 底下
    assert wantgoo.WANTAOO_ORIGIN == "https://www.wantgoo.com"


def test_parse_price_history_converts_and_sorts():
    """原始資料是「最新在前」，要翻成日期升冪 + 欄位名稱統一。"""
    bars = wantgoo.parse_price_history(PRICE_HISTORY_RAW)
    assert len(bars) == 3
    dates = [b["date"] for b in bars]
    assert dates == sorted(dates), "必須依日期升冪"
    assert bars[0]["date"] < bars[-1]["date"]
    assert set(bars[0].keys()) == {"date", "open", "high", "low", "close", "volume"}
    # 原始是「最新在前」，翻正後 bars[0] 應該是最舊那筆（close 2490）
    assert bars[0]["close"] == 2490.0
    assert bars[-1]["close"] == 2420.0
    assert bars[-1]["volume"] == 33389.0


def test_parse_price_history_skips_bad_rows():
    """缺時間或缺收盤的資料列要略過，不可讓整批失敗。"""
    raw = list(PRICE_HISTORY_RAW) + [
        {"time": None, "tradeDate": None, "close": 100.0},
        {"time": 1791907200000, "tradeDate": 1791907200000},
        "not-a-dict",
    ]
    bars = wantgoo.parse_price_history(raw)
    assert len(bars) == 3


def test_parse_price_history_empty():
    assert wantgoo.parse_price_history([]) == []
    assert wantgoo.parse_price_history([{"x": 1}]) == []


def test_taipei_midnight_ms_is_midnight():
    """before 參數必須是「今天 00:00 台北」的毫秒時間戳。"""
    import datetime as dt
    ms = wantgoo._taipei_midnight_ms()
    tpe = dt.timezone(dt.timedelta(hours=8))
    moment = dt.datetime.fromtimestamp(ms / 1000, tpe)
    assert (moment.hour, moment.minute, moment.second) == (0, 0, 0)
    assert ms % 1000 == 0

if __name__ == "__main__":
    # 自動發現所有 test_ 函式 —— 新增測試不可能再被靜默遺漏。
    # 見 backend/tests/_runner.py 的說明。
    import sys as _sys
    from pathlib import Path as _Path

    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
    from backend.tests._runner import run_tests

    run_tests(globals(), "wantgoo")
