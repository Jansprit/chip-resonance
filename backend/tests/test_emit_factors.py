"""
test_emit_factors.py — 因子庫發佈腳本（emit_factors.js）的行為測試

對應原始需求文件 §七：
    log_to_backtest_db(date, F, score)
以及 §六.6 的偏誤控制（嚴守 T+3 資料可得性）。

**為什麼需要測試這支腳本？**
因子庫是回測的唯一資料來源。如果它「看起來有輸出」但其實：
    - 把不可用的因子標成可用 → 回測會用示意值算出假 IC
    - published_at 算錯 → 整份回測帶著前視偏誤
    - 每週重複 append → 歷史檔膨脹，樣本數灌水
那麼回測報告會「看起來很正常」，但結論完全不可信。

所以這裡直接用真實的 Node 執行 emit_factors.js（不是 mock），
驗證它對真實 data.js 的行為。
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
EMIT = REPO / "backend" / "scripts" / "emit_factors.js"

NODE = shutil.which("node")
if NODE is None:  # pragma: no cover - CI 有 node，本地若沒有則明確報錯
    print("FATAL: 需要 node 才能執行 emit_factors.js 測試", file=sys.stderr)
    sys.exit(1)


# ============ 輔助 ============

def _stock(code: str, **overrides) -> dict:
    """一檔通過所有硬性過濾、且 F2 為真實資料的股票。"""
    base = {
        "code": code,
        "name": f"測試{code}",
        "industry": "SEMI",
        "price": 100.0,
        "avg_volume": 5000,
        "director_pledge": 10.0,
        "eps_q4": 5.0,
        "list_year": 20,
        "warning": False,
        "margin_pct": 30.0,
        "dt_ratio": 20.0,
        "pct_1000up_now": 50.0,
        "pct_1000up_w1": 49.0,
        "pct_1000up_w2": 48.0,
        "pct_1000up_w3": 47.0,
        "pct_400up": 50.0,
        "pct_400up_52w_high": False,
        "holder_cnt_change_8w": -1.0,
        "avg_lot_change_8w": 1.0,
        "drawdown_120d": -5.0,
        "ret_60d": 1.0,
        "industry_ret_60d_med": 10.0,
        "director_holding_change_3m": 1.0,
        "div_years": 10,
        "yield_now": 3.0,
        "yield_5y_avg": 2.5,
        "crash_60d": False,
        "pct_1000up_trend": "+",
        "is_60d_high": False,
        "date": "2026-10-22",
        "exchange": "TWSE",
    }
    prov = {k: "illustrative" for k in base}
    prov["price"] = "real"
    prov["industry_ret_60d_med"] = "real"   # → F2 可用
    prov["ret_60d"] = "real"
    prov["pct_1000up_now"] = "real"
    prov["drawdown_120d"] = "real"
    base["_provenance"] = prov
    base.update(overrides)
    return base


def _write_universe(tmp: Path, stocks: list[dict], name: str = "universe.json") -> Path:
    p = tmp / name
    p.write_text(json.dumps(stocks, ensure_ascii=False), encoding="utf-8")
    return p


def _run_emit(input_path: Path, output_path: Path, history_path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [NODE, str(EMIT), str(input_path), str(output_path), str(history_path)],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )


def _history_lines(history_path: Path) -> list[dict]:
    if not history_path.exists():
        return []
    return [
        json.loads(line)
        for line in history_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


# ============ 測試 ============

def test_emit_writes_factors_json():
    """產出 factors.json，含 as_of / published_at / rows。"""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        src = _write_universe(tmp, [_stock("2330"), _stock("2454")])
        out = tmp / "factors.json"
        hist = tmp / "factors_history.jsonl"
        proc = _run_emit(src, out, hist)
        assert proc.returncode == 0, f"emit_factors 失敗：{proc.stderr}"
        payload = json.loads(out.read_text(encoding="utf-8"))
        assert payload["as_of"] == "2026-10-22"
        assert payload["published_at"] == "2026-10-27"   # T+3 營業日
        assert payload["mode"] == "point_in_time"
        assert len(payload["rows"]) == 2
        codes = {r["code"] for r in payload["rows"]}
        assert codes == {"2330", "2454"}


def test_emit_published_at_is_three_business_days():
    """published_at = as_of + 3 個營業日（跳過週末）。"""
    cases = [
        ("2026-10-22", "2026-10-27"),   # 四 → 二
        ("2026-10-23", "2026-10-28"),   # 五 → 三
        ("2026-10-26", "2026-10-29"),   # 一 → 四
    ]
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        for as_of, expected in cases:
            src = _write_universe(tmp, [_stock("2330", date=as_of)], name=f"u_{as_of}.json")
            out = tmp / f"f_{as_of}.json"
            hist = tmp / f"h_{as_of}.jsonl"
            proc = _run_emit(src, out, hist)
            assert proc.returncode == 0, proc.stderr
            payload = json.loads(out.read_text(encoding="utf-8"))
            assert payload["as_of"] == as_of
            assert payload["published_at"] == expected, (
                f"{as_of} 的 published_at 應為 {expected}，實際 {payload['published_at']}"
            )


def test_emit_marks_unavailable_factors_as_null():
    """provenance 不是 real 的因子 → available=False 且值為 null（不可用 0 冒充）。"""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        src = _write_universe(tmp, [_stock("2330")])
        out = tmp / "factors.json"
        hist = tmp / "factors_history.jsonl"
        proc = _run_emit(src, out, hist)
        assert proc.returncode == 0, proc.stderr
        row = json.loads(out.read_text(encoding="utf-8"))["rows"][0]
        # F2 的輸入 industry_ret_60d_med 是 real → 可用
        assert row["available"]["F2"] is True
        assert row["factors"]["F2"] is not None
        # F1 的輸入 pct_1000up_w1/w2/w3 都是 illustrative → 不可用
        assert row["available"]["F1"] is False
        assert row["factors"]["F1"] is None, "不可用因子必須是 null，不是 0"


def test_emit_appends_to_history():
    """因子快照必須累積進 factors_history.jsonl，否則回測永遠只有一週樣本。"""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        src = _write_universe(tmp, [_stock("2330")])
        out = tmp / "factors.json"
        hist = tmp / "factors_history.jsonl"
        proc = _run_emit(src, out, hist)
        assert proc.returncode == 0, proc.stderr
        lines = _history_lines(hist)
        assert len(lines) == 1
        assert lines[0]["as_of"] == "2026-10-22"
        assert lines[0]["published_at"] == "2026-10-27"


def test_emit_history_dedupes_same_as_of():
    """同一週重跑 → 歷史檔不得出現兩筆相同 as_of（否則樣本數灌水）。"""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        src = _write_universe(tmp, [_stock("2330")])
        out = tmp / "factors.json"
        hist = tmp / "factors_history.jsonl"
        for _ in range(3):
            proc = _run_emit(src, out, hist)
            assert proc.returncode == 0, proc.stderr
        lines = _history_lines(hist)
        assert len(lines) == 1, f"重跑 3 次應只有 1 筆快照，實際 {len(lines)} 筆"


def test_emit_history_accumulates_across_weeks():
    """不同週的快照要依序累積，且按 as_of 由舊到新排序。"""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        out = tmp / "factors.json"
        hist = tmp / "factors_history.jsonl"
        for as_of in ("2026-10-22", "2026-10-15", "2026-10-29"):
            src = _write_universe(tmp, [_stock("2330", date=as_of)], name=f"u_{as_of}.json")
            proc = _run_emit(src, out, hist)
            assert proc.returncode == 0, proc.stderr
        lines = _history_lines(hist)
        assert len(lines) == 3
        assert [l["as_of"] for l in lines] == ["2026-10-15", "2026-10-22", "2026-10-29"]


def test_emit_history_updates_same_as_of_with_newer_data():
    """同一 as_of 但資料被修正 → 覆蓋舊的那筆（保留最新版本）。"""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        out = tmp / "factors.json"
        hist = tmp / "factors_history.jsonl"
        src1 = _write_universe(tmp, [_stock("2330", price=100.0)], name="u1.json")
        src2 = _write_universe(tmp, [_stock("2330", price=123.0)], name="u2.json")
        assert _run_emit(src1, out, hist).returncode == 0
        assert _run_emit(src2, out, hist).returncode == 0
        lines = _history_lines(hist)
        assert len(lines) == 1
        assert lines[0]["rows"][0]["price"] == 123.0


def test_emit_missing_input_is_skipped_gracefully():
    """輸入檔不存在時應安靜跳過（pipeline 在 CI 上可能沒有資料），不能讓流程整個爆掉。"""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        out = tmp / "factors.json"
        hist = tmp / "factors_history.jsonl"
        proc = _run_emit(tmp / "nope.json", out, hist)
        assert proc.returncode == 0, proc.stderr
        assert not out.exists()
        assert not hist.exists()


def test_emit_output_matches_history_entry():
    """history 裡的內容必須與當次輸出的 factors.json 完全一致。"""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        src = _write_universe(tmp, [_stock("2330"), _stock("2454")])
        out = tmp / "factors.json"
        hist = tmp / "factors_history.jsonl"
        assert _run_emit(src, out, hist).returncode == 0
        payload = json.loads(out.read_text(encoding="utf-8"))
        lines = _history_lines(hist)
        assert lines[0] == payload


def test_emit_includes_all_positive_factors():
    """因子庫要涵蓋全部正分因子（F1~F10，不含扣分項 F9）。"""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        src = _write_universe(tmp, [_stock("2330")])
        out = tmp / "factors.json"
        hist = tmp / "factors_history.jsonl"
        assert _run_emit(src, out, hist).returncode == 0
        payload = json.loads(out.read_text(encoding="utf-8"))
        assert payload["factor_count"] == 8
        row = payload["rows"][0]
        assert set(row["factors"]) == {"F1", "F2", "F3", "F4", "F5", "F6", "F8", "F10"}

if __name__ == "__main__":
    # 自動發現所有 test_ 函式 —— 新增測試不可能再被靜默遺漏。
    # 見 backend/tests/_runner.py 的說明。
    import sys as _sys
    from pathlib import Path as _Path

    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
    from backend.tests._runner import run_tests

    run_tests(globals(), "emit_factors")
