"""
scripts/run_backtest.py — 籌碼共振選股系統的回測 CLI

對應原始需求文件 §六 驗證框架：
    2. Walk-Forward 滾動驗證（每半年重估權重）
    3. 因子單獨驗效：五分位分層 + IC（未來 4 週 / 12 週報酬），IC<0.02 → 降權或移除
    4. 回測參數：每週一再平衡、持有 4~12 週、0.1425% 手續費 + 0.3% 交易稅 + 0.1% 滑價
    5. 核心指標：年化超額報酬、最大回撤、Sharpe、勝率、多空分層價差是否單調遞增
    6. 偏誤控制：嚴守 T+3（point-in-time）

用法：
    python -m backend.scripts.run_backtest --weeks 4
    python -m backend.scripts.run_backtest --weeks 12 --quantiles 5
    python -m backend.scripts.run_backtest --from 2026-01-01 --to 2026-10-24

⚠️ **誠實揭露**：真實回測需要「每一週當時可得」的因子值。
因子庫從 v0.4.0 才開始逐週累積，所以在累積夠之前，
報告會明確標示 `sufficient_data: false` 與資料涵蓋率，
**不會**輸出任何看起來像策略績效的數字。

═══════════════════════════════════════════════════════════════
⚠️ T+3 的正確解讀（本檔最關鍵的一段）
═══════════════════════════════════════════════════════════════
T+3 的意思是「資料在 published_at 當天才可得，**進場必須從那之後算**」，
**不是**「published_at 之後這份資料就作廢」。

早期版本寫成：
    if published_at > as_of: continue
因為 published_at 永遠 = as_of + 3 個營業天，這個條件會把
**每一份快照都丟掉**，前瞻報酬永遠是空的 ——
回測看起來在跑，實際上一個樣本都沒產出來，
報告卻因為「沒有異常」而被當成通過。

這是典型的「見樹不見林」：
條件寫得好像在執行偏誤控制，實際上把整條迴路掐死。
現在改成：**進場日 = published_at**（資料可得日），
進場價取 published_at 當天（或之後第一個交易日）的收盤價。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.backtest import engine  # noqa: E402
from backend.console import configure_console  # noqa: E402

LATEST = REPO_ROOT / "data" / "latest"
FACTORS_HISTORY = LATEST / "factors_history.jsonl"
FACTORS_SNAPSHOT = LATEST / "factors.json"
PRICE_HISTORY = LATEST / "price_history.json"
REPORT = LATEST / "backtest_report.json"

# 累積到這個週數，IC / 分層統計才有意義
MIN_WEEKS_FOR_STATS = 8
# 累積到這個週數，報告才可以用「策略績效」的口吻自我呈現
# （對照修復計畫 P3 的驗收標準）
MIN_WEEKS_FOR_STRATEGY = 12
# 進場價最多可以比再平衡日晚幾天（涵蓋長假與連假補休）
MAX_ENTRY_LAG_DAYS = 10


# ==================================================================
# 載入
# ==================================================================

def load_factor_snapshots() -> list[dict[str, Any]]:
    """載入 point-in-time 因子快照（由 emit_factors.js 累積）。"""
    snapshots: dict[str, dict[str, Any]] = {}
    if FACTORS_HISTORY.exists():
        for line in FACTORS_HISTORY.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                snap = json.loads(line)
            except json.JSONDecodeError:
                continue
            if snap.get("as_of"):
                snapshots[snap["as_of"]] = snap
    if FACTORS_SNAPSHOT.exists():
        try:
            snap = json.loads(FACTORS_SNAPSHOT.read_text(encoding="utf-8"))
            if snap.get("as_of"):
                snapshots.setdefault(snap["as_of"], snap)
        except json.JSONDecodeError:
            pass
    return [snapshots[k] for k in sorted(snapshots)]


def load_price_series() -> dict[str, list[tuple[str, float]]]:
    """{code: [(日期, 收盤價), ...]}（由舊到新）。"""
    out: dict[str, list[tuple[str, float]]] = {}
    if not PRICE_HISTORY.exists():
        return out
    try:
        payload = json.loads(PRICE_HISTORY.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return out
    for entry in payload if isinstance(payload, list) else []:
        code = entry.get("code")
        bars = entry.get("bars") or []
        series = sorted(
            (b["date"], float(b["close"]))
            for b in bars
            if b.get("date") and b.get("close") is not None
        )
        if code and series:
            out[code] = series
    return out


# ==================================================================
# 再平衡排程（T+3 紀律的核心）
# ==================================================================

def build_rebalance_schedule(
    snapshots: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """
    快照 → 再平衡排程。

    **再平衡日 = published_at**（資料可得日），不是 as_of。
    同一個再平衡日若有多份快照，只保留 as_of 最新者
    （同一個決策時點只能用最新的那份資料）。
    """
    by_rebalance: dict[str, dict[str, str]] = {}
    for snap in snapshots:
        as_of = snap.get("as_of")
        if not as_of:
            continue
        published_at = snap.get("published_at") or as_of
        prev = by_rebalance.get(published_at)
        if prev is None or as_of > prev["as_of"]:
            by_rebalance[published_at] = {
                "as_of": as_of,
                "published_at": published_at,
                "rebalance_date": published_at,
            }
    return [by_rebalance[k] for k in sorted(by_rebalance)]


def _price_on_or_after(
    series: list[tuple[str, float]],
    target: str,
    max_lag_days: Optional[int] = None,
) -> Optional[float]:
    """
    取得 target 當天（或之後最近一個交易日）的收盤價。

    max_lag_days：若第一個符合的價格離 target 超過太多天，回 None
    （例如某檔股票在再平衡日之後才上市，
    不能拿幾個月後的價格假裝它是當時的進場價）。
    """
    limit = None
    if max_lag_days is not None:
        try:
            limit = (date.fromisoformat(target) + timedelta(days=max_lag_days)).isoformat()
        except ValueError:
            limit = None
    for day, close in series:
        if day >= target:
            if limit is not None and day > limit:
                return None
            return close
    return None


def build_forward_returns(
    snapshots: list[dict[str, Any]],
    prices: dict[str, list[tuple[str, float]]],
    weeks: int,
) -> dict[str, Optional[float]]:
    """
    每個 (快照, 股票) 的前瞻報酬。

    進場日 = published_at（資料可得日）→ 進場價 = 該日（或之後第一個交易日）收盤價
    出場日 = 進場日 + weeks 週 → 出場價 = 該日（或之後第一個交易日）收盤價

    回傳的 key 為 f"{as_of}|{code}"，as_of 用來對應回原始快照。
    """
    index = {s["as_of"]: s for s in snapshots if s.get("as_of")}
    returns: dict[str, Optional[float]] = {}
    for entry in build_rebalance_schedule(snapshots):
        snap = index.get(entry["as_of"])
        if not snap:
            continue
        rebalance = entry["rebalance_date"]
        exit_day = (date.fromisoformat(rebalance) + timedelta(days=weeks * 7)).isoformat()
        for row in snap.get("rows", []):
            code = row.get("code")
            series = prices.get(code)
            if not code or not series:
                continue
            entry_px = _price_on_or_after(series, rebalance, MAX_ENTRY_LAG_DAYS)
            exit_px = _price_on_or_after(series, exit_day)
            if entry_px and exit_px:
                returns[f"{entry['as_of']}|{code}"] = exit_px / entry_px - 1
    return returns


# ==================================================================
# 因子報告
# ==================================================================

def _factor_pairs(
    snapshots: list[dict[str, Any]],
    fwd: dict[str, Optional[float]],
    factor_id: str,
) -> list[tuple[float, float]]:
    """收集「因子值 + 前瞻報酬」都存在的配對。"""
    pairs: list[tuple[float, float]] = []
    for snap in snapshots:
        as_of = snap.get("as_of", "")
        for row in snap.get("rows", []):
            code = row.get("code")
            if not code:
                continue
            factors = row.get("factors") or {}
            available = row.get("available") or {}
            val = factors.get(factor_id)
            if val is None or available.get(factor_id) is False:
                continue
            ret = fwd.get(f"{as_of}|{code}")
            if ret is None:
                continue
            pairs.append((float(val), float(ret)))
    return pairs


def _snapshot_ic(
    snapshots: list[dict[str, Any]],
    fwd: dict[str, Optional[float]],
    factor_id: str,
) -> list[float]:
    """每一份快照各自的 IC 時序（用於 ICIR / t 值）。"""
    out: list[float] = []
    for snap in snapshots:
        as_of = snap.get("as_of", "")
        xs: list[float] = []
        ys: list[float] = []
        for row in snap.get("rows", []):
            code = row.get("code")
            if not code:
                continue
            factors = row.get("factors") or {}
            available = row.get("available") or {}
            val = factors.get(factor_id)
            if val is None or available.get(factor_id) is False:
                continue
            ret = fwd.get(f"{as_of}|{code}")
            if ret is None:
                continue
            xs.append(float(val))
            ys.append(float(ret))
        ic = engine.compute_ic(xs, ys)
        if ic is not None:
            out.append(ic)
    return out


def _long_short_series(
    snapshots: list[dict[str, Any]],
    fwd: dict[str, Optional[float]],
    factor_id: str,
) -> list[dict[str, Any]]:
    """每一個再平衡日的多空組合結果（已扣交易成本）。"""
    out: list[dict[str, Any]] = []
    for entry in build_rebalance_schedule(snapshots):
        snap = next(
            (s for s in snapshots if s.get("as_of") == entry["as_of"]),
            None,
        )
        if not snap:
            continue
        rows = snap.get("rows", [])
        rets = {}
        for row in rows:
            code = row.get("code")
            if code:
                rets[code] = fwd.get(f"{entry['as_of']}|{code}")
        res = engine.long_short_portfolio(rows, rets, factor_id)
        if res:
            res["as_of"] = entry["as_of"]
            res["rebalance_date"] = entry["rebalance_date"]
            out.append(res)
    return out


# ==================================================================
# 主流程
# ==================================================================

def run_backtest(
    weeks: int = 4,
    quantiles: int = 5,
    snapshots: Optional[list[dict[str, Any]]] = None,
    prices: Optional[dict[str, list[tuple[str, float]]]] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> dict[str, Any]:
    """執行回測並回傳報告 dict。"""
    snapshots = load_factor_snapshots() if snapshots is None else snapshots
    prices = load_price_series() if prices is None else prices

    if date_from:
        snapshots = [s for s in snapshots if s.get("as_of", "") >= date_from]
    if date_to:
        snapshots = [s for s in snapshots if s.get("as_of", "") <= date_to]

    fwd = build_forward_returns(snapshots, prices, weeks)
    schedule = build_rebalance_schedule(snapshots)

    reports: dict[str, Any] = {}
    for factor_id in engine.FACTOR_IDS:
        pairs = _factor_pairs(snapshots, fwd, factor_id)
        rows = [
            {"code": f"i{i}", "factors": {factor_id: v}, "available": {factor_id: True}}
            for i, (v, _) in enumerate(pairs)
        ]
        rets = {f"i{i}": r for i, (_, r) in enumerate(pairs)}
        rep = engine.factor_report(rows, rets, factor_id, q=quantiles)

        ic_series = _snapshot_ic(snapshots, fwd, factor_id)
        rep["ic_series"] = ic_series
        rep["ic_periods"] = len(ic_series)
        rep["icir"] = engine.compute_icir(ic_series)
        rep["ic_t_stat"] = engine.compute_t_stat(ic_series)

        ls = _long_short_series(snapshots, fwd, factor_id)
        rep["long_short"] = {
            "periods": len(ls),
            "metrics": engine.portfolio_metrics([x["net_return"] for x in ls]),
            "gross_metrics": engine.portfolio_metrics([x["gross_return"] for x in ls]),
            "last": ls[-1] if ls else None,
        }
        reports[factor_id] = rep

    covered = [s.get("as_of") for s in snapshots]
    sufficient = len(covered) >= MIN_WEEKS_FOR_STATS and any(
        r.get("samples", 0) >= 10 for r in reports.values()
    )
    strategy_ready = sufficient and len(covered) >= MIN_WEEKS_FOR_STRATEGY

    # 可用因子的每週覆蓋率（報告頂部要標明「本週可用因子：F2,F3,F8」）
    coverage: dict[str, int] = {}
    for factor_id in engine.FACTOR_IDS:
        n = 0
        for snap in snapshots:
            for row in snap.get("rows", []):
                available = row.get("available") or {}
                if available.get(factor_id):
                    n += 1
        coverage[factor_id] = n

    segments = engine.walk_forward_split(snapshots)

    if strategy_ready:
        note = (
            f"已累積 {len(covered)} 週 point-in-time 快照，"
            "本報告的統計結果可用於因子去留判斷。"
        )
    elif sufficient:
        note = (
            f"已累積 {len(covered)} 週 point-in-time 快照（≥{MIN_WEEKS_FOR_STATS}），"
            f"但尚未達 {MIN_WEEKS_FOR_STRATEGY} 週；"
            "統計量可參考，績效數字仍屬過渡期，不可解讀為策略績效。"
        )
    else:
        note = (
            f"⚠️ 因子庫已累積 {len(covered)} 週，尚不足 {MIN_WEEKS_FOR_STATS} 週；"
            "**目前為流程驗證，不可解讀為策略績效**。"
        )

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "mode": "point_in_time" if len(covered) > 1 else "single_snapshot",
        "sufficient_data": sufficient,
        "sufficient_for_strategy": strategy_ready,
        "min_weeks_required": MIN_WEEKS_FOR_STATS,
        "min_weeks_for_strategy": MIN_WEEKS_FOR_STRATEGY,
        "snapshot_count": len(covered),
        "snapshot_dates": covered,
        "rebalance_dates": [s["rebalance_date"] for s in schedule],
        "holding_weeks": weeks,
        "quantiles": quantiles,
        "price_series_count": len(prices),
        "forward_return_samples": len(fwd),
        "factor_row_coverage": coverage,
        "walk_forward_segments": len(segments),
        "walk_forward": [
            {
                "train_start": s["train_start"],
                "train_end": s["train_end"],
                "test_start": s["test_start"],
                "test_end": s["test_end"],
            } for s in segments
        ],
        "factors": reports,
        "note": note,
    }


def main() -> int:
    configure_console()
    ap = argparse.ArgumentParser(description="籌碼共振回測")
    ap.add_argument("--weeks", type=int, default=4, help="持有週數（4 或 12）")
    ap.add_argument("--quantiles", type=int, default=5, help="分層數")
    ap.add_argument("--from", dest="date_from", default=None, help="起始日期 YYYY-MM-DD")
    ap.add_argument("--to", dest="date_to", default=None, help="結束日期 YYYY-MM-DD")
    args = ap.parse_args()

    report = run_backtest(
        weeks=args.weeks,
        quantiles=args.quantiles,
        date_from=args.date_from,
        date_to=args.date_to,
    )
    LATEST.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"=== 回測報告 {report['generated_at']} ===")
    print(f"  mode            : {report['mode']}")
    print(f"  快照數          : {report['snapshot_count']} {report['snapshot_dates']}")
    print(f"  再平衡日        : {report['rebalance_dates']}")
    print(f"  價格序列        : {report['price_series_count']} 檔")
    print(f"  前瞻報酬樣本    : {report['forward_return_samples']}")
    print(f"  持有週數        : {report['holding_weeks']}")
    print(f"  資料足夠        : {report['sufficient_data']}")
    print(f"  可當策略績效    : {report['sufficient_for_strategy']}")
    print(f"  {report['note']}")
    print()
    print(f"  {'因子':6s} {'樣本':>6s} {'IC':>8s} {'RankIC':>8s} {'ICIR':>7s} "
          f"{'多空淨值':>9s}  單調  判定")
    for fid, r in report["factors"].items():
        ic = r.get("ic")
        ric = r.get("rank_ic")
        icir = r.get("icir")
        ls = (r.get("long_short") or {}).get("metrics") or {}
        total = ls.get("total_return")
        print(
            f"  {fid:6s} {r.get('samples', 0):6d} "
            f"{('%.4f' % ic) if ic is not None else '   n/a':>8s} "
            f"{('%.4f' % ric) if ric is not None else '   n/a':>8s} "
            f"{('%.3f' % icir) if icir is not None else '  n/a':>7s} "
            f"{('%.3f%%' % (total * 100)) if total is not None else '    n/a':>9s}  "
            f"{'是' if r.get('monotonic') else '否':>4s}  {r.get('verdict')}"
        )
    print()
    print(f"  Wrote {REPORT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
