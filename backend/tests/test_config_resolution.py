"""
test_config_resolution.py — Tests for unified configuration resolution

對應 docs/2026-10-21-專案體檢報告.md BUG-13（死設定）

驗證：
- env_get() 讀取順序：程序環境變數 → backend/.env → 預設值
- pipeline_limit() 真的會吃 .env 裡的 PIPELINE_LIMIT（舊版只讀 os.environ）
- pipeline_limit() 的邊界與錯誤處理
- session_available() 回報真實的登入 session 狀態（存在且未過期）
- CredentialManager.summary() 不再回報「讀得到卻不影響行為」的死憑證
- .env.example 不再列出死設定鍵

執行：python backend/tests/test_config_resolution.py
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.scrapers import base as base_mod
from backend.scrapers.base import (
    CredentialManager,
    env_get,
    reset_config_cache,
    session_available,
    session_is_expired,
)

TAIPEI_TZ = timezone(timedelta(hours=8))
REPO_ROOT = Path(__file__).resolve().parents[2]


def _isolate_env(tmp_path: Path, env_text: str) -> None:
    """把 CredentialManager 指向暫存的 .env，並清掉設定快取。"""
    env_file = tmp_path / ".env"
    env_file.write_text(env_text, encoding="utf-8")
    os.environ["CHIP_RESONANCE_ENV"] = str(env_file)
    reset_config_cache()


def _cleanup_env() -> None:
    os.environ.pop("CHIP_RESONANCE_ENV", None)
    os.environ.pop("PIPELINE_LIMIT", None)
    os.environ.pop("RL_JITTER", None)
    reset_config_cache()


# ============ env_get 讀取順序 ============

def test_env_get_prefers_process_environment_over_env_file():
    """程序環境變數優先於 .env 檔案。"""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        _isolate_env(tmp, "PIPELINE_LIMIT=3\n")
        os.environ["PIPELINE_LIMIT"] = "7"
        try:
            assert env_get("PIPELINE_LIMIT") == "7"
        finally:
            _cleanup_env()


def test_env_get_falls_back_to_env_file():
    """程序環境變數沒有時，要能從 .env 檔案讀到（BUG-13 原本會漏掉）。"""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        _isolate_env(tmp, "PIPELINE_LIMIT=3\nRL_JITTER=1.25\n")
        try:
            assert env_get("PIPELINE_LIMIT") == "3"
            assert env_get("RL_JITTER") == "1.25"
        finally:
            _cleanup_env()


def test_env_get_returns_default_when_absent():
    """兩邊都沒有時回傳 default。"""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        _isolate_env(tmp, "")
        try:
            assert env_get("NOT_A_REAL_KEY", "fallback") == "fallback"
            assert env_get("NOT_A_REAL_KEY") is None
        finally:
            _cleanup_env()


# ============ pipeline_limit ============

def test_pipeline_limit_reads_env_file():
    """PIPELINE_LIMIT 寫在 .env 也要生效（這是 BUG-13 的核心）。"""
    from backend.pipeline import pipeline_limit

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        _isolate_env(tmp, "PIPELINE_LIMIT=3\n")
        try:
            assert pipeline_limit(default=50) == 3
        finally:
            _cleanup_env()


def test_pipeline_limit_process_env_overrides_env_file():
    from backend.pipeline import pipeline_limit

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        _isolate_env(tmp, "PIPELINE_LIMIT=3\n")
        os.environ["PIPELINE_LIMIT"] = "9"
        try:
            assert pipeline_limit(default=50) == 9
        finally:
            _cleanup_env()


def test_pipeline_limit_falls_back_to_default():
    from backend.pipeline import pipeline_limit

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        _isolate_env(tmp, "")
        try:
            assert pipeline_limit(default=50) == 50
            assert pipeline_limit(default=5) == 5
        finally:
            _cleanup_env()


def test_pipeline_limit_zero_means_unlimited():
    """0 代表不限制；負數也應視為不限制而非爆量。"""
    from backend.pipeline import pipeline_limit

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        _isolate_env(tmp, "PIPELINE_LIMIT=0\n")
        try:
            assert pipeline_limit(default=50) == 0
        finally:
            _cleanup_env()
            _isolate_env(tmp, "PIPELINE_LIMIT=-5\n")
            try:
                assert pipeline_limit(default=50) == 0
            finally:
                _cleanup_env()


def test_pipeline_limit_invalid_value_uses_default():
    """非整數不應該讓 pipeline 崩掉，應退回預設。"""
    from backend.pipeline import pipeline_limit

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        _isolate_env(tmp, "PIPELINE_LIMIT=abc\n")
        try:
            assert pipeline_limit(default=50) == 50
        finally:
            _cleanup_env()


# ============ session 真實狀態 ============

def test_session_available_false_when_missing():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        os.environ["CHIP_RESONANCE_SESSION_DIR"] = str(tmp / "sessions")
        try:
            assert session_available("pyramid") is False
        finally:
            os.environ.pop("CHIP_RESONANCE_SESSION_DIR", None)


def test_session_available_true_for_valid_session():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        sdir = tmp / "sessions"
        sdir.mkdir()
        expires = (datetime.now(TAIPEI_TZ) + timedelta(days=7)).isoformat()
        (sdir / "pyramid.json").write_text(
            json.dumps({"cookies": [], "_meta": {"expires_at": expires}}),
            encoding="utf-8",
        )
        os.environ["CHIP_RESONANCE_SESSION_DIR"] = str(sdir)
        try:
            assert session_available("pyramid") is True
        finally:
            os.environ.pop("CHIP_RESONANCE_SESSION_DIR", None)


def test_session_available_false_for_expired_session():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        sdir = tmp / "sessions"
        sdir.mkdir()
        expires = (datetime.now(TAIPEI_TZ) - timedelta(days=1)).isoformat()
        (sdir / "pyramid.json").write_text(
            json.dumps({"cookies": [], "_meta": {"expires_at": expires}}),
            encoding="utf-8",
        )
        os.environ["CHIP_RESONANCE_SESSION_DIR"] = str(sdir)
        try:
            assert session_available("pyramid") is False
        finally:
            os.environ.pop("CHIP_RESONANCE_SESSION_DIR", None)


def test_session_available_false_for_corrupt_file():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        sdir = tmp / "sessions"
        sdir.mkdir()
        (sdir / "pyramid.json").write_text("{not json", encoding="utf-8")
        os.environ["CHIP_RESONANCE_SESSION_DIR"] = str(sdir)
        try:
            assert session_available("pyramid") is False
        finally:
            os.environ.pop("CHIP_RESONANCE_SESSION_DIR", None)


def test_session_is_expired_without_meta():
    """沒有 expires_at 欄位時視為未過期（不誤判）。"""
    assert session_is_expired({}) is False
    assert session_is_expired({"_meta": {}}) is False
    assert session_is_expired({"_meta": {"expires_at": "not-a-date"}}) is False


# ============ summary() 不再回報死憑證 ============

def test_summary_has_no_dead_credential_keys():
    """summary() 不應再出現讀得到卻不影響行為的死設定。"""
    cred = CredentialManager()
    summary = cred.summary()
    for dead in (
        "pyramid_credentials",
        "goodinfo_credentials",
    ):
        assert dead not in summary, f"{dead} 是死設定，應已移除"
    assert "pyramid_session" in summary
    assert "goodinfo_session" in summary
    assert "tdcc_session" in summary


def test_summary_session_flags_are_bool():
    cred = CredentialManager()
    summary = cred.summary()
    for key in ("pyramid_session", "goodinfo_session", "tdcc_session"):
        assert isinstance(summary[key], bool)


# ============ .env.example 與 pyproject 不再列死設定 ============

def test_env_example_has_no_dead_keys():
    """.env.example 不得再列出從未被讀取的設定鍵。

    只檢查「真正的設定行」（KEY=...），註解裡提到這些鍵是允許的
    （我們刻意在註解說明它們為什麼被移除）。
    """
    text = (REPO_ROOT / "backend" / ".env.example").read_text(encoding="utf-8")
    assigned = set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key = line.split("=", 1)[0].strip()
        if key:
            assigned.add(key)

    for dead in (
        "PYRAMID_USERNAME",
        "PYRAMID_PASSWORD",
        "GOODINFO_USERNAME",
        "GOODINFO_PASSWORD",
    ):
        assert dead not in assigned, f".env.example 仍列著死設定 {dead}"

    assert "PIPELINE_LIMIT" in assigned, "PIPELINE_LIMIT 應該保留（現在真的生效）"
    assert "GOODINFO_PROXY_URL" in assigned, "GOODINFO_PROXY_URL 是真的有在用的"


def test_pyproject_has_no_dead_optional_env():
    """pyproject.toml 的 optional_env 清單不得再列死設定。"""
    text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    start = text.index("optional_env = [")
    end = text.index("]", start)
    block = text[start:end]
    listed = set(re.findall(r'"([A-Z_][A-Z0-9_]*)"', block))

    for dead in (
        "PYRAMID_USERNAME",
        "PYRAMID_PASSWORD",
        "GOODINFO_USERNAME",
        "GOODINFO_PASSWORD",
    ):
        assert dead not in listed, f"pyproject.toml optional_env 仍列著死設定 {dead}"

    assert "PIPELINE_LIMIT" in listed
    assert "RL_JITTER" in listed

if __name__ == "__main__":
    # 自動發現所有 test_ 函式 —— 新增測試不可能再被靜默遺漏。
    # 見 backend/tests/_runner.py 的說明。
    import sys as _sys
    from pathlib import Path as _Path

    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
    from backend.tests._runner import run_tests

    run_tests(globals(), "config_resolution")
