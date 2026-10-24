"""
backend/console.py — 主控台輸出編碼處理（Windows 相容）

Windows 繁中預設主控台是 cp950（Big5），無法編碼 ⚠ ✅ → ★ 等符號。
Python 會在 print() 時直接丟 UnicodeEncodeError，讓整個流程中斷。

對 Windows Task Scheduler 這種「沒有人盯著」的排程來說，
最糟的情況不是「報錯」，而是「看起來有跑，實際上每次都掛在第一行」——
而且因為工作排程器只記錄 exit code，這種失敗會被完全忽略。

這裡把 stdout/stderr 調成 UTF-8（errors='replace' 兜底），
讓符號能正確顯示；就算真的編碼不了，也只會退化成 '?'，不會讓流程爆掉。

⚠️ 注意：這只影響「印到螢幕」的文字。
寫檔案的地方一律明確指定 encoding="utf-8"，不受影響。
"""
from __future__ import annotations

import sys


def configure_console() -> str:
    """
    設定 stdout / stderr 的編碼。回傳實際套用的編碼名稱（供測試與記錄）。

    優先嘗試 UTF-8（符號能正確顯示）；
    若平台不支援（例如某些 CI 的啞管），退回 errors='replace'，
    確保「編碼失敗」永遠不會讓排程流程中斷。
    """
    applied = ""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
            applied = "utf-8"
        except (ValueError, OSError, LookupError):
            try:
                reconfigure(errors="replace")
                applied = applied or "replace"
            except (ValueError, OSError):
                pass
    return applied
