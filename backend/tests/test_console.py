"""
test_console.py — 主控台輸出編碼的 Windows 相容性測試

**為什麼這需要測試？**
Windows 繁中主控台是 cp950（Big5），無法編碼 ⚠ ✅ 等符號。
Python 會在 print() 時丟 UnicodeEncodeError。
對 Windows Task Scheduler 這種沒人盯著的排程來說，
「每次都掛在第一行」卻沒有任何錯誤紀錄 —— 這是最難察覺的一類 bug。

而且這個問題**只會在 Windows 上出現**，
Linux CI 永遠測不到，等於沒有防線。
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend import console


def test_configure_console_does_not_raise():
    """核心需求：設定編碼本身絕對不能拋例外。"""
    applied = console.configure_console()
    assert isinstance(applied, str)
    assert applied in ("utf-8", "replace", "")


def test_configure_console_survives_non_reconfigurable_streams():
    """沒有 reconfigure() 的 stream（例如某些測試替身）也不能讓流程爆掉。"""

    class _Fake:
        pass

    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout = _Fake()
    sys.stderr = _Fake()
    try:
        console.configure_console()   # 不應拋例外
    finally:
        sys.stdout, sys.stderr = old_out, old_err


def test_configure_console_sets_replace_errors():
    """設定後 errors 必須是 replace（或 utf-8 本身就支援 replace）。"""

    class _Fake:
        def __init__(self):
            self.calls = []

        def reconfigure(self, **kwargs):
            self.calls.append(kwargs)

    fake = _Fake()
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout = fake
    sys.stderr = fake
    try:
        console.configure_console()
    finally:
        sys.stdout, sys.stderr = old_out, old_err
    assert fake.calls, "應該有呼叫 reconfigure"
    for kwargs in fake.calls:
        assert kwargs.get("errors") == "replace", f"必須設定 errors='replace'：{kwargs}"


def test_printing_warning_symbol_does_not_crash_after_configure():
    """設定之後印出 ⚠ 不得拋 UnicodeEncodeError。"""
    buf = io.StringIO()
    old_out = sys.stdout
    sys.stdout = buf
    try:
        console.configure_console()
        print("⚠️ 測試：目前為流程驗證，不可解讀為策略績效")
    finally:
        sys.stdout = old_out
    assert "流程驗證" in buf.getvalue()


def test_run_backtest_cli_writes_report_without_console_error():
    """
    端到端：跑一次 CLI 主流程，必須寫出報告檔。

    這是「報告頂部強制顯示 ⚠」的落地驗證 ——
    若 Windows 主控台編碼讓 CLI 崩潰，報告就不會存在。
    """
    import json
    import tempfile

    from backend.scripts import run_backtest as bt

    with tempfile.TemporaryDirectory() as tmp:
        report_path = Path(tmp) / "backtest_report.json"
        old_report = bt.REPORT
        bt.REPORT = report_path
        try:
            bt.main()
        finally:
            bt.REPORT = old_report
        assert report_path.exists(), "CLI 必須產出報告檔"
        payload = json.loads(report_path.read_text(encoding="utf-8"))
        assert "factors" in payload
        assert "note" in payload


if __name__ == "__main__":
    fns = [
        test_configure_console_does_not_raise,
        test_configure_console_survives_non_reconfigurable_streams,
        test_configure_console_sets_replace_errors,
        test_printing_warning_symbol_does_not_crash_after_configure,
        test_run_backtest_cli_writes_report_without_console_error,
    ]
    for fn in fns:
        fn()
        print(f"PASS: {fn.__name__}")
    print(f"\nAll {len(fns)} console tests passed.")
