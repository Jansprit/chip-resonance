"""
backtest — 籌碼共振選股系統的回測引擎

對應原始需求文件（tabbit_神秘金字塔網站_財富密碼揭密.md §六 驗證框架）。

⚠️ 誠實前提：真實回測需要 **point-in-time 因子值**。
用今天的資料回測會有前視偏誤，因此因子值必須逐週累積到
`data/latest/factors.json`（`as_of` + `published_at` = T+3）。
累積不足時，報告必須自報資料涵蓋率，不可宣稱策略績效。
"""

from .engine import (  # noqa: F401
    EPS,
    FACTOR_IDS,
    annualize_return,
    annualize_sharpe,
    apply_trading_costs,
    compute_ic,
    compute_icir,
    compute_rank_ic,
    compute_t_stat,
    factor_report,
    forward_return,
    hit_rate,
    is_monotonic,
    long_short_portfolio,
    max_drawdown,
    portfolio_metrics,
    quantile_analysis,
    quantile_spread,
    select_point_in_time,
    walk_forward_split,
)

__all__ = [
    "EPS",
    "FACTOR_IDS",
    "annualize_return",
    "annualize_sharpe",
    "apply_trading_costs",
    "compute_ic",
    "compute_icir",
    "compute_rank_ic",
    "compute_t_stat",
    "factor_report",
    "forward_return",
    "hit_rate",
    "is_monotonic",
    "long_short_portfolio",
    "max_drawdown",
    "portfolio_metrics",
    "quantile_analysis",
    "quantile_spread",
    "select_point_in_time",
    "walk_forward_split",
]
