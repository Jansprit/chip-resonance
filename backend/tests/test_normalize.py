"""
test_normalize.py — Unit tests for normalize.py

Validates field unification from various sources to STOCK_UNIVERSE schema.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.normalize import (
    DEFAULTS,
    from_twse,
    from_tpex,
    from_pyramid,
    from_tdcc,
    from_mops_director,
    from_goodinfo_margin_short,
    from_finmind_prices,
    from_finmind_month_revenue,
    merge_into,
    guess_industry,
)


def test_from_twse_fills_defaults():
    """TWSE rows should be merged with all default chip values."""
    rows = [{"code": "2330", "name": "台積電", "price": 2460, "volume_lots": 1000,
             "date": "2026-09-18", "exchange": "TWSE"}]
    result = from_twse(rows)
    assert len(result) == 1
    s = result[0]
    assert s["code"] == "2330"
    assert s["name"] == "台積電"
    assert s["price"] == 2460
    assert s["avg_volume"] == 1000
    assert s["pct_1000up_now"] == DEFAULTS["pct_1000up_now"]
    assert s["pct_1000up_trend"] == "="
    assert s["warning"] is False


def test_from_pyramid_computes_trend():
    """pyramid 應根據 pct_1000up_now - w3 計算 trend."""
    rows = [{
        "code": "2330",
        "date": "2026-09-18",
        "pct_1000up_now": 70.0,
        "pct_1000up_w1": 68.0,
        "pct_1000up_w2": 67.0,
        "pct_1000up_w3": 65.0,  # delta = 5.0 -> trend +
    }]
    result = from_pyramid(rows)
    assert result[0]["pct_1000up_trend"] == "+"

    rows2 = [{"code": "X", "pct_1000up_now": 60.0, "pct_1000up_w1": 65.0,
              "pct_1000up_w2": 67.0, "pct_1000up_w3": 70.0, "date": "2026-09-18"}]  # delta = -10
    result2 = from_pyramid(rows2)
    assert result2[0]["pct_1000up_trend"] == "-"

    rows3 = [{"code": "X", "pct_1000up_now": 70.0, "pct_1000up_w1": 70.0,
              "pct_1000up_w2": 70.0, "pct_1000up_w3": 70.0, "date": "2026-09-18"}]  # delta = 0
    result3 = from_pyramid(rows3)
    assert result3[0]["pct_1000up_trend"] == "="


def test_guess_industry_semiconductors():
    """台股半導體代號應正確歸類。"""
    assert guess_industry("2330") == "SEMI"  # 台積電
    assert guess_industry("2454") == "SEMI"  # 聯發科
    assert guess_industry("2303") == "SEMI"  # 聯電
    assert guess_industry("3711") == "SEMI"  # 日月光


def test_guess_industry_finance():
    assert guess_industry("2884") == "FIN"  # 玉山金
    assert guess_industry("2882") == "FIN"  # 國泰金
    assert guess_industry("2891") == "FIN"


def test_guess_industry_shipping():
    assert guess_industry("2603") == "SHIP"  # 長榮
    assert guess_industry("2609") == "SHIP"  # 陽明


def test_guess_industry_food():
    assert guess_industry("1216") == "FOOD"  # 統一


def test_guess_industry_unknown():
    assert guess_industry("9999") == "OTHER"
    assert guess_industry("") == "OTHER"


def test_merge_into_priority():
    """merge_into 後面的 overlay 應覆蓋前面的。"""
    base = [{"code": "2330", "name": "台積電", "price": 100, "avg_volume": 1000}]
    overlay1 = [{"code": "2330", "price": 200}]  # 較早
    overlay2 = [{"code": "2330", "price": 300, "margin_pct": 50}]  # 較晚（覆蓋）

    result = merge_into(base, overlay1, overlay2)
    assert result[0]["price"] == 300  # 最後的 overlay 勝
    assert result[0]["margin_pct"] == 50
    assert result[0]["name"] == "台積電"  # base 保留
    assert result[0]["avg_volume"] == 1000


def test_from_tpex_preserves_exchange():
    rows = [{"code": "6488", "name": "環球晶", "price": 500, "volume_lots": 100,
             "date": "2026-09-18", "exchange": "TPEx"}]
    result = from_tpex(rows)
    assert result[0]["exchange"] == "TPEx"


def test_from_mops_director_sets_3m_change():
    rows = [{"code": "2330", "date": "2026-09-18", "director_holding_change_3m": 0.5,
             "director_pledge_pct": 0.1}]
    result = from_mops_director(rows)
    assert result[0]["director_holding_change_3m"] == 0.5
    assert result[0]["director_pledge"] == 0.1


def test_from_goodinfo_margin_short():
    rows = [{"code": "2330", "date": "2026-09-18", "margin_pct": 12.5, "dt_ratio": 18.0}]
    result = from_goodinfo_margin_short(rows)
    assert result[0]["margin_pct"] == 12.5
    assert result[0]["dt_ratio"] == 18.0


def test_from_finmind_prices_computes_drawdown():
    """FinMind prices 應計算 ret_60d, drawdown_120d, is_60d_high。"""
    import datetime
    history = []
    end_date = datetime.date(2026, 9, 18)
    for i in range(130):
        d = end_date - datetime.timedelta(days=130 - i)
        # 簡單遞增序列：100, 101, 102, ..., 229
        price = 100.0 + i
        history.append({
            "stock_id": "TEST",
            "date": d.isoformat(),
            "close": price,
        })
    result = from_finmind_prices(history)
    assert "TEST" in result
    s = result["TEST"]
    assert "ret_60d" in s
    assert "drawdown_120d" in s
    assert "is_60d_high" in s
    # 線性遞增 1 元/天，所以 60 天後從 price[69] -> price[129]
    # price[69] = 169, price[129] = 229, ret_60d = (229/169 - 1)*100 ≈ 35.5%
    assert 30 < s["ret_60d"] < 40
    # 130 天都是單調遞增，沒有回撤
    assert s["drawdown_120d"] == 0
    # 最近 60 天新高（因為單調遞增）
    assert s["is_60d_high"] is True


if __name__ == "__main__":
    test_from_twse_fills_defaults()
    print("PASS: test_from_twse_fills_defaults")
    test_from_pyramid_computes_trend()
    print("PASS: test_from_pyramid_computes_trend")
    test_guess_industry_semiconductors()
    print("PASS: test_guess_industry_semiconductors")
    test_guess_industry_finance()
    print("PASS: test_guess_industry_finance")
    test_guess_industry_shipping()
    print("PASS: test_guess_industry_shipping")
    test_guess_industry_food()
    print("PASS: test_guess_industry_food")
    test_guess_industry_unknown()
    print("PASS: test_guess_industry_unknown")
    test_merge_into_priority()
    print("PASS: test_merge_into_priority")
    test_from_tpex_preserves_exchange()
    print("PASS: test_from_tpex_preserves_exchange")
    test_from_mops_director_sets_3m_change()
    print("PASS: test_from_mops_director_sets_3m_change")
    test_from_goodinfo_margin_short()
    print("PASS: test_from_goodinfo_margin_short")
    test_from_finmind_prices_computes_drawdown()
    print("PASS: test_from_finmind_prices_computes_drawdown")
    print("\nAll 12 normalize tests passed.")