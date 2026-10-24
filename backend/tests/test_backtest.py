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


def test_pearson_ic_returns_none_for_constant_input_with_awkward_floats():
    """
    常數序列的「零變異」判定必須用浮點容差。

    [0.05, 0.05, 0.05] 的累加誤差會讓 mean = 0.05000000000000001，
    標準差算出來是 1.4e-18（不是 0），於是 `std == 0` 判斷失效，
    IC 會變成一個天知道多大的亂數。
    這不是理論問題：整份回測報告的 IC 都會被污染。
    """
    assert engine.compute_ic([0.05, 0.05, 0.05], [0.1, 0.2, 0.3]) is None
    assert engine.compute_ic([0.1, 0.1, 0.1, 0.1], [0.1, 0.2, 0.3, 0.4]) is None
    assert engine.compute_ic([0.1, 0.2, 0.3], [0.05, 0.05, 0.05]) is None


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


def test_is_monotonic_false_without_data():
    """
    沒有資料時不可宣稱「單調遞增」。

    `all([])` 在 Python 回 True —— 那是布林運算的陷阱，不是分析結論。
    報告若在 0 個樣本時顯示「單調遞增：是」，就是在講假話。
    """
    assert engine.is_monotonic([]) is False
    assert engine.is_monotonic([{"quantile": 1, "count": 0, "mean_return": 0.0}]) is False
    assert engine.is_monotonic([
        {"quantile": 1, "count": 5, "mean_return": 0.01},
        {"quantile": 2, "count": 0, "mean_return": 0.0},
    ]) is False


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


def test_annualize_sharpe_none_for_constant_returns_with_awkward_floats():
    """零波動判定同樣要用浮點容差（[0.05]*10 的累加誤差足以讓 std ≠ 0）。"""
    assert engine.annualize_sharpe([0.05] * 10) is None
    assert engine.annualize_sharpe([0.3] * 7) is None


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


# ============ 單一因子報告 ============

def test_factor_report_ic_only_pairs_rows_with_both_factor_and_return():
    """
    IC 只能用「因子值與前瞻報酬同時存在」的列來配對。

    舊版把「有因子值但沒報酬」的列也算進因子清單，卻從報酬清單裡剔除，
    兩邊長度不一致後 `compute_ic` 只取前 N 筆 → 配對錯位，
    算出來的 IC 完全不是同一組股票的相關性。
    這會讓「沒有未來報酬」的樣本（正是最容易產生假訊號的地方）
    汙染真實樣本的 IC。
    """
    rows = [
        {"code": "A", "factors": {"F2": 100.0}, "available": {"F2": True}},
        {"code": "B", "factors": {"F2": 1.0}, "available": {"F2": True}},
        {"code": "C", "factors": {"F2": 2.0}, "available": {"F2": True}},
        {"code": "D", "factors": {"F2": 3.0}, "available": {"F2": True}},
    ]
    rets = {"A": None, "B": 0.1, "C": 0.2, "D": 0.3}
    rep = engine.factor_report(rows, rets, "F2")
    assert rep["samples"] == 3
    # 只用 B/C/D → 因子與報酬完全同向 → IC = 1.0
    assert abs(rep["ic"] - 1.0) < 1e-9
    assert abs(rep["rank_ic"] - 1.0) < 1e-9


def test_factor_report_skips_unavailable_factor_even_with_return():
    """available=False 的因子不可進入配對（不管有沒有報酬）。"""
    rows = [
        {"code": "A", "factors": {"F2": 1.0}, "available": {"F2": False}},
        {"code": "B", "factors": {"F2": 2.0}, "available": {"F2": True}},
        {"code": "C", "factors": {"F2": 3.0}, "available": {"F2": True}},
        {"code": "D", "factors": {"F2": 4.0}, "available": {"F2": True}},
    ]
    rets = {"A": 0.9, "B": 0.2, "C": 0.3, "D": 0.4}
    rep = engine.factor_report(rows, rets, "F2")
    assert rep["samples"] == 3
    assert abs(rep["ic"] - 1.0) < 1e-9


def test_factor_report_verdict_matches_ic():
    """verdict 必須與實際 IC 一致（不可用錯配的 IC 判斷去留）。"""
    rows = [
        {"code": "A", "factors": {"F2": 1000.0}, "available": {"F2": True}},
    ] + [
        {"code": f"B{i}", "factors": {"F2": float(i)}, "available": {"F2": True}}
        for i in range(1, 12)
    ]
    rets = {"A": None}
    rets.update({f"B{i}": i / 100.0 for i in range(1, 12)})
    rep = engine.factor_report(rows, rets, "F2")
    assert rep["samples"] == 11
    assert rep["ic"] is not None
    expected = "keep" if abs(rep["ic"]) >= 0.02 else "downweight_or_remove"
    assert rep["verdict"] == expected


# ============ ICIR / t 值 ============

