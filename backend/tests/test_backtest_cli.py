"""
test_backtest_cli.py — 回測 CLI 的 point-in-time 紀律與報告結構測試

對應原始需求文件 §六 驗證框架：
    6. 偏誤控制：嚴守 T+3 資料可得性（point-in-time）

**為什麼需要獨立測試 CLI 層？**
引擎（backend/backtest/engine.py）是純函數，已經測得很紮實；
但「引擎算得對」不代表「CLI 餵給引擎的資料是對的」。
v0.4.0 開發過程中就在這一層出過一個致命錯誤：

    `published_at > as_of → skip`

T+3 的意思是「published_at 之後才可以用這份資料**進場**」，
不是「published_at 之後這份資料就作廢」。
因為 published_at 永遠 = as_of + 3 個工作天，那個條件會把
**每一份快照都丟掉**，前瞻報酬永遠是空的 ——
回測看起來在跑，實際上一個樣本都沒產出來。

這就是典型的「見樹不見林」：
條件寫得好像在執行偏誤控制，實際上把整條迴路掐死。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.scripts import run_backtest as bt


# ============ 輔助 ============

def _snapshot(as_of: str, published_at: str, code: str = "2330",
              factor: str = "F2", value: float = 60.0) -> dict:
    return {
        "as_of": as_of,
        "published_at": published_at,
        "mode": "point_in_time",
        "rows": [{
            "code": code,
            "factors": {factor: value},
            "available": {factor: True},
        }],
    }


# ============ T+3 進場紀律 ============

def test_forward_return_enters_at_published_at_not_as_of():
    """
    核心測試：進場價必須取自 published_at（資料可得日）之後的第一個收盤價。

    若用 as_of 進場，就是前視偏誤（look-ahead bias）：
    10/22 收盤時根本還不知道 10/27 才公布的籌碼資料，
    卻用 10/22 的價格假裝已經持有。
    """
    snapshots = [_snapshot("2026-10-22", "2026-10-27")]
    prices = {"2330": [
        ("2026-10-22", 100.0),   # as_of 當天：此時資料還沒公布
        ("2026-10-23", 101.0),
        ("2026-10-27", 110.0),   # published_at：資料可得，進場
        ("2026-11-24", 121.0),   # published_at + 4 週，出場
    ]}
    fwd = bt.build_forward_returns(snapshots, prices, weeks=4)
    assert "2026-10-22|2330" in fwd, "快照的每檔股票都應該有前瞻報酬"
    # 110 → 121 = +10%；若錯用 as_of 價格（100）會變成 +21%
    assert abs(fwd["2026-10-22|2330"] - (121.0 / 110.0 - 1)) < 1e-9


def test_forward_return_never_uses_price_before_publication():
    """即使 published_at 之前有更低（更好）的價格，也不得用來進場。"""
    snapshots = [_snapshot("2026-10-22", "2026-10-27")]
    prices = {"2330": [
        ("2026-10-22", 50.0),    # 故意放一個「很划算」的價格
        ("2026-10-27", 110.0),
        ("2026-11-24", 121.0),
    ]}
    fwd = bt.build_forward_returns(snapshots, prices, weeks=4)
    assert abs(fwd["2026-10-22|2330"] - (121.0 / 110.0 - 1)) < 1e-9


def test_forward_return_same_day_publication_enters_same_day():
    """published_at == as_of（無資料落差）時，直接用當天價格進場。"""
    snapshots = [_snapshot("2026-10-22", "2026-10-22")]
    prices = {"2330": [("2026-10-22", 100.0), ("2026-11-19", 110.0)]}
    fwd = bt.build_forward_returns(snapshots, prices, weeks=4)
    assert abs(fwd["2026-10-22|2330"] - 0.10) < 1e-9


def test_forward_return_skips_when_no_price_after_publication():
    """published_at 之後沒有價格 → 不產生報酬（不可用 as_of 價格補）。"""
    snapshots = [_snapshot("2026-10-22", "2026-10-27")]
    prices = {"2330": [("2026-10-22", 100.0), ("2026-10-23", 101.0)]}
    fwd = bt.build_forward_returns(snapshots, prices, weeks=4)
    assert "2026-10-22|2330" not in fwd


def test_forward_return_skips_when_exit_price_missing():
    """出場價不足（持有週數還沒走完）→ 不產生報酬。"""
    snapshots = [_snapshot("2026-10-22", "2026-10-27")]
    prices = {"2330": [("2026-10-27", 110.0), ("2026-10-28", 112.0)]}
    fwd = bt.build_forward_returns(snapshots, prices, weeks=4)
    assert "2026-10-22|2330" not in fwd


def test_forward_return_skips_unknown_code():
    snapshots = [_snapshot("2026-10-22", "2026-10-27", code="9999")]
    prices = {"2330": [("2026-10-27", 110.0), ("2026-11-24", 121.0)]}
    fwd = bt.build_forward_returns(snapshots, prices, weeks=4)
    assert fwd == {}


def test_forward_return_holding_period_is_configurable():
    """持有週數改變 → 出場日改變 → 報酬改變。"""
    snapshots = [_snapshot("2026-10-22", "2026-10-27")]
    prices = {"2330": [
        ("2026-10-27", 100.0),
        ("2026-11-03", 105.0),   # +1 週
        ("2026-11-24", 120.0),   # +4 週
    ]}
    fwd4 = bt.build_forward_returns(snapshots, prices, weeks=4)
    fwd1 = bt.build_forward_returns(snapshots, prices, weeks=1)
    assert abs(fwd4["2026-10-22|2330"] - 0.20) < 1e-9
    assert abs(fwd1["2026-10-22|2330"] - 0.05) < 1e-9


def test_rebalance_date_is_published_at():
    """再平衡日 = published_at（資料可得日），不是 as_of。"""
    snaps = [
        _snapshot("2026-10-15", "2026-10-20"),
        _snapshot("2026-10-22", "2026-10-27"),
    ]
    schedule = bt.build_rebalance_schedule(snaps)
    assert [s["rebalance_date"] for s in schedule] == ["2026-10-20", "2026-10-27"]


def test_rebalance_schedule_dedupes_same_rebalance_date():
    """同一個再平衡日有多份快照 → 只保留 as_of 最新者（最新資料優先）。"""
    snaps = [
        _snapshot("2026-10-15", "2026-10-20"),
        _snapshot("2026-10-16", "2026-10-20"),
    ]
    schedule = bt.build_rebalance_schedule(snaps)
    assert len(schedule) == 1
    assert schedule[0]["as_of"] == "2026-10-16"


# ============ 報告結構 ============

def test_run_backtest_report_has_required_keys():
    report = bt.run_backtest(
        weeks=4, quantiles=5,
        snapshots=[_snapshot("2026-10-22", "2026-10-27")],
        prices={"2330": [("2026-10-27", 110.0), ("2026-11-24", 121.0)]},
    )
    for key in ("generated_at", "mode", "sufficient_data", "min_weeks_required",
                "snapshot_count", "snapshot_dates", "holding_weeks", "quantiles",
                "factors", "note"):
        assert key in report, f"報告缺少 {key}"
    for fid in ("F1", "F2", "F3", "F4", "F5", "F6", "F8", "F10"):
        assert fid in report["factors"], f"報告缺少因子 {fid}"


def test_run_backtest_marks_insufficient_data_for_single_snapshot():
    """只有一份快照 → 樣本不足 → sufficient_data 必須是 False，且明說不可當績效。"""
    report = bt.run_backtest(
        weeks=4, quantiles=5,
        snapshots=[_snapshot("2026-10-22", "2026-10-27")],
        prices={"2330": [("2026-10-27", 110.0), ("2026-11-24", 121.0)]},
    )
    assert report["sufficient_data"] is False
    assert report["snapshot_count"] == 1
    assert "策略績效" in report["note"]
    assert report["mode"] == "single_snapshot"


def test_run_backtest_marks_insufficient_data_below_min_weeks():
    """7 份快照 → 仍未達 8 週門檻 → sufficient_data False。"""
    snaps = [_snapshot(f"2026-08-{d:02d}", f"2026-08-{d + 3:02d}") for d in range(1, 8)]
    prices = {"2330": [("2026-08-04", 100.0), ("2026-12-01", 120.0)]}
    report = bt.run_backtest(weeks=4, snapshots=snaps, prices=prices)
    assert report["snapshot_count"] == 7
    assert report["sufficient_data"] is False


def test_run_backtest_reports_sufficient_data_with_enough_snapshots():
    """8 份快照 + 足夠樣本 → sufficient_data True。"""
    snaps = []
    for i in range(8):
        as_of = f"2026-0{(i % 9) + 1}-15"
        snaps.append(_snapshot(as_of, as_of))
    # 12 檔股票，價格隨因子值單調遞增 → 應有正 IC
    prices = {}
    for i in range(12):
        code = f"9{i:03d}"
        prices[code] = [("2026-01-15", 100.0), ("2026-12-01", 100.0 + i * 5)]
    snaps = []
    for i in range(8):
        as_of = f"2026-0{(i % 9) + 1}-15"
        rows = [{
            "code": f"9{j:03d}",
            "factors": {"F2": float(j)},
            "available": {"F2": True},
        } for j in range(12)]
        snaps.append({"as_of": as_of, "published_at": as_of, "rows": rows})
    report = bt.run_backtest(weeks=4, snapshots=snaps, prices=prices)
    assert report["snapshot_count"] == 8
    assert report["sufficient_data"] is True
    assert report["mode"] == "point_in_time"
    f2 = report["factors"]["F2"]
    assert f2["samples"] >= 10
    assert f2["ic"] is not None and f2["ic"] > 0
    assert f2["quantile_spread"] > 0
    assert f2["monotonic"] is True
    assert f2["verdict"] == "keep"


def test_run_backtest_counts_forward_return_samples():
    report = bt.run_backtest(
        weeks=4, quantiles=5,
        snapshots=[_snapshot("2026-10-22", "2026-10-27")],
        prices={"2330": [("2026-10-27", 110.0), ("2026-11-24", 121.0)]},
    )
    assert report["forward_return_samples"] == 1


def test_run_backtest_handles_empty_inputs():
    """完全沒有資料時不能爆掉，且必須誠實標示不足。"""
    report = bt.run_backtest(weeks=4, snapshots=[], prices={})
    assert report["snapshot_count"] == 0
    assert report["sufficient_data"] is False
    assert report["price_series_count"] == 0


def test_load_price_series_handles_bars_shape():
    """price_history.json 的 bars 結構要能被正確解析（真實檔案格式）。"""
    import json
    import tempfile

    payload = [{"code": "2330", "bars": [
        {"date": "2026-01-02", "close": 100.0},
        {"date": "2026-01-05", "close": 105.0},
    ]}]
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "price_history.json"
        p.write_text(json.dumps(payload), encoding="utf-8")
        original = bt.PRICE_HISTORY
        try:
            bt.PRICE_HISTORY = p
            series = bt.load_price_series()
        finally:
            bt.PRICE_HISTORY = original
    assert series["2330"] == [("2026-01-02", 100.0), ("2026-01-05", 105.0)]


if __name__ == "__main__":
    fns = [
        test_forward_return_enters_at_published_at_not_as_of,
        test_forward_return_never_uses_price_before_publication,
        test_forward_return_same_day_publication_enters_same_day,
        test_forward_return_skips_when_no_price_after_publication,
        test_forward_return_skips_when_exit_price_missing,
        test_forward_return_skips_unknown_code,
        test_forward_return_holding_period_is_configurable,
        test_rebalance_date_is_published_at,
        test_rebalance_schedule_dedupes_same_rebalance_date,
        test_run_backtest_report_has_required_keys,
        test_run_backtest_marks_insufficient_data_for_single_snapshot,
        test_run_backtest_marks_insufficient_data_below_min_weeks,
        test_run_backtest_reports_sufficient_data_with_enough_snapshots,
        test_run_backtest_counts_forward_return_samples,
        test_run_backtest_handles_empty_inputs,
        test_load_price_series_handles_bars_shape,
    ]
    for fn in fns:
        fn()
        print(f"PASS: {fn.__name__}")
    print(f"\nAll {len(fns)} backtest CLI tests passed.")
