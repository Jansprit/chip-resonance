"""
test_schema.py — 資料檔驗證器的行為測試

**為什麼需要這份測試？**
v0.4.0 新增了 margin_balance.json / valuation.json / industry.json
三個「以 code 為 key 的物件型」資料檔，
但驗證器裡對應的分支被寫在「最外層應為 array」的檢查**之後** ——
變成永遠走不到的死碼。

症狀：CI 的資料驗證步驟直接失敗（`預期是 array，但拿到 dict`），
而且這三個檔案從來沒有被驗證過。

這份測試釘住「dict 型檔案必須能被驗證」這件事。
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

REPO = Path(__file__).resolve().parents[2]


def _run_schema(path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "backend.schema", str(path)],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )


def _write(tmp: Path, name: str, payload) -> Path:
    p = tmp / name
    p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return p


def test_margin_balance_dict_is_validated():
    with tempfile.TemporaryDirectory() as tmp:
        p = _write(Path(tmp), "margin_balance.json", {
            "2330": {
                "margin_balance": 14477.0, "margin_limit": 522035.0,
                "margin_pct": 2.77, "short_balance": 3.0,
                "short_limit": 522035.0, "short_pct": 0.0,
            },
        })
        proc = _run_schema(p)
        assert proc.returncode == 0, f"驗證失敗：{proc.stdout}\n{proc.stderr}"


def test_valuation_dict_is_validated():
    with tempfile.TemporaryDirectory() as tmp:
        p = _write(Path(tmp), "valuation.json", {
            "2330": {
                "close_price": 2385.0, "yield_now": 2.86,
                "dividend_year": 114, "pe_ratio": None, "pb_ratio": 8.9,
            },
        })
        proc = _run_schema(p)
        assert proc.returncode == 0, f"驗證失敗：{proc.stdout}\n{proc.stderr}"


def test_industry_dict_is_validated():
    with tempfile.TemporaryDirectory() as tmp:
        p = _write(Path(tmp), "industry.json", {"2330": "24"})
        proc = _run_schema(p)
        assert proc.returncode == 0, f"驗證失敗：{proc.stdout}\n{proc.stderr}"


def test_industry_dict_rejects_empty_value():
    with tempfile.TemporaryDirectory() as tmp:
        p = _write(Path(tmp), "industry.json", {"2330": "  "})
        proc = _run_schema(p)
        assert proc.returncode == 1, "空值必須被擋下"


def test_finmind_prices_list_is_validated():
    with tempfile.TemporaryDirectory() as tmp:
        p = _write(Path(tmp), "finmind_prices.json", [
            {"date": "2026-09-01", "stock_id": "2330", "close": 2400.0},
        ])
        proc = _run_schema(p)
        assert proc.returncode == 0, f"驗證失敗：{proc.stdout}\n{proc.stderr}"


def test_finmind_prices_rejects_missing_stock_id():
    with tempfile.TemporaryDirectory() as tmp:
        p = _write(Path(tmp), "finmind_prices.json", [{"date": "2026-09-01"}])
        proc = _run_schema(p)
        assert proc.returncode == 1, "缺 stock_id 必須被擋下"


def test_price_history_list_is_validated():
    with tempfile.TemporaryDirectory() as tmp:
        p = _write(Path(tmp), "price_history.json", [
            {"code": "2330", "bars": [
                {"date": "2026-09-01", "open": 1.0, "high": 2.0,
                 "low": 0.5, "close": 1.5, "volume": 100.0},
            ]},
        ])
        proc = _run_schema(p)
        assert proc.returncode == 0, f"驗證失敗：{proc.stdout}\n{proc.stderr}"


def test_unknown_file_type_is_rejected():
    """未知檔案類型必須報錯（不可放行）。"""
    with tempfile.TemporaryDirectory() as tmp:
        p = _write(Path(tmp), "weird.json", [{"a": 1}])
        proc = _run_schema(p)
        assert proc.returncode == 1, "未知類型必須回非 0"


if __name__ == "__main__":
    import sys as _sys
    from pathlib import Path as _Path

    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
    from backend.tests._runner import run_tests

    run_tests(globals(), "schema")
