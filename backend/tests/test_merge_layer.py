"""
test_merge_layer.py — Tests for the source merge layer (build_universe.build)

這是整個系統的關鍵橋接點：把各來源抓回來的真實資料
合併進 demo_subset.json，並標註每個欄位的來源（real / illustrative）。

驗證：
- 價格衍生因子計算（ret_60d / drawdown_120d / is_60d_high / crash_60d）
- 產業中位數只採用真實的 ret_60d
- 各來源欄位映射正確（TDCC / MOPS / MoneyDJ）
- 多週欄位必須整組都有值才覆寫（避免假 delta）
- provenance 標記正確
- 因子可用性（factor_is_available）與前端一致

執行：python backend/tests/test_merge_layer.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.normalize import (
    FACTOR_INPUTS,
    compute_industry_medians,
    compute_price_derived,
    factor_is_available,
)
from backend.scripts.build_universe import build


# ============ 價格衍生因子 ============

def _bars(start_close: float, n: int, step: float = 1.0) -> list[dict]:
    """造 n 根日線，收盤價從 start_close 每根 +step。"""
    out = []
    for i in range(n):
        out.append({
            "date": f"2026-{1 + i // 28:02d}-{1 + i % 28:02d}",
            "close": start_close + i * step,
        })
    return out


def test_compute_price_derived_basic():
    bars = _bars(100.0, 200, 1.0)
    r = compute_price_derived(bars, bar_days=1)
    assert r["bars"] == 200
    # 60 日報酬：closes[-61] = 100 + 139 = 239；current = 100+199 = 299
    expected = (299 / 239 - 1) * 100
    assert abs(r["ret_60d"] - expected) < 0.05
    # 連續上漲 → 目前就是最高 → is_60d_high
    assert r["is_60d_high"] is True
    # 沒有回撤
    assert abs(r["drawdown_120d"]) < 0.01
    assert r["crash_60d"] is False
    assert r["last_date"] == bars[-1]["date"]


def test_compute_price_derived_detects_crash():
    """近 60 日內單週跌幅 > 15% → crash_60d = True。"""
    bars = _bars(100.0, 100, 1.0)
    # 最後一根直接砍 20%
    bars[-1]["close"] = bars[-2]["close"] * 0.7
    r = compute_price_derived(bars, bar_days=1)
    assert r["crash_60d"] is True


def test_compute_price_derived_insufficient_data():
    """資料不足時必須回 None，不能回 0（0 會製造假訊號）。"""
    r = compute_price_derived([], bar_days=5)
    assert r["ret_60d"] is None
    assert r["drawdown_120d"] is None
    assert r["is_60d_high"] is None
    assert r["crash_60d"] is None

    r2 = compute_price_derived(_bars(100.0, 5, 1.0), bar_days=5)
    assert r2["ret_60d"] is None
    assert r2["drawdown_120d"] is None


def test_compute_price_derived_drawdown():
    bars = _bars(100.0, 200, 1.0)
    bars[-1]["close"] = 150.0   # 從高點 299 跌到 150
    r = compute_price_derived(bars, bar_days=1)
    assert r["drawdown_120d"] < -45
    assert r["is_60d_high"] is False


# ============ 產業中位數 ============

def test_compute_industry_medians_only_uses_real():
    stocks = [
        {"industry": "半導體", "ret_60d": 10.0, "_provenance": {"ret_60d": "real"}},
        {"industry": "半導體", "ret_60d": 20.0, "_provenance": {"ret_60d": "real"}},
        {"industry": "半導體", "ret_60d": 999.0, "_provenance": {"ret_60d": "illustrative"}},
        {"industry": "銀行", "ret_60d": 5.0, "_provenance": {"ret_60d": "real"}},
    ]
    med = compute_industry_medians(stocks)
    # 半導體只有 2 筆真實 → 中位數 = (10+20)/2 = 15，999 不參與
    assert med["半導體"] == 15.0
    # 銀行只有 1 筆真實同業 → 不列入
    assert "銀行" not in med


def test_compute_industry_medians_min_peers():
    stocks = [
        {"industry": "X", "ret_60d": 1.0, "_provenance": {"ret_60d": "real"}},
        {"industry": "X", "ret_60d": 3.0, "_provenance": {"ret_60d": "real"}},
    ]
    assert compute_industry_medians(stocks, min_peers=3) == {}
    assert compute_industry_medians(stocks, min_peers=2) == {"X": 2.0}


# ============ 合併層 ============

SEED = [
    {
        "code": "2330", "name": "台積電", "industry": "半導體",
        "price": 100.0, "avg_volume": 1000, "date": "2026-01-01", "exchange": "TWSE",
        "pct_1000up_now": 50.0, "pct_1000up_w1": 49.0, "pct_1000up_w2": 48.0,
        "pct_1000up_w3": 47.0, "pct_1000up_trend": "+", "pct_400up": 60.0,
        "director_holding_change_3m": 0.0, "director_pledge": 0.0,
        "ret_60d": 0.0, "drawdown_120d": 0.0, "is_60d_high": False,
        "crash_60d": False, "industry_ret_60d_med": 0.0,
    },
    {
        "code": "2454", "name": "聯發科", "industry": "半導體",
        "price": 200.0, "avg_volume": 500, "date": "2026-01-01", "exchange": "TWSE",
        "pct_1000up_now": 50.0, "pct_1000up_w1": 49.0, "pct_1000up_w2": 48.0,
        "pct_1000up_w3": 47.0, "pct_1000up_trend": "+", "pct_400up": 60.0,
        "director_holding_change_3m": 0.0, "director_pledge": 0.0,
        "ret_60d": 0.0, "drawdown_120d": 0.0, "is_60d_high": False,
        "crash_60d": False, "industry_ret_60d_med": 0.0,
    },
]


def test_build_merges_prices_and_marks_real():
    prices = [
        {"code": "2330", "price": 1234.0, "volume_lots": 999, "date": "2026-10-22",
         "exchange": "TWSE", "change": 15.0},
    ]
    merged, stats = build(SEED, prices, [], [], [], [], [], [])
    s = merged[0]
    assert s["price"] == 1234.0
    assert s["avg_volume"] == 999
    assert s["date"] == "2026-10-22"
    prov = s["_provenance"]
    assert prov["price"] == "real"
    assert prov["avg_volume"] == "real"
    # 沒有資料的欄位維持示意
    assert prov["pct_1000up_now"] == "illustrative"
    assert stats["price"] == 1


def test_build_merges_tdcc_chip():
    tdcc = [
        {"code": "2330", "date": "2026-10-22", "pct_1000up_now": 84.7,
         "pct_400up_now": 70.2, "pct_1000up_w1": 83.0, "pct_1000up_w2": 82.0,
         "pct_1000up_w3": 81.0, "pct_1000up_trend": "+"},
    ]
    merged, stats = build(SEED, [], [], tdcc, [], [], [], [])
    s = merged[0]
    assert s["pct_1000up_now"] == 84.7
    # TDCC 的 pct_400up_now 要映射到 seed 的 pct_400up
    assert s["pct_400up"] == 70.2
    prov = s["_provenance"]
    assert prov["pct_1000up_now"] == "real"
    assert prov["pct_400up"] == "real"
    assert prov["pct_1000up_w1"] == "real"
    assert stats["tdcc"] == 1


def test_build_tdcc_partial_multiweek_is_not_overwritten():
    """多週欄位只到 w2（缺 w3）→ 整組都不覆寫，保留示意值。"""
    tdcc = [
        {"code": "2330", "date": "2026-10-22", "pct_1000up_now": 84.7,
         "pct_1000up_w1": 83.0, "pct_1000up_w2": 82.0},
    ]
    merged, _ = build(SEED, [], [], tdcc, [], [], [], [])
    s = merged[0]
    # now 是單週 → 可以覆寫
    assert s["pct_1000up_now"] == 84.7
    # w1/w2/w3 整組缺 w3 → 不得覆寫（否則會產生「真實 now − 示意 w3」的假 delta）
    assert s["pct_1000up_w1"] == 49.0
    assert s["pct_1000up_w2"] == 48.0
    assert s["pct_1000up_w3"] == 47.0
    prov = s["_provenance"]
    assert prov["pct_1000up_w1"] == "illustrative"
    assert prov["pct_1000up_w3"] == "illustrative"


def test_build_merges_mops():
    mops = [
        {"code": "2330", "period": "11509", "rows": 49,
         "holding_total": 1713829460.0, "pledged_total": 8128000.0,
         "pledge_pct": 0.4743, "director_holding_change_3m": -0.2781},
    ]
    merged, stats = build(SEED, [], [], [], mops, [], [], [])
    s = merged[0]
    assert s["director_pledge"] == 0.4743
    assert s["director_holding_change_3m"] == -0.2781
    prov = s["_provenance"]
    assert prov["director_pledge"] == "real"
    assert prov["director_holding_change_3m"] == "real"
    assert stats["mops"] == 1


def test_build_merges_price_derived_and_industry_median():
    pyramid = [
        {"code": "2330", "ret_60d": 10.0, "drawdown_120d": -5.0,
         "is_60d_high": False, "crash_60d": False},
        {"code": "2454", "ret_60d": 30.0, "drawdown_120d": -2.0,
         "is_60d_high": True, "crash_60d": True},
    ]
    merged, stats = build(SEED, [], [], [], [], pyramid, [], [])
    s = merged[0]
    assert s["ret_60d"] == 10.0
    assert s["drawdown_120d"] == -5.0
    assert s["is_60d_high"] is False
    assert s["crash_60d"] is False
    prov = s["_provenance"]
    assert prov["ret_60d"] == "real"
    assert prov["drawdown_120d"] == "real"
    # 同產業中位數 = (10+30)/2 = 20
    assert s["industry_ret_60d_med"] == 20.0
    assert prov["industry_ret_60d_med"] == "real"
    assert stats["wantgoo_price"] == 2


def test_factor_availability_follows_provenance():
    """F8 = drawdown_120d + pct_1000up_now，兩者都真實才可用。"""
    tdcc = [{"code": "2330", "date": "2026-10-22", "pct_1000up_now": 84.7}]
    pyramid = [{"code": "2330", "ret_60d": 10.0, "drawdown_120d": -5.0,
                "is_60d_high": False, "crash_60d": False}]
    merged, _ = build(SEED, [], [], tdcc, [], pyramid, [], [])
    s = merged[0]
    assert factor_is_available(s, "F8") is True

    # 缺 TDCC → F8 不可用（不能拿示意的 pct_1000up_now 混著真實的 drawdown）
    merged2, _ = build(SEED, [], [], [], [], pyramid, [], [])
    assert factor_is_available(merged2[0], "F8") is False


def test_build_does_not_mutate_seed():
    """合併層不得就地改動 seed（避免污染下一次的執行）。"""
    before = [dict(s) for s in SEED]
    build(SEED, [{"code": "2330", "price": 1.0, "volume_lots": 1, "date": "x",
                   "exchange": "TWSE"}], [], [], [], [], [], [])
    assert SEED == before


if __name__ == "__main__":
    test_compute_price_derived_basic()
    print("PASS: test_compute_price_derived_basic")
    test_compute_price_derived_detects_crash()
    print("PASS: test_compute_price_derived_detects_crash")
    test_compute_price_derived_insufficient_data()
    print("PASS: test_compute_price_derived_insufficient_data")
    test_compute_price_derived_drawdown()
    print("PASS: test_compute_price_derived_drawdown")
    test_compute_industry_medians_only_uses_real()
    print("PASS: test_compute_industry_medians_only_uses_real")
    test_compute_industry_medians_min_peers()
    print("PASS: test_compute_industry_medians_min_peers")
    test_build_merges_prices_and_marks_real()
    print("PASS: test_build_merges_prices_and_marks_real")
    test_build_merges_tdcc_chip()
    print("PASS: test_build_merges_tdcc_chip")
    test_build_tdcc_partial_multiweek_is_not_overwritten()
    print("PASS: test_build_tdcc_partial_multiweek_is_not_overwritten")
    test_build_merges_mops()
    print("PASS: test_build_merges_mops")
    test_build_merges_price_derived_and_industry_median()
    print("PASS: test_build_merges_price_derived_and_industry_median")
    test_factor_availability_follows_provenance()
    print("PASS: test_factor_availability_follows_provenance")
    test_build_does_not_mutate_seed()
    print("PASS: test_build_does_not_mutate_seed")
    print("\nAll 13 merge_layer tests passed.")
