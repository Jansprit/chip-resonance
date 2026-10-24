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

# 浮點容差：判斷「這個數是不是 0」時必須用容差，
# 否則像 [0.05, 0.05, 0.05] 這種常數序列會因為累加誤差
# 算出 1e-18 的「標準差」，然後把無法計算的 IC 變成一個亂數。
# 這不是理論問題 —— 整份回測報告的 IC 會直接被污染。
EPS = 1e-12

# 因子權重（與 data.js 一致；F9 為扣分項，不進分層）
FACTOR_IDS = ("F1", "F2", "F3", "F4", "F5", "F6", "F8", "F10")


def _is_zero(x: float, eps: float = EPS) -> bool:
    """帶容差的「是否為零」判斷。"""
    return abs(x) < eps



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
    if _is_zero(sx) or _is_zero(sy):
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


# ============ ICIR / t 值 ============

def compute_icir(ic_series: list[float]) -> Optional[float]:
    """
    ICIR = IC 序列的平均值 / 標準差（原始文件 §六.3 的自我淘汰機制）。

    ICIR 比單期 IC 更能反映因子的**穩定性**：
    一個平均 IC 0.05 但忽正忽負的因子，ICIR 會很低，不該拿來當權重。

    樣本 < 3 或 IC 序列無變異 → None（定義上無意義，不是 inf / 0）。
    """
    if len(ic_series) < 3:
        return None
    std = _std(ic_series)
    if _is_zero(std):
        return None
    return _mean(ic_series) / std


def compute_t_stat(ic_series: list[float]) -> Optional[float]:
    """
    IC 序列的 t 值（檢定「IC 平均值是否顯著 ≠ 0」）。

    t = mean / (std / sqrt(n))
    """
    if len(ic_series) < 2:
        return None
    std = _std(ic_series)
    if _is_zero(std):
        return None
    return _mean(ic_series) / (std / math.sqrt(len(ic_series)))



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
    """
    分層平均報酬是否單調遞增（分層有序性檢定）。

    有效分層少於 2 個時回 False ——
    沒有資料時宣稱「單調遞增」是假的，
    `all([])` 會回 True，那是布林運算的陷阱，不是分析結論。
    """
    means = [q["mean_return"] for q in quantiles if q.get("count")]
    if len(means) < 2:
        return False
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
    if _is_zero(std):
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


def portfolio_metrics(returns: list[float]) -> dict[str, Any]:
    """
    一條報酬序列（多空組合或策略）的績效摘要。

    回傳 None 的欄位代表「定義上無意義」（例如零波動的 Sharpe），
    不可用 0 冒充 —— 0 會被誤讀成「績效為零」。
    """
    periods = len(returns)
    if periods == 0:
        return {
            "periods": 0,
            "total_return": None,
            "annualized_return": None,
            "sharpe": None,
            "max_drawdown": 0.0,
            "hit_rate": 0.0,
        }
    total = 1.0
    equity = []
    for r in returns:
        total *= (1 + r)
        equity.append(total)
    return {
        "periods": periods,
        "total_return": total - 1,
        "annualized_return": annualize_return(returns),
        "sharpe": annualize_sharpe(returns),
        "max_drawdown": max_drawdown(equity),
        "hit_rate": hit_rate(returns),
    }



# ============ 多空組合 ============

