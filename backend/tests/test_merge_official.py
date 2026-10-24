"""
test_merge_official.py — 官方端點資料接進合併層的測試

對應「專案修復計畫.MD」P0（TWSE 官方端點補齊因子輸入）。

驗證重點：
- margin_pct / short_ratio → F9 的輸入
- yield_now → F5 的輸入
- 產業別 CID → F2 產業籌碼流量的基礎
- 價格歷史（Yahoo）→ 價格衍生因子，且**優先於**玩股網（CI 友善）
- 缺資料時必須標成 illustrative（不可假裝是真的）
- 限額為 0 / 缺值時不可寫入 0
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.scripts.build_universe import build


SEED = [
    {
        "code": "2330", "name": "台積電", "industry": "半導體",
        "price": 100.0, "avg_volume": 1000, "date": "2026-01-01", "exchange": "TWSE",
        "margin_pct": 0.0, "short_ratio": 0.0, "yield_now": 0.0,
        "industry_cid": "",
        "pct_1000up_now": 50.0, "pct_1000up_w1": 49.0, "pct_1000up_w2": 48.0,
        "pct_1000up_w3": 47.0, "pct_1000up_trend": "+", "pct_400up": 60.0,
        "director_holding_change_3m": 0.0, "director_pledge": 0.0,
        "ret_60d": 0.0, "drawdown_120d": 0.0, "is_60d_high": False,
        "crash_60d": False, "industry_ret_60d_med": 0.0,
        "div_years": 0, "yield_5y_avg": 0.0,
        "holder_cnt_change_8w": 0.0, "avg_lot_change_8w": 0.0,
        "eps_q4": 0.0, "list_year": 0, "warning": False,
        "margin_pct_dummy": 0.0,
    },
    {
        "code": "2454", "name": "聯發科", "industry": "半導體",
        "price": 200.0, "avg_volume": 500, "date": "2026-01-01", "exchange": "TWSE",
        "margin_pct": 0.0, "short_ratio": 0.0, "yield_now": 0.0,
        "industry_cid": "",
        "pct_1000up_now": 50.0, "pct_1000up_w1": 49.0, "pct_1000up_w2": 48.0,
        "pct_1000up_w3": 47.0, "pct_1000up_trend": "+", "pct_400up": 60.0,
        "director_holding_change_3m": 0.0, "director_pledge": 0.0,
        "ret_60d": 0.0, "drawdown_120d": 0.0, "is_60d_high": False,
        "crash_60d": False, "industry_ret_60d_med": 0.0,
        "div_years": 0, "yield_5y_avg": 0.0,
        "holder_cnt_change_8w": 0.0, "avg_lot_change_8w": 0.0,
        "eps_q4": 0.0, "list_year": 0, "warning": False,
    },
]

EMPTY = {"prices": [], "tpex": [], "tdcc": [], "mops": [], "wantgoo": [],
         "pyramid": [], "finmind": []}


def _build(**overrides):
    kwargs = dict(EMPTY)
    kwargs.update(overrides)
    return build(
        SEED,
        kwargs["prices"], kwargs["tpex"], kwargs["tdcc"], kwargs["mops"],
        kwargs["wantgoo"], kwargs["pyramid"], kwargs["finmind"],
        margin_balance=overrides.get("margin_balance"),
        valuation=overrides.get("valuation"),
        industry=overrides.get("industry"),
        price_history=overrides.get("price_history"),
    )


# ============ F9：融資券 ============

def test_merge_margin_balance_marks_real():
    merged, stats = _build(margin_balance={
        "2330": {"margin_balance": 35472, "margin_limit": 6483092,
                 "margin_pct": 0.547, "short_balance": 15,
                 "short_limit": 6483092, "short_pct": 0.00023},
    })
    s = merged[0]
    assert abs(s["margin_pct"] - 0.547) < 1e-6
    assert s["_provenance"]["margin_pct"] == "real"
    assert s["_provenance"]["short_ratio"] == "real"
    assert stats["margin"] == 1
    # 沒資料的那檔必須維持 illustrative
    assert merged[1]["_provenance"]["margin_pct"] == "illustrative"


def test_merge_margin_balance_none_value_stays_illustrative():
    """限額為 0 → 使用率無法計算，必須維持 illustrative（不可標成 real）。

    注意：欄位值維持 seed 的預設值而非寫 None，因為
    demo_subset 的 schema 宣告 margin_pct 為 float（不接受 None）。
    「這個值不是真的」由 _provenance 表達 —— F9 的可用性判定看的就是它。
    """
    merged, stats = _build(margin_balance={
        "2330": {"margin_balance": 100, "margin_limit": 0, "margin_pct": None,
                 "short_balance": 0, "short_limit": 0, "short_pct": None},
    })
    s = merged[0]
    assert s["_provenance"]["margin_pct"] == "illustrative"
    assert s["_provenance"]["short_ratio"] == "illustrative"
    assert stats["margin"] == 0


# ============ F5：殖利率 ============

def test_merge_valuation_marks_real():
    merged, stats = _build(valuation={
        "2330": {"close_price": 2385.0, "yield_now": 0.92,
                 "dividend_year": 114, "pe_ratio": 27.65, "pb_ratio": 9.61},
    })
    s = merged[0]
    assert s["yield_now"] == 0.92
    assert s["_provenance"]["yield_now"] == "real"
    assert stats["valuation"] == 1


def test_merge_valuation_missing_yield_not_real():
    merged, _ = _build(valuation={
        "2330": {"close_price": 10.0, "yield_now": None,
                 "dividend_year": None, "pe_ratio": None, "pb_ratio": None},
    })
    assert merged[0]["_provenance"]["yield_now"] == "illustrative"


# ============ 產業別 CID ============

def test_merge_industry_cid():
    merged, stats = _build(industry={"2330": "24", "2454": "24"})
    assert merged[0]["industry_cid"] == "24"
    assert merged[0]["_provenance"]["industry_cid"] == "real"
    assert stats["industry"] == 2


# ============ 價格歷史（Yahoo，CI 友善）============

def test_merge_price_history_produces_derived_factors():
    """price_history 應能算出 ret_60d / drawdown_120d 等價格衍生因子。"""
    bars = []
    for i in range(200):
        bars.append({"date": f"2026-{(i // 28) % 12 + 1:02d}-{i % 28 + 1:02d}",
                     "open": 100.0, "high": 101.0, "low": 99.0,
                     "close": 100.0 + i, "volume": 1000})
    merged, stats = _build(price_history=[{"code": "2330", "bars": bars}])
    s = merged[0]
    assert s["_provenance"]["ret_60d"] == "real"
    assert s["_provenance"]["drawdown_120d"] == "real"
    assert s["_provenance"]["is_60d_high"] == "real"
    assert s["_provenance"]["crash_60d"] == "real"
    assert stats["price_history"] == 1


def test_price_history_takes_priority_over_wantgoo():
    """Yahoo（CI 友善）優先於玩股網（datacenter IP 403）。"""
    bars = [{"date": f"2026-01-{i % 28 + 1:02d}", "open": 1.0, "high": 1.0,
             "low": 1.0, "close": 100.0 + i, "volume": 1} for i in range(130)]
    merged, _ = _build(
        wantgoo=[{"code": "2330", "ret_60d": 999.0, "drawdown_120d": -99.0,
                  "is_60d_high": True, "crash_60d": True, "bars": 490,
                  "last_date": "2026-10-22"}],
        price_history=[{"code": "2330", "bars": bars}],
    )
    s = merged[0]
    assert s["ret_60d"] != 999.0
    assert s["_provenance"]["ret_60d"] == "real"


def test_merge_without_new_sources_keeps_illustrative():
    merged, stats = _build()
    s = merged[0]
    assert s["_provenance"]["margin_pct"] == "illustrative"
    assert s["_provenance"]["yield_now"] == "illustrative"
    assert s["_provenance"]["industry_cid"] == "illustrative"


if __name__ == "__main__":
    test_merge_margin_balance_marks_real()
    print("PASS: test_merge_margin_balance_marks_real")
    test_merge_margin_balance_none_value_stays_illustrative()
    print("PASS: test_merge_margin_balance_none_value_stays_illustrative")
    test_merge_valuation_marks_real()
    print("PASS: test_merge_valuation_marks_real")
    test_merge_valuation_missing_yield_not_real()
    print("PASS: test_merge_valuation_missing_yield_not_real")
    test_merge_industry_cid()
    print("PASS: test_merge_industry_cid")
    test_merge_price_history_produces_derived_factors()
    print("PASS: test_merge_price_history_produces_derived_factors")
    test_price_history_takes_priority_over_wantgoo()
    print("PASS: test_price_history_takes_priority_over_wantgoo")
    test_merge_without_new_sources_keeps_illustrative()
    print("PASS: test_merge_without_new_sources_keeps_illustrative")
    print("\nAll 8 merge_official tests passed.")
