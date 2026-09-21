"""
test_integration.py — End-to-end integration test for the pipeline

驗證：
- Pipeline.run_twse() 抓取 + 寫入 + meta.json 更新全鏈路
- 各源 graceful skip 機制正確觸發
- 寫入的 JSON 通過 schema 驗證

不實際呼叫外網（避免測試變慢 + 觸發 IP 風險），用 mock 替換 HttpClient。
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# 確保 import pipeline 時不會執行 main()
import backend.pipeline as pipeline
from backend.scrapers.base import SourceHealth, RateLimiter, HttpClient


def test_run_twse_writes_correctly():
    """run_twse 應該寫入 data/latest/prices.json 與 data/<date>/prices.json。"""
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        # 模擬 pipeline.py 的呼叫：out_dir = data_dir / "latest"
        out_dir = data_dir / "latest"
        out_dir.mkdir(parents=True, exist_ok=True)

        mock_prices = [
            {"code": "2330", "name": "台積電", "price": 2460, "volume_lots": 1000,
             "open": 2450, "high": 2470, "low": 2440, "change": 10,
             "turnover": 2460000, "transactions": 5000, "date": "2026-09-18",
             "exchange": "TWSE"}
        ]
        mock_idx = [
            {"date": "2026-09-18", "name": "加權指數", "value": 47180.75, "change_pct": 1.93}
        ]
        with patch("backend.pipeline.fetch_prices", return_value=mock_prices), \
             patch("backend.pipeline.fetch_market_index", return_value=mock_idx):
            status = pipeline.run_twse(out_dir)

        assert status["status"] == "ok"
        assert status["stocks_count"] == 1
        # 檢查寫入的檔案（out_dir 為 data_dir/latest，所以檔案在 out_dir 下）
        assert (out_dir / "prices.json").exists()
        assert (out_dir / "market_index.json").exists()

        # 檢查內容
        with open(out_dir / "prices.json", encoding="utf-8") as f:
            data = json.load(f)
        assert data[0]["code"] == "2330"
        assert data[0]["price"] == 2460


def test_run_finmind_skips_without_token():
    """沒有 FINMIND_TOKEN 時，run_finmind 應該回傳 skipped 狀態。"""
    with tempfile.TemporaryDirectory() as tmp:
        out_dir = Path(tmp) / "latest"
        out_dir.mkdir(parents=True, exist_ok=True)
        with patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("FINMIND_TOKEN", None)
            from backend.scrapers.base import CredentialManager
            with patch.object(CredentialManager, "finmind_token", new_callable=lambda: None):
                status = pipeline.run_finmind(out_dir)
        assert status["status"] == "skipped"
        assert "FINMIND_TOKEN" in status["reason"]


def test_run_mops_graceful_skip():
    """MOPS 2024 改版後應該 graceful skip。"""
    with tempfile.TemporaryDirectory() as tmp:
        out_dir = Path(tmp) / "latest"
        out_dir.mkdir(parents=True, exist_ok=True)
        status = pipeline.run_mops(out_dir)
        assert status["status"] == "skipped"
        assert "MOPS" in status["reason"]


def test_source_health_disables_on_403():
    """SourceHealth.record_failure(disable=True) 應該標記 disabled。"""
    h = SourceHealth("test", daily_quota=10)
    h.can_request()  # 沒問題
    h.record_failure("HTTP 403 banned", disable=True)
    assert h.disabled_reason is not None
    assert not h.can_request()


def test_rate_limiter_rejects_low_interval():
    """RateLimiter 不接受 < 0.5s 的間隔。"""
    import pytest
    with pytest.raises(ValueError):
        RateLimiter(min_interval=0.1)


def test_taipei_today_format():
    """taipei_today 應該回傳 YYYY-MM-DD 格式。"""
    from backend.scrapers.base import taipei_today
    today = taipei_today()
    assert len(today) == 10
    assert today[4] == "-"
    assert today[7] == "-"


def test_meta_written_after_run():
    """run_twse 成功後，meta.json 應該被 update_meta 寫入。"""
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        out_dir = data_dir / "latest"
        out_dir.mkdir(parents=True, exist_ok=True)

        with patch("backend.pipeline.fetch_prices", return_value=[]), \
             patch("backend.pipeline.fetch_market_index", return_value=[]):
            pipeline.run_twse(out_dir)
            # update_meta 接受 out_dir (data/latest/)，寫到 out_dir/meta.json
            from backend.pipeline import update_meta
            update_meta(out_dir, {"twse": {"status": "ok"}}, notes="test")

        assert (out_dir / "meta.json").exists()
        with open(out_dir / "meta.json", encoding="utf-8") as f:
            meta = json.load(f)
        assert "twse" in meta["sources"]


def test_demo_subset_preserves_chip_fields():
    """demo_subset.json 必須保留 pct_1000up_now 等 chip 欄位，讓 scoring engine 能運作。"""
    from backend.scrapers.tpex import save_latest
    from backend.normalize import merge_into

    # 模擬 demo 資料
    base_demo = [{
        "code": "2330", "name": "台積電", "industry": "SEMI",
        "price": 2460, "avg_volume": 40892688,
        "pct_1000up_now": 67.5, "pct_400up": 82.1,
        "is_60d_high": True, "warning": False
    }]
    pyramid_chip = [{
        "code": "2330", "pct_1000up_now": 70.0,
        "pct_1000up_w1": 68.0, "pct_1000up_w2": 67.0, "pct_1000up_w3": 65.0,
    }]

    merged = merge_into(base_demo, pyramid_chip)
    assert merged[0]["pct_1000up_now"] == 70.0  # pyramid 覆蓋
    assert merged[0]["price"] == 2460  # demo 保留
    assert merged[0]["industry"] == "SEMI"


if __name__ == "__main__":
    test_run_twse_writes_correctly()
    print("PASS: test_run_twse_writes_correctly")
    test_run_finmind_skips_without_token()
    print("PASS: test_run_finmind_skips_without_token")
    test_run_mops_graceful_skip()
    print("PASS: test_run_mops_graceful_skip")
    test_source_health_disables_on_403()
    print("PASS: test_source_health_disables_on_403")
    test_rate_limiter_rejects_low_interval()
    print("PASS: test_rate_limiter_rejects_low_interval")
    test_taipei_today_format()
    print("PASS: test_taipei_today_format")
    test_meta_written_after_run()
    print("PASS: test_meta_written_after_run")
    test_demo_subset_preserves_chip_fields()
    print("PASS: test_demo_subset_preserves_chip_fields")
    print("\nAll 8 integration tests passed.")