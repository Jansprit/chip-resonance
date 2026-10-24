"""
test_suite_integrity.py — 測試套件本身的完整性守門

**這支測試在防止什麼？**
本專案曾經有 18 個測試檔，每個檔案的 `__main__` 都手寫一份
「要跑哪些測試」清單。於是新增一個測試函式、卻忘了加進清單時，
那個測試**永遠不會執行**，而且沒有任何錯誤 ——
CI 一片綠燈，但新測試根本沒跑。

症狀是「測試有寫」，實際是「測試沒跑」——
這是「見樹不見林」最典型的形態：綠燈本身就是症狀。

這支 meta 測試守住兩條規則：
1. 每個 test_*.py 都必須用共用 runner（自動發現），不得手寫清單。
2. runner 實際執行的測試數，必須等於 AST 分析出的 test_ 函式數。
"""
from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.tests import _runner

REPO = Path(__file__).resolve().parents[2]
TESTS_DIR = REPO / "backend" / "tests"
SELF = Path(__file__).resolve()


def _test_files(include_self: bool = False) -> list[Path]:
    """
    找出所有測試檔。

    預設**排除自己** —— 否則這支 meta 測試會把自己再 spawn 出去，
    形成無限遞迴（實測會開出幾十個 python 行程）。
    自己改用行程內檢查（見 test_meta_test_runs_all_its_own_functions）。
    """
    files = sorted(TESTS_DIR.glob("test_*.py"))
    if not include_self:
        files = [f for f in files if f.resolve() != SELF]
    return files


def _ast_test_functions(path: Path) -> list[str]:
    """用 AST 找出模組層級的 test_ 函式（排除巢狀定義與方法）。"""
    # utf-8-sig：萬一檔案帶 BOM 也不能讓這支 meta 測試整個爆掉
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    names = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("test_"):
                names.append(node.name)
    return names


def _fake_fn(name: str, module: str = "fake_mod"):
    """做出一個「看起來屬於 module」的函式（runner 會比對 __module__）。"""
    def _fn():
        return None
    _fn.__name__ = name
    _fn.__module__ = module
    return _fn


# ============ 規則 1：不得手寫測試清單 ============

def test_every_test_file_uses_shared_runner():
    """每個測試檔的 __main__ 都必須呼叫共用 runner。"""
    offenders = []
    for path in _test_files():
        text = path.read_text(encoding="utf-8")
        if "run_tests(globals()" not in text:
            offenders.append(path.name)
    assert not offenders, (
        f"這幾個檔案沒有用共用 runner（新增測試會被靜默遺漏）：{offenders}"
    )


def test_no_test_file_calls_test_functions_directly_at_module_level():
    """模組層級不得出現 test_xxx() 的直接呼叫（那就是手寫清單）。"""
    offenders = []
    for path in _test_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
                func = node.value.func
                name = getattr(func, "id", None) or getattr(func, "attr", None)
                if name and name.startswith("test_"):
                    offenders.append(f"{path.name}:{node.lineno} {name}()")
    assert not offenders, f"發現手寫的測試呼叫清單：{offenders}"


# ============ 規則 2：runner 不得漏掉任何測試 ============

def test_runner_discovers_all_module_level_test_functions():
    """共用 runner 必須找出模組裡的全部 test_ 函式。"""
    found = _runner.discover({
        "__name__": "fake_mod",
        "test_a": _fake_fn("test_a"),
        "test_b": _fake_fn("test_b"),
        "helper": _fake_fn("helper"),
    })
    assert [n for n, _ in found] == ["test_a", "test_b"]


def test_runner_ignores_imported_functions():
    """從別處 import 進來的函式不可被當成本模組的測試。"""
    found = _runner.discover({
        "__name__": "fake_mod",
        "test_real": _fake_fn("test_real"),
        "test_imported": _fake_fn("test_imported", module="other_mod"),
    })
    names = [n for n, _ in found]
    assert names == ["test_real"], f"import 進來的函式不該被算成本模組的測試：{names}"


def test_runner_ignores_non_functions():
    """非函式（常數、模組）不可被算成測試。"""
    found = _runner.discover({
        "__name__": "fake_mod",
        "test_data": [1, 2, 3],
        "test_mod": sys,
        "test_real": _fake_fn("test_real"),
    })
    assert [n for n, _ in found] == ["test_real"]


