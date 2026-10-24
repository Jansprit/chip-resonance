"""
backtest/engine.py — 籌碼共振選股系統的回測引擎核心

對應原始需求文件（tabbit_神秘金字塔網站_財富密碼揭密.md §六 驗證框架）：

  3. 因子單獨驗效：五分位分層回測 + IC 分析（因子值 vs 未來 4 週/12 週報酬）
  4. 回測參數：每週一再平衡、持有 4~12 週、
     0.1425% 手續費 + 0.3% 交易稅 + 0.1% 滑價
  5. 核心指標：年化超額報酬、最大回撤、Sharpe、勝率、
     **多空分層價差是否單調遞增**
  6. 偏誤控制：嚴守 T+3 資料可得性（point-in-time）

**設計原則**：全部是純函數，無網路、無檔案 I/O。
只有 `select_point_in_time` 與 `factor_report` 會組裝結果，
資料由呼叫端（backend/scripts/run_backtest.py）從 point-in-time 因子庫餵進來。

⚠️ 誠實前提：真實回測需要 **point-in-time 因子值**（每一週「當時可得」的因子），
用今天的資料回測會有前視偏誤。因子庫從 v0.4.0 開始逐週累積，
累積不足時回測報告必須自報資料涵蓋率，不可宣稱策略績效。
"""
from __future__ import annotations

import math
from typing import Any, Optional

# ===== 回測參數（原始文件 §六.4）=====
FEE_RATE = 0.001425      # 手續費 0.1425%（單邊）
TAX_RATE = 0.003         # 交易稅 0.3%（賣出）
SLIPPAGE = 0.001         # 滑價 0.1%（單邊）
PERIODS_PER_YEAR = 52    # 週頻率

# 因子權重（與 data.js 一致；F9 為扣分項，不進分層）
FACTOR_IDS = ("F1", "F2", "F3", "F4", "F5", "F6", "F8", "F10")


# ============ 相關性 ============

def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _std(xs: list[float]) -> float:
    if len(xs) < 2:
        return 0.0
    m = _mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / len(xs))


def compute_ic(factor_values: list[float], returns: list[float]) -> Optional[float]:
    """
    Pearson 因子 IC（因子值與前瞻報酬的相關係數）。

    **常數因子回 None 而不是 0** —— 0 會被誤讀成「完全不預測」，
    而實際意義是「無法計算」。
    """
    n = min(len(factor_values), len(returns))
    if n < 3:
        return None
    x = factor_values[:n]
    y = returns[:n]
    mx, my = _mean(x), _mean(y)
    sx, sy = _std(x), _std(y)
    if sx == 0 or sy == 0:
        return None
    cov = sum((x[i] - mx) * (y[i] - my) for i in range(n))
    return cov / (n * sx * sy)


def _ranks(xs: list[float]) -> list[float]:
    """平均秩（處理並列）。"""
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def compute_rank_ic(
    factor_values: list[float],
    returns: list[float],
) -> Optional[float]:
    """Spearman Rank IC（對單調變換不敏感，比 Pearson IC 穩健）。"""
    n = min(len(factor_values), len(returns))
    if n < 3:
        return None
    return compute_ic(_ranks(factor_values[:n]), _ranks(returns[:n]))


# ============ 五分位分層 ============

def quantile_analysis(
    factor_values: list[Optional[float]],
    returns: list[Optional[float]],
    q: int = 5,
) -> list[dict[str, Any]]:
    """
    五分位分層分析：把個股依因子值分成 q 組，計算每組的平均前瞻報酬。

    回傳 [{quantile, count, mean_return}, ...]，quantile 1 = 因子值最低。
    """
    pairs = [
        (f, r) for f, r in zip(factor_values, returns)
        if f is not None and r is not None
    ]
    if not pairs or q < 2:
        return []
    pairs.sort(key=lambda p: p[0])
    n = len(pairs)
    size = n / q
    out: list[dict[str, Any]] = []
    for i in range(q):
        lo = int(i * size)
        hi = int((i + 1) * size) if i < q - 1 else n
        chunk = pairs[lo:hi]
        if not chunk:
            out.append({"quantile": i + 1, "count": 0, "mean_return": 0.0})
            continue
        out.append({
            "quantile": i + 1,
            "count": len(chunk),
            "mean_return": sum(r for _, r in chunk) / len(chunk),
        })
    return out


def quantile_spread(quantiles: list[dict[str, Any]]) -> float:
    """多空價差 = 最高分位平均報酬 − 最低分位平均報酬。

    原始文件 §六.5：「多空分層價差是否單調遞增」是核心指標。
    """
    valid = [q for q in quantiles if q.get("count")]
    if len(valid) < 2:
        return 0.0
    return valid[-1]["mean_return"] - valid[0]["mean_return"]


def is_monotonic(quantiles: list[dict[str, Any]]) -> bool:
    """分層平均報酬是否單調遞增（分層有序性檢定）。"""
    means = [q["mean_return"] for q in quantiles if q.get("count")]
    return all(means[i] <= means[i + 1] for i in range(len(means) - 1))


# ============ 交易成本 ============

