"""
backend/tests/_runner.py — 共用測試執行器（自動發現 test_ 函式）

**為什麼需要這個檔案？**
本專案曾經有 18 個測試檔，每個檔案的 `__main__` 都手寫一份
「要跑哪些測試」清單。於是新增一個測試函式、卻忘了加進清單時，
那個測試**永遠不會執行**，而且沒有任何錯誤 —— CI 一片綠燈，
但新測試根本沒跑。

這是典型的「見樹不見林」：症狀是「測試有寫」，實際是「測試沒跑」。

這裡改成**自動發現**：只要函式名稱以 `test_` 開頭就一定會被執行。
再配合 `test_suite_integrity.py` 守住這條規則，
新增測試不可能再被靜默遺漏。
"""
from __future__ import annotations

import inspect
from typing import Any, Callable


def discover(module_globals: dict[str, Any]) -> list[tuple[str, Callable[[], Any]]]:
    """
    找出模組內所有可執行的測試函式（名稱以 `test_` 開頭）。

    排除：
    - 非函式（import 進來的模組、資料常數）
    - 巢狀於其他函式內的函式（只取模組層級）
    - 名稱以 `test_` 開頭但其實是 helper 的情況由呼叫端自行取捨
    """
    found: list[tuple[str, Callable[[], Any]]] = []
    for name, obj in sorted(module_globals.items()):
        if not name.startswith("test_"):
            continue
        if not inspect.isfunction(obj):
            continue
        # 只取模組層級定義的函式（__module__ 指向同一個模組）
        if getattr(obj, "__module__", None) != module_globals.get("__name__"):
            continue
        found.append((name, obj))
    return found


def run_tests(module_globals: dict[str, Any], label: str = "") -> int:
    """
    執行模組內所有測試函式，回傳測試數量。

    會印出一行 `TESTS_EXECUTED: N` —— 供完整性檢查解析比對。
    """
    fns = discover(module_globals)
    for name, fn in fns:
        fn()
        print(f"PASS: {name}")
    print(f"TESTS_EXECUTED: {len(fns)}")
    suffix = f" {label}" if label else ""
    print(f"\nAll {len(fns)}{suffix} tests passed.")
    return len(fns)
