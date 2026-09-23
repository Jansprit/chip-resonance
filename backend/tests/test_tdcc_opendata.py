"""
test_tdcc_opendata.py — Tests for TDCC Government Open Data platform scraper

驗證：
- 民國年日期轉 ISO 正確
- 17 級中正確跳過合計行（tier 17）
- 特別股（tier 16）也應跳過（避免重複加總）
- 4 個關鍵大戶分級（400/600/800/1000 張）計算正確
- 多週歷史讀寫與趨勢計算
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.scrapers.tdcc_opendata import (
    _roc_date_to_iso,
    aggregate_to_pct_400_1000,
    parse_holder_distribution_csv,
    parse_holder_csv_to_pct_per_stock,
    save_history,
    load_history,
    compute_multi_week_trend,
)


def test_roc_date_to_iso():
    """TDCC 用 7 碼民國年（例 20260918 = 民國 115.09.18 = 2026-09-18）。"""
    assert _roc_date_to_iso("20260918") == "2026-09-18"
    assert _roc_date_to_iso("1141231") == "2025-12-31"
    assert _roc_date_to_iso("") == ""


def test_aggregate_skips_tier_16_and_17():
    """Tiers 16, 17 是合計/特別股，不該加總。"""
    rows = [
        # 2330 真實資料
        {"date": "2026-09-18", "code": "2330", "tier": 1,  "people": 100, "shares": 1000,  "pct": 0.5},
        {"date": "2026-09-18", "code": "2330", "tier": 12, "people": 100, "shares": 5000,  "pct": 1.0},
        {"date": "2026-09-18", "code": "2330", "tier": 13, "people": 50,  "shares": 10000, "pct": 2.0},
        {"date": "2026-09-18", "code": "2330", "tier": 14, "people": 20,  "shares": 5000,  "pct": 1.0},
        {"date": "2026-09-18", "code": "2330", "tier": 15, "people": 10,  "shares": 100000, "pct": 50.0},
        # 合計行（pct=100.0）應跳過
        {"date": "2026-09-18", "code": "2330", "tier": 17, "people": 99999, "shares": 99999999, "pct": 100.0},
        # 特別股（tier 16）應跳過
        {"date": "2026-09-18", "code": "2330", "tier": 16, "people": 1, "shares": 1000, "pct": 0.0},
    ]
    result = aggregate_to_pct_400_1000(rows, "2330")

    # 應只加總 tiers 12-15
    # 400up: 1.0 + 2.0 + 1.0 + 50.0 = 54.0
    # 600up: 2.0 + 1.0 + 50.0 = 53.0
    # 800up: 1.0 + 50.0 = 51.0
    # 1000up: 50.0
    assert result["pct_400up_now"] == 54.0
    assert result["pct_600up_now"] == 53.0
    assert result["pct_800up_now"] == 51.0
    assert result["pct_1000up_now"] == 50.0
    # 跳過 17 後總和不超過 100%
    assert result["pct_400up_now"] < 100.0


def test_parse_csv_handles_bom_and_header():
    """CSV 開頭可能有 BOM。"""
    csv_text = (
        "\ufeff資料日期,證券代號,持股分級,人數,股數,占集保庫存數比例%\n"
        "20260918,000218,1,100,5000,0.10\n"
        "20260918,000218,2,50,20000,0.40\n"
        "20260918,000218,12,5,500000,10.0\n"
        "20260918,000218,15,1,5000000,90.0\n"
        "20260918,000218,17,999,9999999,100.0\n"  # 合計
    )
    rows = parse_holder_distribution_csv(csv_text)
    # 跳過 17 後剩 4 筆
    assert len(rows) == 4
    assert all(r["code"] == "000218" for r in rows)
    assert rows[0]["pct"] == 0.10
    assert rows[-1]["pct"] == 90.0
    # 應能正確彙總
    agg = aggregate_to_pct_400_1000(rows, "000218")
    assert agg["pct_400up_now"] == 10.0 + 90.0   # 100.0
    assert agg["pct_1000up_now"] == 90.0


def test_parse_to_pct_per_stock():
    csv_text = (
        "資料日期,證券代號,持股分級,人數,股數,占集保庫存數比例%\n"
        "20260918,2330,15,1000,10000000,80.0\n"
        "20260918,2330,17,9999,99999999,100.0\n"
        "20260918,2454,15,500,5000000,60.0\n"
        "20260918,2454,17,999,9999999,100.0\n"
    )
    by_code = parse_holder_csv_to_pct_per_stock(csv_text)
    assert "2330" in by_code
    assert "2454" in by_code
    assert by_code["2330"]["pct_1000up_now"] == 80.0
    assert by_code["2454"]["pct_1000up_now"] == 60.0


def test_history_save_load_and_trend():
    """多週歷史：儲存、載入、計算趨勢。"""
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)

        # 第 1 週
        rows_w0 = [
            {"date": "2026-09-18", "code": "2330", "pct_1000up_now": 85.0,
             "pct_400up_now": 88.0, "pct_600up_now": 87.0, "pct_800up_now": 86.0,
             "people_400up_now": 1000, "people_1000up_now": 500},
        ]
        save_history(rows_w0, data_dir, iso_date="2026-09-18")

        # 第 2 週
        rows_w1 = [
            {"date": "2026-09-11", "code": "2330", "pct_1000up_now": 84.0,
             "pct_400up_now": 87.0, "pct_600up_now": 86.0, "pct_800up_now": 85.0,
             "people_400up_now": 990, "people_1000up_now": 490},
        ]
        save_history(rows_w1, data_dir, iso_date="2026-09-11")

        # 第 3 週
        rows_w2 = [
            {"date": "2026-09-04", "code": "2330", "pct_1000up_now": 83.0,
             "pct_400up_now": 86.0, "pct_600up_now": 85.0, "pct_800up_now": 84.0,
             "people_400up_now": 980, "people_1000up_now": 480},
        ]
        save_history(rows_w2, data_dir, iso_date="2026-09-04")

        # 載入
        history = load_history(data_dir, weeks=4)
        assert "2026-09-18" in history
        assert "2026-09-11" in history
        assert "2026-09-04" in history

        # 計算趨勢：w3=83.0, w2=84.0, w1=85.0, w0=86.0 → 上升
        trend = compute_multi_week_trend(history, "2330")
        assert trend["pct_1000up_w0"] == 85.0
        assert trend["pct_1000up_w1"] == 84.0
        assert trend["pct_1000up_w2"] == 83.0
        assert trend["pct_1000up_w3"] is None  # 沒有第 4 週
        assert trend["pct_1000up_trend"] == "="  # 沒有完整 4 週


def test_history_w0_minus_w3_trend_up():
    """有完整 4 週歷史時，趨勢計算正確。"""
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)

        for week, val in [("2026-09-18", 86.0), ("2026-09-11", 85.5),
                          ("2026-09-04", 85.0), ("2026-08-28", 84.5)]:
            save_history([
                {"date": week, "code": "2330", "pct_1000up_now": val,
                 "pct_400up_now": 88.0, "pct_600up_now": 87.0, "pct_800up_now": 86.0,
                 "people_400up_now": 1000, "people_1000up_now": 500}
            ], data_dir, iso_date=week)

        history = load_history(data_dir, weeks=4)
        trend = compute_multi_week_trend(history, "2330")
        # w3 (oldest) = 84.5, w0 (newest) = 86.0 → diff +1.5 → "+"
        assert trend["pct_1000up_w3"] == 84.5
        assert trend["pct_1000up_w0"] == 86.0
        assert trend["pct_1000up_trend"] == "+"


if __name__ == "__main__":
    test_roc_date_to_iso()
    print("PASS: test_roc_date_to_iso")
    test_aggregate_skips_tier_16_and_17()
    print("PASS: test_aggregate_skips_tier_16_and_17")
    test_parse_csv_handles_bom_and_header()
    print("PASS: test_parse_csv_handles_bom_and_header")
    test_parse_to_pct_per_stock()
    print("PASS: test_parse_to_pct_per_stock")
    test_history_save_load_and_trend()
    print("PASS: test_history_save_load_and_trend")
    test_history_w0_minus_w3_trend_up()
    print("PASS: test_history_w0_minus_w3_trend_up")
    print("\nAll 6 tdcc_opendata tests passed.")