def test_runner_executes_every_discovered_test():
    """run_tests 必須真的把每個測試都跑掉。"""
    calls = []

    def _t1():
        calls.append("t1")

    def _t2():
        calls.append("t2")

    _t1.__module__ = "fake_mod"
    _t2.__module__ = "fake_mod"
    count = _runner.run_tests({
        "__name__": "fake_mod",
        "test_t1": _t1,
        "test_t2": _t2,
    })
    assert count == 2
    assert sorted(calls) == ["t1", "t2"]


# ============ 規則 3：每個測試檔實際執行的數量必須吻合 ============

def test_each_test_file_runs_all_its_test_functions():
    """
    實際執行每個測試檔，比對「執行的數量」與「AST 分析出的數量」。

    這是最後一道防線：即使有人手動改了 runner 或加了 weird 的 __main__，
    數量對不上就會被抓到。
    """
    mismatches = []
    for path in _test_files():
        expected = len(_ast_test_functions(path))
        env = dict(os.environ)
        # 讓子行程一律用 UTF-8 輸出，否則 Windows 的 cp950 會讓解碼失敗
        env["PYTHONIOENCODING"] = "utf-8"
        proc = subprocess.run(
            [sys.executable, str(path)],
            cwd=str(REPO),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=600,
        )
        executed = None
        for line in proc.stdout.splitlines():
            if line.startswith("TESTS_EXECUTED:"):
                executed = int(line.split(":", 1)[1].strip())
        if proc.returncode != 0:
            mismatches.append(f"{path.name}: 執行失敗（returncode={proc.returncode}）")
            continue
        if executed is None:
            mismatches.append(f"{path.name}: 輸出沒有 TESTS_EXECUTED 標記")
            continue
        if executed != expected:
            mismatches.append(
                f"{path.name}: 定義 {expected} 個測試，實際只跑了 {executed} 個"
            )
        if expected == 0:
            mismatches.append(
                f"{path.name}: 沒有任何 test_ 函式（這個檔的測試根本沒在跑）"
            )
    assert not mismatches, "測試執行數量不一致：\n" + "\n".join(mismatches)


def test_no_test_file_defines_a_bare_main_without_tests():
    """
    舊式的 `def main(): ... check(...)` 結構必須被淘汰。

    實測踩過這個坑：test_scoring_provenance.py 原本是這種寫法，
    轉成共用 runner 後因為沒有任何 `test_` 開頭的函式，
    整個檔案變成「0 個測試、exit code 0」——CI 一片綠燈，
    但那 33 項檢查一個都沒跑。
    """
    offenders = []
    for path in _test_files(include_self=True):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        has_main = any(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "main"
            for node in tree.body
        )
        if not has_main:
            continue
        # 有 main() 就必須同時有 test_ 函式，且 main 不可是唯一入口
        has_tests = any(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name.startswith("test_")
            for node in tree.body
        )
        if not has_tests:
            offenders.append(path.name)
    assert not offenders, (
        f"這幾個檔案只有 main()、沒有 test_ 函式（測試不會被執行）：{offenders}"
    )


def test_meta_test_runs_all_its_own_functions():
    """
    這支 meta 測試自己也必須跑滿自己的測試（行程內檢查）。

    不用 subprocess 是為了避免自我遞迴。
    """
    expected = len(_ast_test_functions(SELF))
    found = _runner.discover(dict(globals()))
    assert len(found) == expected, (
        f"meta 測試自己定義了 {expected} 個測試，runner 只找到 {len(found)} 個"
    )


def test_at_least_one_test_file_exists():
    """避免這個 meta 測試因為路徑錯誤而「什麼都沒檢查」還是一片綠燈。"""
    files = _test_files(include_self=True)
    assert len(files) >= 10, f"只找到 {len(files)} 個測試檔，路徑可能不對"


def test_meta_test_excludes_itself_from_subprocess_scan():
    """自我遞迴是最容易踩到的地雷 —— 明確守住這條。"""
    assert SELF not in _test_files()
    assert SELF in _test_files(include_self=True)


if __name__ == "__main__":
    import sys as _sys
    from pathlib import Path as _Path

    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
    from backend.tests._runner import run_tests

    run_tests(globals(), "suite_integrity")