def test_compute_icir_of_constant_ic_is_none():
    """IC 序列完全相同 → 標準差為 0 → ICIR 無法定義（回 None 不是 inf）。"""
    assert engine.compute_icir([0.05, 0.05, 0.05]) is None


def test_compute_icir_positive_and_negative():
    """ICIR = IC 均值 / IC 標準差。"""
    icir = engine.compute_icir([0.04, 0.06, 0.05])
    assert icir is not None and icir > 0
    icir_neg = engine.compute_icir([-0.04, -0.06, -0.05])
    assert icir_neg is not None and icir_neg < 0


def test_compute_icir_needs_at_least_three_points():
    assert engine.compute_icir([0.05]) is None
    assert engine.compute_icir([0.05, 0.06]) is None


def test_compute_t_stat():
    """t 值 = mean / (std / sqrt(n))。"""
    xs = [0.04, 0.06, 0.05, 0.07]
    t = engine.compute_t_stat(xs)
    assert t is not None
    mean = sum(xs) / len(xs)
    var = sum((x - mean) ** 2 for x in xs) / len(xs)
    expected = mean / ((var ** 0.5) / (len(xs) ** 0.5))
    assert abs(t - expected) < 1e-9


def test_compute_t_stat_needs_two_points():
    assert engine.compute_t_stat([0.05]) is None


# ============ 多空組合 ============

def test_long_short_portfolio_uses_top_and_bottom_quantiles():
    """多空組合：做多前 20%、做空後 20%，淨值等權。"""
    rows = [
        {"code": f"S{i}", "factors": {"F2": float(i)}, "available": {"F2": True}}
        for i in range(10)
    ]
    rets = {f"S{i}": i / 100.0 for i in range(10)}
    res = engine.long_short_portfolio(rows, rets, "F2", long_pct=0.2, short_pct=0.2)
    # 前 20% = S9, S8；後 20% = S0, S1
    assert res["long_codes"] == ["S9", "S8"]
    assert res["short_codes"] == ["S0", "S1"]
    gross = (0.09 + 0.08) / 2 - (0.0 + 0.01) / 2
    assert abs(res["gross_return"] - gross) < 1e-9
    assert res["cost"] > 0
    assert abs(res["net_return"] - (gross - res["cost"])) < 1e-9


def test_long_short_portfolio_handles_insufficient_rows():
    """列數不足時無法做多空 → 回 None，不可假裝有績效。"""
    rows = [{"code": "A", "factors": {"F2": 1.0}, "available": {"F2": True}}]
    res = engine.long_short_portfolio(rows, {"A": 0.1}, "F2")
    assert res is None


def test_long_short_portfolio_skips_missing_returns():
    """缺報酬的股票不可進入多空組合。"""
    rows = [
        {"code": f"S{i}", "factors": {"F2": float(i)}, "available": {"F2": True}}
        for i in range(10)
    ]
    rets = {f"S{i}": (i / 100.0 if i >= 2 else None) for i in range(10)}
    res = engine.long_short_portfolio(rows, rets, "F2", long_pct=0.2, short_pct=0.2)
    assert res is not None
    assert "S0" not in res["short_codes"]
    assert "S1" not in res["short_codes"]


def test_portfolio_metrics_from_returns():
    """多空組合的績效指標。"""
    rets = [0.02, -0.01, 0.03, 0.015, -0.005]
    m = engine.portfolio_metrics(rets)
    assert abs(m["hit_rate"] - 0.6) < 1e-9
    assert m["sharpe"] is not None
    assert m["max_drawdown"] <= 0
    assert m["total_return"] is not None
    assert m["periods"] == 5


def test_portfolio_metrics_empty():
    m = engine.portfolio_metrics([])
    assert m["periods"] == 0
    assert m["hit_rate"] == 0.0
    assert m["sharpe"] is None


# ============ Walk-Forward ============

def test_walk_forward_split_produces_segments():
    """每段用前 train_weeks 週訓練、後 test_weeks 週驗證（原始文件 §六.2）。"""
    snaps = [{"as_of": f"2026-{1 + i // 4:02d}-0{1 + i % 4}"} for i in range(24)]
    segments = engine.walk_forward_split(snaps, train_weeks=12, test_weeks=4)
    assert len(segments) >= 1
    seg = segments[0]
    assert len(seg["train"]) == 12
    assert len(seg["test"]) == 4
    # 訓練集必須全部早於驗證集（不可偷看未來）
    assert max(s["as_of"] for s in seg["train"]) < min(s["as_of"] for s in seg["test"])


def test_walk_forward_split_empty():
    assert engine.walk_forward_split([], train_weeks=12, test_weeks=4) == []


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
    # 自動發現所有 test_ 函式 —— 新增測試不可能再被靜默遺漏。
    # 見 backend/tests/_runner.py 的說明。
    import sys as _sys
    from pathlib import Path as _Path

    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
    from backend.tests._runner import run_tests

    run_tests(globals(), "backtest")