def apply_trading_costs(
    turnover: float,
    fee_rate: float = FEE_RATE,
    tax_rate: float = TAX_RATE,
    slippage: float = SLIPPAGE,
) -> float:
    """
    交易成本（占名目比例，0~1）。

    turnover = 1.0 代表一進一出全部換手：
        買進手續費 + 賣出手續費 + 賣出交易稅 + 雙邊滑價
    """
    if turnover <= 0:
        return 0.0
    return turnover * (fee_rate + fee_rate + tax_rate + 2 * slippage)


# ============ 績效指標 ============

def max_drawdown(equity: list[float]) -> float:
    """最大回撤（%），從歷史高點算起。回傳負值。"""
    peak = None
    worst = 0.0
    for v in equity:
        if peak is None or v > peak:
            peak = v
        if peak:
            dd = (v / peak - 1) * 100
            if dd < worst:
                worst = dd
    return worst


def annualize_sharpe(
    returns: list[float],
    periods_per_year: int = PERIODS_PER_YEAR,
    rf: float = 0.0,
) -> Optional[float]:
    """
    年化 Sharpe（週頻率預設 52 期）。

    零波動（所有報酬相同）→ None（Sharpe 定義上無意義，不是 inf）。
    """
    if len(returns) < 2:
        return None
    std = _std(returns)
    if std == 0:
        return None
    excess = _mean(returns) - rf / periods_per_year
    return (excess / std) * math.sqrt(periods_per_year)


def hit_rate(returns: list[float]) -> float:
    """勝率（正報酬的比例）。"""
    if not returns:
        return 0.0
    return sum(1 for r in returns if r > 0) / len(returns)


def annualize_return(returns: list[float], periods_per_year: int = PERIODS_PER_YEAR) -> float:
    """年化報酬（幾何平均）。"""
    if not returns:
        return 0.0
    total = 1.0
    for r in returns:
        total *= (1 + r)
    periods = len(returns)
    if periods == 0:
        return 0.0
    return (total ** (periods_per_year / periods) - 1) * 100


# ============ 前瞻報酬 ============

def forward_return(
    prices: list[float],
    index: int,
    weeks: int = 4,
) -> Optional[float]:
    """
    前瞻報酬：從第 `index` 筆（再平衡時點）到其後第 `weeks` 週的報酬。

    prices 為由舊到新的完整價格序列（例如每週收價）。
    資料不足以往前看 `weeks` 週時回 None。

    用法：prices = [p0, p1, ..., pN]；
          index=0 → 用 p0 當基準，報酬 = p[weeks]/p[0] - 1
    """
    if index < 0 or index + weeks >= len(prices) or weeks <= 0:
        return None
    base = prices[index]
    if not base:
        return None
    return prices[index + weeks] / base - 1


# ============ point-in-time 紀律 ============

def select_point_in_time(
    rows: list[dict[str, Any]],
    rebalance_date: str,
) -> list[dict[str, Any]]:
    """
    篩選在 `rebalance_date` 當下「已經可得」的因子列。

    兩道關卡（原始文件 §六.6 的偏誤控制）：
    1. `published_at` 必須 ≤ rebalance_date（T+3 紀律）
    2. 該因子的 `available` 標記不得為 False
    """
    out: list[dict[str, Any]] = []
    for row in rows or []:
        published = str(row.get("published_at", ""))
        if published and published > rebalance_date:
            continue
        available = row.get("available")
        if isinstance(available, dict):
            if not any(available.get(fid) for fid in FACTOR_IDS):
                continue
        out.append(row)
    return out


# ============ 單一因子報告 ============

def factor_report(
    rows: list[dict[str, Any]],
    forward_returns: dict[str, Optional[float]],
    factor_id: str,
) -> dict[str, Any]:
    """
    單一因子的驗效報告（原始文件 §六.3）。

    rows：point-in-time 因子列（每列含 code / factors / available）
    forward_returns：{code: 未來 N 週報酬}
    """
    factor_values: list[Optional[float]] = []
    rets: list[Optional[float]] = []
    for row in rows:
        code = row.get("code")
        factors = row.get("factors") or {}
        available = row.get("available") or {}
        value = factors.get(factor_id)
        if value is None or available.get(factor_id) is False:
            factor_values.append(None)
            rets.append(forward_returns.get(code))
            continue
        factor_values.append(float(value))
        rets.append(forward_returns.get(code))

    quantiles = quantile_analysis(factor_values, rets, q=5)
    valid = [f for f in factor_values if f is not None]
    valid_rets = [r for f, r in zip(factor_values, rets) if f is not None and r is not None]
    return {
        "factor": factor_id,
        "samples": len(valid_rets),
        "ic": compute_ic(valid, valid_rets),
        "rank_ic": compute_rank_ic(valid, valid_rets),
        "quantiles": quantiles,
        "quantile_spread": quantile_spread(quantiles),
        "monotonic": is_monotonic(quantiles),
        "ic_ir_threshold": 0.02,
        "verdict": (
            "insufficient_data" if len(valid_rets) < 10
            else ("keep" if abs(compute_ic(valid, valid_rets) or 0) >= 0.02
                  else "downweight_or_remove")
        ),
    }