def long_short_portfolio(
    rows: list[dict[str, Any]],
    forward_returns: dict[str, Optional[float]],
    factor_id: str,
    long_pct: float = 0.2,
    short_pct: float = 0.2,
) -> Optional[dict[str, Any]]:
    """
    因子多空組合（原始文件 §六.3 的因子單獨驗效）。

    做多因子值最高的一組、做空最低的一組，各取 long_pct / short_pct，
    等權持有到期末。報酬已含交易成本。

    回傳 None 代表「做不出有意義的多空組合」（可用列數太少），
    呼叫端必須如實標示「無法評估」，不可拿 0 冒充。
    """
    pairs: list[tuple[float, str, float]] = []
    for row in rows:
        code = row.get("code")
        if not code:
            continue
        factors = row.get("factors") or {}
        available = row.get("available") or {}
        value = factors.get(factor_id)
        if value is None or available.get(factor_id) is False:
            continue
        ret = forward_returns.get(code)
        if ret is None:
            continue
        pairs.append((float(value), code, float(ret)))

    n = len(pairs)
    # 至少要有 4 列，否則多空兩邊會互相重疊，組合沒有統計意義
    if n < 4:
        return None

    pairs.sort(key=lambda p: p[0])
    n_long = max(1, int(n * long_pct + 0.5))
    n_short = max(1, int(n * short_pct + 0.5))
    # 避免多空重疊
    if n_long + n_short > n:
        n_long = max(1, n - n_short)

    shorts = pairs[:n_short]
    longs = list(reversed(pairs[n - n_long:]))   # 由高到低，符合「前 20%」的直覺

    long_ret = sum(p[2] for p in longs) / len(longs)
    short_ret = sum(p[2] for p in shorts) / len(shorts)
    gross = long_ret - short_ret

    # 每期多空兩邊都要完整換手：多頭 1 份 + 空頭 1 份
    cost = apply_trading_costs(2.0)

    return {
        "factor": factor_id,
        "n_pairs": n,
        "long_codes": [p[1] for p in longs],
        "short_codes": [p[1] for p in shorts],
        "long_return": long_ret,
        "short_return": short_ret,
        "gross_return": gross,
        "cost": cost,
        "net_return": gross - cost,
    }


# ============ Walk-Forward ============

def walk_forward_split(
    snapshots: list[dict[str, Any]],
    train_weeks: int = 52,
    test_weeks: int = 13,
) -> list[dict[str, Any]]:
    """
    Walk-Forward 滾動切分（原始文件 §六.2：「每半年用最新資料重估權重一次」）。

    每段 = 前 train_weeks 週訓練 + 後 test_weeks 週驗證，
    視窗隨著時間往前滾動。**訓練集必定早於驗證集**，不可偷看未來。
    """
    usable = sorted(
        (s for s in snapshots or [] if s.get("as_of")),
        key=lambda s: s["as_of"],
    )
    if len(usable) <= train_weeks:
        return []
    segments: list[dict[str, Any]] = []
    start = 0
    while start + train_weeks + test_weeks <= len(usable):
        train = usable[start:start + train_weeks]
        test = usable[start + train_weeks:start + train_weeks + test_weeks]
        segments.append({
            "train": train,
            "test": test,
            "train_start": train[0]["as_of"],
            "train_end": train[-1]["as_of"],
            "test_start": test[0]["as_of"],
            "test_end": test[-1]["as_of"],
        })
        start += test_weeks
    return segments


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
    q: int = 5,
) -> dict[str, Any]:
    """
    單一因子的驗效報告（原始文件 §六.3）。

    rows：point-in-time 因子列（每列含 code / factors / available）
    forward_returns：{code: 未來 N 週報酬}

    ⚠️ **配對必須嚴格**：只有「因子值存在 且 前瞻報酬存在」的列才會進入統計。
    舊版把有因子值但沒報酬的列也算進因子清單，卻從報酬清單剔除，
    兩邊長度不一致 → `compute_ic` 只取前 N 筆 → 因子與報酬**錯位配對**，
    算出來的 IC 根本不是同一組股票的相關性。
    """
    pairs: list[tuple[float, float]] = []
    for row in rows:
        code = row.get("code")
        factors = row.get("factors") or {}
        available = row.get("available") or {}
        value = factors.get(factor_id)
        if value is None or available.get(factor_id) is False:
            continue
        ret = forward_returns.get(code)
        if ret is None:
            continue
        pairs.append((float(value), float(ret)))

    factor_values = [p[0] for p in pairs]
    rets = [p[1] for p in pairs]

    quantiles = quantile_analysis(factor_values, rets, q=q)
    ic = compute_ic(factor_values, rets)
    rank_ic = compute_rank_ic(factor_values, rets)
    samples = len(pairs)

    if samples < 10:
        verdict = "insufficient_data"
    elif ic is None:
        verdict = "ic_undefined"       # 因子值無變異 → 無法定義 IC
    elif abs(ic) >= 0.02:
        verdict = "keep"
    else:
        verdict = "downweight_or_remove"

    return {
        "factor": factor_id,
        "samples": samples,
        "ic": ic,
        "rank_ic": rank_ic,
        "quantiles": quantiles,
        "quantile_spread": quantile_spread(quantiles),
        "monotonic": is_monotonic(quantiles),
        "ic_ir_threshold": 0.02,
        "verdict": verdict,
    }

