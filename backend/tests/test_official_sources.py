"""
test_official_sources.py — 官方開放 API 的解析器測試

對應 docs/2026-10-21-專案體檢報告.md BUG-04 與「專案修復計畫.MD」P0。

這些端點是**官方 / 政府開放 API**，2026-10-24 實測不擋 datacenter IP，
所以能放進 CI 的 public 集合：

  TWSE MI_MARGN   → 融資融券餘額 → F9 的 margin_pct / short_ratio
  TWSE BWIBBU_d   → 個股基本資料 → F5 的 yield_now
  TWSE t187ap03_L → 公司基本資料 → 產業別（CID）成分股清單（F2 的基礎）
  Yahoo v8/chart  → 價格歷史（免 key，CI 友善）

設計原則：**解析是純函數、與網路分離**，
測試用真實 API 回應格式的 fixture，不連網。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.scrapers import twse


# ============ fixtures（真實 API 回應格式，2026-10-24 實測）============

MI_MARGN_ROWS = [
    {
        "股票代號": "2330", "股票名稱": "台積電",
        "融資買進": "597", "融資賣出": "434", "融資現金償還": "21",
        "融資前日餘額": "35330", "融資今日餘額": "35472", "融資限額": "6483092",
        "融券買進": "1", "融券賣出": "10", "融券現券償還": "",
        "融券前日餘額": "6", "融券今日餘額": "15", "融券限額": "6483092",
        "資券互抵": "", "註記": " ",
    },
    {
        "股票代號": "2454", "股票名稱": "聯發科",
        "融資買進": "0", "融資賣出": "0", "融資現金償還": "",
        "融資前日餘額": "100", "融資今日餘額": "120", "融資限額": "0",
        "融券買進": "", "融券賣出": "", "融券現券償還": "",
        "融券前日餘額": "", "融券今日餘額": "0", "融券限額": "0",
        "資券互抵": "", "註記": " ",
    },
]

BWIBBU_ROWS = [
    {"Date": "20261022", "Code": "2330", "Name": "台積電", "ClosePrice": "2385.00",
     "DividendYield": "0.92", "DividendYear": "114", "PEratio": "27.65",
     "PBratio": "9.61", "FiscalYearQuarter": "2026Q2"},
    {"Date": "20261022", "Code": "2454", "Name": "聯發科", "ClosePrice": "4010.00",
     "DividendYield": "1.85", "DividendYear": "114", "PEratio": "18.2",
     "PBratio": "2.4", "FiscalYearQuarter": "2026Q2"},
    {"Date": "20261022", "Code": "9999", "Name": "無配息股", "ClosePrice": "10.00",
     "DividendYield": "", "DividendYear": "", "PEratio": "",
     "PBratio": "", "FiscalYearQuarter": "2026Q2"},
]

T187_ROWS = [
    {"出表日期": "1151023", "公司代號": "1101", "公司名稱": "臺灣水泥股份有限公司",
     "公司簡稱": "台泥", "外國企業註冊地國": "－ ", "產業別": "01",
     "住址": "台北市中山北路2段113號"},
    {"出表日期": "1151023", "公司代號": "2330", "公司名稱": "台灣積體電路製造股份有限公司",
     "公司簡稱": "台積電", "外國企業註冊地國": "－ ", "產業別": "24",
     "住址": "新竹市科學園區晶圓一路3號"},
    {"出表日期": "1151023", "公司代號": "2891", "公司名稱": "中信金控股份有限公司",
     "公司簡稱": "中信金", "外國企業註冊地國": "－ ", "產業別": "80",
     "住址": "台北市松壽路"},
]


# ============ MI_MARGN ============

def test_parse_margin_balance_computes_pct():
    """融資使用率 = 融資今日餘額 / 融資限額 × 100"""
    out = twse.parse_margin_balance(MI_MARGN_ROWS)
    assert "2330" in out
    m = out["2330"]
    assert m["margin_balance"] == 35472
    assert m["margin_limit"] == 6483092
    assert abs(m["margin_pct"] - (35472 / 6483092 * 100)) < 1e-6
    assert abs(m["short_pct"] - (15 / 6483092 * 100)) < 1e-9


def test_parse_margin_balance_zero_limit_is_none_not_zero():
    """限額為 0 時必須回 None（不可回 0，否則 F9 會誤判為零槓桿）。"""
    out = twse.parse_margin_balance(MI_MARGN_ROWS)
    m = out["2454"]
    assert m["margin_limit"] == 0
    assert m["margin_pct"] is None
    assert m["short_pct"] is None


def test_parse_margin_balance_skips_missing_fields():
    """欄位缺漏的列要被跳過而不是拋例外。"""
    out = twse.parse_margin_balance([{"股票代號": "1111"}])
    assert "1111" not in out


def test_parse_margin_balance_empty():
    assert twse.parse_margin_balance([]) == {}


# ============ BWIBBU_d ============

def test_parse_valuation_extracts_dividend_yield():
    """F5 的 yield_now = DividendYield"""
    out = twse.parse_valuation(BWIBBU_ROWS)
    assert out["2330"]["yield_now"] == 0.92
    assert out["2330"]["dividend_year"] == 114
    assert out["2330"]["close_price"] == 2385.0
    assert out["2330"]["pe_ratio"] == 27.65
    assert out["2330"]["pb_ratio"] == 9.61


def test_parse_valuation_missing_yield_is_none():
    """沒有配息資料時 yield_now 必須是 None（0 會讓 F5 誤判為低殖利率）。"""
    out = twse.parse_valuation(BWIBBU_ROWS)
    assert "9999" not in out or out["9999"]["yield_now"] is None


def test_parse_valuation_empty():
    assert twse.parse_valuation([]) == {}


# ============ t187ap03_L 產業別 ============

def test_parse_industry_map():
    """產業別 CID → 成分股清單（F2 的基礎）。"""
    out = twse.parse_industry(T187_ROWS)
    assert out == {"1101": "01", "2330": "24", "2891": "80"}


def test_parse_industry_skips_blank():
    out = twse.parse_industry(
        T187_ROWS + [{"出表日期": "1151023", "公司代號": "9999", "產業別": "  "}]
    )
    assert "9999" not in out


def test_parse_industry_empty():
    assert twse.parse_industry([]) == {}


# ============ 價格歷史（Yahoo v8，CI 友善）============

def test_parse_yahoo_chart_to_bars():
    """Yahoo v8/finance/chart 回應 → 統一格式的日 K 線。

    ⚠️ 真實 Yahoo 的 timestamp 是**秒**（不是毫秒）。
    2026-10-24 實測首筆 timestamp = 1792080000（10 碼 = 秒）。
    之前的 fixture 誤用毫秒，導致解析出 1970-01-21 而測試仍通過 ——
    這是「測試沒有測到真實行為」的典型案例。
    """
    payload = {
        "chart": {
            "result": [{
                "meta": {"currency": "TWD", "symbol": "2330.TW"},
                "timestamp": [1792080000, 1791993600],  # 秒，倒序
                "indicators": {"quote": [{
                    "open": [2430.0, 2420.0],
                    "high": [2445.0, 2450.0],
                    "low": [2420.0, 2420.0],
                    "close": [2420.0, 2440.0],
                    "volume": [33389, 48032],
                }]},
            }],
            "error": None,
        }
    }
    bars = twse.parse_yahoo_chart(payload, "2330")
    assert len(bars) == 2
    # 必須翻正成日期升冪
    assert bars[0]["date"] < bars[-1]["date"]
    # 真實秒級時間戳 → 必須落在 2026 年，不是 1970
    assert bars[-1]["date"].startswith("2026-")
    assert bars[-1]["close"] == 2420.0
    assert bars[-1]["volume"] == 33389
    assert set(bars[0].keys()) == {"date", "open", "high", "low", "close", "volume"}


def test_parse_yahoo_chart_accepts_millisecond_timestamps():
    """毫秒級時間戳也要能解析（有些 Yahoo 端點/代理會回毫秒）。"""
    payload = {
        "chart": {
            "result": [{
                "timestamp": [1792080000000],
                "indicators": {"quote": [{
                    "open": [2430.0], "high": [2445.0], "low": [2420.0],
                    "close": [2420.0], "volume": [33389],
                }]},
            }],
            "error": None,
        }
    }
    bars = twse.parse_yahoo_chart(payload, "2330")
    assert len(bars) == 1
    assert bars[0]["date"].startswith("2026-")


def test_parse_yahoo_chart_handles_error():
    payload = {"chart": {"result": None, "error": {"code": "Not Found"}}}
    assert twse.parse_yahoo_chart(payload, "9999") == []


def test_parse_yahoo_chart_handles_null_values():
    payload = {"chart": {"result": [{
        "timestamp": [1792080000000, 1791993600000],
        "indicators": {"quote": [{
            "open": [None, 2420.0], "high": [None, 2450.0],
            "low": [None, 2420.0], "close": [None, 2440.0],
            "volume": [None, 48032],
        }]},
    }], "error": None}}
    bars = twse.parse_yahoo_chart(payload, "2330")
    # 沒有收盤價的列要被跳過
    assert len(bars) == 1
    assert bars[0]["close"] == 2440.0


def test_parse_yahoo_chart_empty():
    assert twse.parse_yahoo_chart({}, "2330") == []
    assert twse.parse_yahoo_chart({"chart": {"result": []}}, "2330") == []

def test_fetch_price_history_tries_both_twse_and_tpex_suffixes():
    """
    上櫃股在 Yahoo 用 .TWO，上市用 .TW。

    只試 .TW 會讓上櫃股整批 404（2026-10-25 實測 5347 / 4743 / 4128），
    看起來像「股票下市了」，實際上只是後綴不對。
    """
    attempted = []

    class _FakeClient:
        def get_json(self, url):
            attempted.append(url)
            if ".TWO" in url:
                return {"chart": {"result": [{
                    "timestamp": [1792080000],
                    "indicators": {"quote": [{"close": [2385.0]}]},
                }], "error": None}}
            raise RuntimeError("404 Not Found")

    bars = twse.fetch_price_history("5347", client=_FakeClient())
    assert len(attempted) == 2, f"應該先試 .TW 再試 .TWO，實際：{attempted}"
    assert ".TW?" in attempted[0]
    assert ".TWO?" in attempted[1]
    assert bars, "上櫃股應該能取到 K 線"


def test_fetch_price_history_returns_empty_when_all_suffixes_fail():
    attempted = []

    class _FakeClient:
        def get_json(self, url):
            attempted.append(url)
            raise RuntimeError("404 Not Found")

    assert twse.fetch_price_history("9999", client=_FakeClient()) == []
    assert len(attempted) == 2


def test_fetch_price_history_stops_at_first_success():
    attempted = []

    class _FakeClient:
        def get_json(self, url):
            attempted.append(url)
            return {"chart": {"result": [{
                "timestamp": [1792080000],
                "indicators": {"quote": [{"close": [2385.0]}]},
            }], "error": None}}

    twse.fetch_price_history("2330", client=_FakeClient())
    assert len(attempted) == 1, "第一個後綴成功就不該再試"


def test_yahoo_suffixes_include_twse_and_tpex():
    assert "TW" in twse.YAHOO_SUFFIXES
    assert "TWO" in twse.YAHOO_SUFFIXES


if __name__ == "__main__":
    # 自動發現所有 test_ 函式 —— 新增測試不可能再被靜默遺漏。
    # 見 backend/tests/_runner.py 的說明。
    import sys as _sys
    from pathlib import Path as _Path

    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
    from backend.tests._runner import run_tests

    run_tests(globals(), "official_sources")
