"""
test_backtest.py — 回測引擎的數學核心測試

對應原始需求文件（tabbit_神秘金字塔網站_財富密碼揭密.md §六 驗證框架）：

  3. 因子單獨驗效：五分位分層回測 + IC 分析（因子值與未來 4 週/12 週報酬的相關性）
  4. 回測參數：每週一再平衡、持有 4~12 週、0.1425% 手續費 + 0.3% 交易稅 + 0.1% 滑價
  5. 核心指標：年化超額報酬、最大回撤、Sharpe、勝率、多空分層價差是否單調遞增
  6. 偏誤控制：嚴守 T+3 資料可得性

**設計原則**：純函數、無網路、無檔案 I/O → 可完整測試。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.backtest import engine


# ============ IC ============

def test_pearson_ic_perfect_positive():
    x = [1.0, 2.0, 3.0, 4.0]
    y = [2.0, 4.0, 6.0, 8.0]
    assert abs(engine.compute_ic(x, y) - 1.0) < 1e-9


def test_pearson_ic_perfect_negative():
    x = [1.0, 2.0, 3.0, 4.0]
    y = [8.0, 6.0, 4.0, 2.0]
    assert abs(engine.compute_ic(x, y) + 1.0) < 1e-9


def test_pearson_ic_returns_none_for_constant_input():
    """常數因子沒有預測力 → IC 應為 None（不可回 0，0 會被當成「無預測力」的證據）。"""
    assert engine.compute_ic([1.0, 1.0, 1.0], [1.0, 2.0, 3.0]) is None


def test_pearson_ic_returns_none_for_insufficient_data():
    assert engine.compute_ic([1.0], [2.0]) is None
    assert engine.compute_ic([], []) is None
    assert engine.compute_ic([1.0, 2.0], [1.0]) is None


def test_rank_ic_is_scale_invariant():
    """RankIC 對單調變換不敏感（這是它比 Pearson IC 穩健的原因）。"""
    x = [1.0, 2.0, 3.0, 4.0, 5.0]
    y = [1.0, 3.0, 2.0, 5.0, 4.0]
    r1 = engine.compute_rank_ic(x, y)
    r2 = engine.compute_rank_ic([v * 10 for v in x], [v + 100 for v in y])
    assert r1 is not None and r2 is not None
    assert abs(r1 - r2) < 1e-9


# ============ 五分位分層 ============

def test_quantile_analysis_monotonic_when_signal_is_perfect():
    """完美排序的因子 → 五分位平均報酬應單調遞增。"""
    n = 100
    factor = [float(i) for i in range(n)]
    rets = [float(i) / 10 for i in range(n)]
    qs = engine.quantile_analysis(factor, rets, q=5)
    assert len(qs) == 5
    means = [x["mean_return"] for x in qs]
    assert means == sorted(means), f"分層應單調遞增：{means}"
    # Q5 - Q1 價差（原始文件 §六.5 的核心指標）
    spread = engine.quantile_spread(qs)
    assert spread > 0
    assert sum(x["count"] for x in qs) == n


def test_quantile_analysis_handles_empty():
    assert engine.quantile_analysis([], []) == []
    assert engine.quantile_spread([]) == 0.0


def test_quantile_analysis_skips_missing_pairs():
    factor = [1.0, 2.0, 3.0, None]
    rets = [0.1, 0.2, None, 0.4]
    qs = engine.quantile_analysis(factor, rets, q=2)
    assert sum(x["count"] for x in qs) == 2


# ============ 交易成本 ============

def test_apply_trading_costs():
    """單邊手續費 0.1425% + 交易稅 0.3%（賣出）+ 滑價 0.1%。"""
    # 換手 100%（全買全賣）→ 成本 = 買進 0.1425% + 賣出(0.1425%+0.3%) + 滑價 0.1%*2
    cost = engine.apply_trading_costs(1.0)
    assert abs(cost - (0.001425 + 0.001425 + 0.003 + 0.002)) < 1e-9


def test_apply_trading_costs_zero_turnover():
    assert engine.apply_trading_costs(0.0) == 0.0


# ============ 績效指標 ============

def test_max_drawdown():
    """最大回撤： equity 從 100 跌到 80 → −20%"""
    dd = engine.max_drawdown([100.0, 80.0, 90.0])
    assert abs(dd - (-20.0)) < 1e-9


def test_max_drawdown_from_peak():
    """回撤是從「最高點」算起，不是從第一點。"""
    dd = engine.max_drawdown([100.0, 120.0, 80.0, 90.0])
    assert abs(dd - ((80.0 / 120.0 - 1) * 100)) < 1e-9


def test_max_drawdown_no_drawdown():
    assert engine.max_drawdown([100.0, 110.0, 120.0]) == 0.0


def test_annualize_sharpe():
    """52 週/年的週頻率： Sharpe = mean/std * sqrt(52)"""
    rets = [0.01, 0.02, -0.01, 0.03, 0.015, -0.005, 0.02, 0.01, -0.02, 0.025]
    s = engine.annualize_sharpe(rets, periods_per_year=52)
    assert s is not None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / len(rets)
    std = var ** 0.5
    expected = (mean / std) * (52 ** 0.5)
    assert abs(s - expected) < 1e-6


def test_annualize_sharpe_none_for_constant_returns():
    """零波動 → 無法定義 Sharpe，回 None 而不是 inf。"""
    assert engine.annualize_sharpe([0.01] * 10) is None


def test_hit_rate():
    assert engine.hit_rate([0.1, -0.1, 0.2, -0.2]) == 0.5
    assert engine.hit_rate([]) == 0.0


# ============ 前瞻報酬（T+3 紀律）============

def test_forward_return_uses_future_weeks():
    """前瞻報酬必須用「未來」的價格，不是過去。

    prices 為由舊到新的完整序列，index 為再平衡時點。
    """
    prices = [100.0, 101.0, 102.0, 103.0, 110.0]
    rets = engine.forward_return(prices, 0, weeks=4)
    # 110/100 - 1 = 10%
    assert abs(rets - 0.10) < 1e-9


def test_forward_return_none_when_not_enough_history():
    assert engine.forward_return([100.0, 101.0], 0, weeks=4) is None
    assert engine.forward_return([100.0, 101.0, 102.0], 0, weeks=4) is None


def test_forward_return_two_weeks():
    """index=0、weeks=2 → 對到 prices[2]。"""
    prices = [100.0, 101.0, 102.0, 121.0]
    rets = engine.forward_return(prices, 0, weeks=2)
    assert abs(rets - 0.02) < 1e-9
    # 同一序列、weeks=3 → 對到 prices[3] = 121
    assert abs(engine.forward_return(prices, 0, weeks=3) - 0.21) < 1e-9


# ============ point-in-time 紀律 ============

def test_select_point_in_time_rejects_future_publication():
    """嚴守 T+3：published_at 晚於 rebalance 日的因子值不可使用。"""
    rows = [
        {"code": "A", "as_of": "2026-10-24", "published_at": "2026-10-29",
         "factors": {"F1": 70.0}},
        {"code": "B", "as_of": "2026-10-24", "published_at": "2026-10-27",
         "factors": {"F1": 80.0}},
    ]
    usable = engine.select_point_in_time(rows, "2026-10-28")
    codes = {r["code"] for r in usable}
    assert "B" in codes
    assert "A" not in codes, "published_at 晚於 rebalance 日的資料不可用（前視偏誤）"


def test_select_point_in_time_keeps_missing_availability():
    """沒有 available 標記的因子不可使用（寧可不用，不可假裝有）。"""
    rows = [
        {"code": "A", "as_of": "2026-10-24", "published_at": "2026-10-20",
         "factors": {"F1": 70.0}},
        {"code": "C", "as_of": "2026-10-24", "published_at": "2026-10-20",
         "factors": {"F1": 90.0}, "available": {"F1": False}},
    ]
    usable = engine.select_point_in_time(rows, "2026-10-28")
    codes = {r["code"] for r in usable}
    assert "A" in codes
    assert "C" not in codes


if __name__ == "__main__":
    test_pearson_ic_perfect_positive()
    print("PASS: test_pearson_ic_perfect_positive")
    test_pearson_ic_perfect_negative()
    print("PASS: test_pearson_ic_perfect_negative")
    test_pearson_ic_returns_none_for_constant_input()
    print("PASS: test_pearson_ic_returns_none_for_constant_input")
    test_pearson_ic_returns_none_for_insufficient_data()
    print("PASS: test_pearson_ic_returns_none_for_insufficient_data")
    test_rank_ic_is_scale_invariant()
    print("PASS: test_rank_ic_is_scale_invariant")
    test_quantile_analysis_monotonic_when_signal_is_perfect()
    print("PASS: test_quantile_analysis_monotonic_when_signal_is_perfect")
    test_quantile_analysis_handles_empty()
    print("PASS: test_quantile_analysis_handles_empty")
    test_quantile_analysis_skips_missing_pairs()
    print("PASS: test_quantile_analysis_skips_missing_pairs")
    test_apply_trading_costs()
    print("PASS: test_apply_trading_costs")
    test_apply_trading_costs_zero_turnover()
    print("PASS: test_apply_trading_costs_zero_turnover")
    test_max_drawdown()
    print("PASS: test_max_drawdown")
    test_max_drawdown_no_drawdown()
    print("PASS: test_max_drawdown_no_drawdown")
    test_annualize_sharpe()
    print("PASS: test_annualize_sharpe")
    test_annualize_sharpe_none_for_constant_returns()
    print("PASS: test_annualize_sharpe_none_for_constant_returns")
    test_hit_rate()
    print("PASS: test_hit_rate")
    test_forward_return_uses_future_weeks()
    print("PASS: test_forward_return_uses_future_weeks")
    test_forward_return_none_when_not_enough_history()
    print("PASS: test_forward_return_none_when_not_enough_history")
    test_forward_return_two_weeks()
    print("PASS: test_forward_return_two_weeks")
    test_select_point_in_time_rejects_future_publication()
    print("PASS: test_select_point_in_time_rejects_future_publication")
    test_select_point_in_time_keeps_missing_availability()
    print("PASS: test_select_point_in_time_keeps_missing_availability")
    print("\nAll 20 backtest tests passed.")
