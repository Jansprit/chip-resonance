"""
scrapers/tdcc_opendata.py — 集保結算所 政府資料開放平台 抓取器

資料源：https://opendata.tdcc.com.tw/getOD.ashx?id=<ID>
- 這是 TDCC 在政府資料開放平台（data.gov.tw）上的官方釋出
- **完全免費、無需 API Key、無 rate limit**

可用資料集：
- id=1-2 — 上市公司資料清單（12.8 MB CSV）
- id=1-5 — 集保戶股權分散表（**2.3 MB CSV** — F1/F4/F6/F8 主要來源）
- id=2-1 — 集保戶開戶數統計（散戶開/銷戶）
- id=2-2 — 集保戶款項收付統計
- id=A — 無資料

更新頻率：每週五盤後 22:00 後可下載當週資料
- 2026-09-18（週五）資料 → 2026-09-19（週六）可下載
- 「資料日期」欄位用 ROC 民國年

對應因子：
- F1 大股東連續加碼 → pct_1000up_now（最新一週）
- F4 集中度突破 → pct_400up_52w_high
- F6 散戶退場主力接手 → id=2-1（集保開戶數趨勢）
- F8 回調籌碼守穩 → pct_400up_now（最近 4 週）
- F10 利空籌碼修復 → 需配合神秘金字塔的 pct_1000up_trend

節流：無（公開下載），建議搭配 ETag/Last-Modified 檢查避免重複下載。
"""

from __future__ import annotations

import csv
import io
import json
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from .base import (
    RateLimiter,
    SourceHealth,
    RetryPolicy,
    HttpClient,
    CredentialManager,
    write_json,
    taipei_today,
)


TDCC_OPENDATA_BASE = "https://opendata.tdcc.com.tw/getOD.ashx"

# 資料集 ID 常數
DATASET_ISSUER_LIST = "1-2"        # 上市公司資料清單
DATASET_HOLDER_DIST = "1-5"        # 集保戶股權分散表
DATASET_ACCOUNT_STAT = "2-1"       # 集保戶開戶數統計

# 持股分級（依集保公告標準）
# 1: 1-999 股
# 2: 1,000-5,000
# 3: 5,001-10,000
# ...
# 15: 400,001 股以上
# 15 級 = 400 張以上
# 16 級 = 1,000 張以上（自定義）
# 對應因子：
# - pct_400up = level 15 累計
# - pct_1000up = 自定義 (>= 1,000,000 股) 累計

# 集保標準 15 級（股數範圍）
TIER_RANGES = [
    (1, 999),            # 1
    (1000, 5000),        # 2
    (5001, 10000),       # 3
    (10001, 15000),      # 4
    (15001, 20000),      # 5
    (20001, 30000),      # 6
    (30001, 40000),      # 7
    (40001, 50000),      # 8
    (50001, 100000),     # 9
    (100001, 200000),    # 10
    (200001, 400000),    # 11
    (400001, 600000),    # 12
    (600001, 800000),    # 13
    (800001, 1000000),   # 14
    (1000001, None),     # 15
]

# 對應到 9 因子的關鍵分級
TIER_400UP = 15         # >= 400,001 股 = 400 張以上
TIER_1000UP = 15        # 1000 張 = 1,000,000 股以上（F1 計算需要從分級 15 累計，或外部來源）

# 注意：TDCC 標準分級只到 100 萬股（1000 張剛好是 15 級下界）
# 真正的「1000 張以上」需要自定義分級：
#   - 神秘金字塔與 FinMind 在 15 級之上還有 16 級（100 萬以上）
#   - TDCC 開放資料不提供 16 級（除非自費下載集保原始檔案）


def create_tdcc_opendata_client(cred: CredentialManager | None = None) -> HttpClient:
    """TDCC 政府資料開放平台 — 完全免費，無需 token。"""
    rl = RateLimiter(min_interval=1.0, source_name="tdcc_opendata")  # 公開下載，1s 即可
    health = SourceHealth(source_name="tdcc_opendata", daily_quota=100)
    return HttpClient(rate_limiter=rl, health=health, retry=RetryPolicy())


def is_available() -> bool:
    """TDCC 政府資料開放平台永遠可用（無認證需求）。"""
    return True


def fetch_holder_distribution(
    client: HttpClient | None = None,
) -> str:
    """
    下載集保戶股權分散表 CSV 原始字串（UTF-8）。

    URL: https://opendata.tdcc.com.tw/getOD.ashx?id=1-5

    回傳：CSV 內容字串（呼叫端負責 parse 與寫檔）
    """
    client = client or create_tdcc_opendata_client()
    url = f"{TDCC_OPENDATA_BASE}?{urlencode({'id': DATASET_HOLDER_DIST})}"
    response = client.session.get(url, timeout=60)
    response.raise_for_status()
    response.encoding = "utf-8"
    return response.text


def fetch_issuer_list(
    client: HttpClient | None = None,
) -> str:
    """
    下載上市公司資料清單 CSV（用於校對 stock universe）。

    URL: https://opendata.tdcc.com.tw/getOD.ashx?id=1-2
    """
    client = client or create_tdcc_opendata_client()
    url = f"{TDCC_OPENDATA_BASE}?{urlencode({'id': DATASET_ISSUER_LIST})}"
    response = client.session.get(url, timeout=60)
    response.raise_for_status()
    response.encoding = "utf-8"
    return response.text


def parse_holder_distribution_csv(csv_text: str) -> list[dict[str, Any]]:
    """
    解析 集保戶股權分散表 CSV → 結構化資料。

    每筆回傳：
        {
            'date': '2026-09-18',         # 資料日期（民國轉西元）
            'code': '2330',                # 證券代號
            'tier': 15,                     # 持股分級 (1-15)
            'people': 5210,                 # 該級距人數
            'shares': 12345678,            # 該級距股數
            'pct': 4.5,                     # 占集保庫存數比例%
        }

    CSV 格式（from opendata.tdcc.com.tw）：
        ﻿資料日期, 證券代號, 持股分級, 人數, 股數, 占集保庫存數比例%
        20260918, 000218, 1, 0, 0, 0.00
        ...
    """
    rows = []
    reader = csv.DictReader(io.StringIO(csv_text))
    for row in reader:
        try:
            # 處理可能的前置 BOM 或空白 key
            date_str = (row.get("資料日期") or row.get("\ufeff資料日期") or "").strip()
            code = (row.get("證券代號") or "").strip()
            tier_str = (row.get("持股分級") or "").strip()
            people_str = (row.get("人數") or "").strip()
            shares_str = (row.get("股數") or "").strip()
            pct_str = (row.get("占集保庫存數比例%") or "").strip()

            if not date_str or not code:
                continue

            # 民國年轉西元：例如 20260918 → 1160918 → 2026-09-18
            iso_date = _roc_date_to_iso(date_str)
            tier_num = int(tier_str)

            # 跳過合計行（tier 17）與特別股（tier 16）
            # 集保開放資料的 17 級中：
            #   1-15: 實際持股分級（1-999 股 ~ 1000 張以上）
            #   16: 特別股（0.00%）
            #   17: 合計（100.00%）— 必須排除避免重複加總
            if tier_num >= 16:
                continue

            rows.append({
                "date": iso_date,
                "code": code,
                "tier": tier_num,
                "people": int(people_str) if people_str else 0,
                "shares": int(shares_str) if shares_str else 0,
                "pct": float(pct_str) if pct_str else 0.0,
            })
        except (ValueError, KeyError):
            continue
    return rows


def _roc_date_to_iso(date_str: str) -> str:
    """
    民國日期轉 ISO 格式。

    TDCC 開放資料用「民國年 7 碼」: "20260918" → 116+1911=2026, 09, 18
    注意：TDCC 開放資料的「資料日期」是 7 碼（含民國 3 位數），不是 8 碼。
    """
    s = date_str.strip()
    if len(s) == 7 and s.isdigit():
        roc_year = int(s[:3])
        return f"{roc_year + 1911:04d}-{s[3:5]}-{s[5:7]}"
    elif len(s) == 8 and s.isdigit():
        # 已是西元年（防呆）
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return s


def aggregate_to_pct_400_1000(
    rows: list[dict[str, Any]],
    code: str,
) -> dict[str, Any]:
    """
    把同一檔個股的多級距資料彙總為四個關鍵大戶分級比例。

    TDCC 開放資料的 1-15 級對應（股數）：
    - level 1-11: 散戶 (1-400,000 股)
    - level 12:    400,001-600,000 股 (400-600 張)
    - level 13:    600,001-800,000 股 (600-800 張)
    - level 14:    800,001-1,000,000 股 (800-1000 張)
    - level 15:    >= 1,000,001 股 (1000 張以上)

    對應因子：
    - F1 大股東連續加碼 → pct_1000up（level 15 累計）
    - F4 集中度突破 → pct_400up（level 12+ 累計）
    - F6 散戶退場主力接手 → pct_400up_now（搭配散戶分級計算）

    註：神秘金字塔可能提供更精細的 1000+ 級、董監級，
    本系統以集保公開資料為主、神秘金字塔為輔。
    """
    relevant = [r for r in rows if r["code"] == code and r["tier"] < 16]
    if not relevant:
        return {
            "date": None,
            "code": code,
            "pct_400up_now": 0.0,
            "pct_600up_now": 0.0,
            "pct_800up_now": 0.0,
            "pct_1000up_now": 0.0,
            "people_400up_now": 0,
            "people_1000up_now": 0,
        }
    pct_400up = sum(r["pct"] for r in relevant if r["tier"] >= 12)   # 400 張以上
    pct_600up = sum(r["pct"] for r in relevant if r["tier"] >= 13)   # 600 張以上
    pct_800up = sum(r["pct"] for r in relevant if r["tier"] >= 14)   # 800 張以上
    pct_1000up = sum(r["pct"] for r in relevant if r["tier"] >= 15)  # 1000 張以上
    people_400up = sum(r["people"] for r in relevant if r["tier"] >= 12)
    people_1000up = sum(r["people"] for r in relevant if r["tier"] >= 15)
    return {
        "date": relevant[0]["date"],
        "code": code,
        "pct_400up_now": round(pct_400up, 2),
        "pct_600up_now": round(pct_600up, 2),
        "pct_800up_now": round(pct_800up, 2),
        "pct_1000up_now": round(pct_1000up, 2),
        "people_400up_now": people_400up,
        "people_1000up_now": people_1000up,
    }


# ============ 多週歷史支援 ============

def parse_holder_csv_to_pct_per_stock(
    csv_text: str,
) -> dict[str, dict[str, Any]]:
    """
    解析 CSV 為 { stock_code: aggregated_pct_dict } 結構。
    """
    rows = parse_holder_distribution_csv(csv_text)
    by_code: dict[str, list[dict]] = {}
    for r in rows:
        by_code.setdefault(r["code"], []).append(r)

    return {code: aggregate_to_pct_400_1000(rows, code) for code, rows in by_code.items()}


# ============ 多週歷史支援（cache 在 data/local/tdcc_history/）============

def save_history(
    parsed: list[dict[str, Any]],
    data_dir: Path,
    *,
    iso_date: str = "",
) -> Path:
    """
    把當週 parsed 結果存到 data/local/tdcc_history/YYYY-MM-DD.json

    這樣下週跑 pipeline 時，可以讀取「過去 4 週」組合成多週歷史，
    用於 F1 (大股東連續加碼) 的連續性判斷。
    """
    if not parsed:
        raise ValueError("empty parsed, nothing to save")
    date = iso_date or parsed[0].get("date")
    if not date:
        # fallback to current date
        from .base import taipei_today
        date = taipei_today()
    out_dir = data_dir / "local" / "tdcc_history"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{date}.json"
    write_json(out_path, parsed)
    return out_path


def load_history(
    data_dir: Path,
    *,
    weeks: int = 4,
) -> dict[str, list[dict[str, Any]]]:
    """
    載入過去 N 週的 TDCC 歷史。

    回傳：{ iso_date: [aggregated_pct_dict for each stock] }
    """
    history_dir = data_dir / "local" / "tdcc_history"
    if not history_dir.exists():
        return {}
    # 找出最近 N 週的日期
    files = sorted(history_dir.glob("*.json"), reverse=True)
    result = {}
    for f in files[:weeks]:
        date = f.stem  # YYYY-MM-DD
        result[date] = json.loads(f.read_text(encoding="utf-8"))
    return result


def compute_multi_week_trend(
    history: dict[str, list[dict[str, Any]]],
    code: str,
) -> dict[str, Any]:
    """
    從多週歷史計算「連續 4 週大戶分級變化」。

    回傳：
        {
            'code': '2330',
            'pct_1000up_w0': 84.7,  # 當週
            'pct_1000up_w1': 83.5,  # 上週
            'pct_1000up_w2': 82.8,  # 上上週
            'pct_1000up_w3': 81.0,  # 上上上週
            'pct_1000up_trend': '+',  # 連續 4 週都是 + (w3→w0)
        }
    """
    sorted_dates = sorted(history.keys(), reverse=True)
    out: dict[str, Any] = {"code": code, "pct_1000up_w0": None, "pct_1000up_w1": None,
                            "pct_1000up_w2": None, "pct_1000up_w3": None,
                            "pct_1000up_trend": "="}

    for i, date in enumerate(sorted_dates[:4]):
        rows = history[date]
        for row in rows:
            if row.get("code") == code:
                out[f"pct_1000up_w{i}"] = row.get("pct_1000up_now", 0.0)
                break

    # 計算趨勢：w0 (新) vs w3 (舊)
    newest = out["pct_1000up_w0"]
    oldest = out["pct_1000up_w3"]
    if newest is not None and oldest is not None:
        if newest > oldest + 0.5:
            out["pct_1000up_trend"] = "+"
        elif newest < oldest - 0.5:
            out["pct_1000up_trend"] = "-"
        else:
            out["pct_1000up_trend"] = "="
    return out


# Need this import
import json


# ============ 寫入輔助 ============

def save_latest(
    out_dir: Path,
    parsed: list[dict[str, Any]],
    *,
    snapshot_date: str = "",
) -> dict[str, str]:
    """寫入 out_dir/tdcc_chip.json 與快照。"""
    written = {}
    snapshot_date = snapshot_date or taipei_today()
    out_dir.mkdir(parents=True, exist_ok=True)
    snapshot_dir = out_dir.parent / snapshot_date
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    name = "tdcc_chip.json"
    latest_path = out_dir / name
    snapshot_path = snapshot_dir / name
    write_json(latest_path, parsed)
    write_json(snapshot_path, parsed)
    written[name] = str(latest_path)
    return written


if __name__ == "__main__":
    print("=== TDCC 政府資料開放平台 smoke test ===")
    print()
    print("1. 下載股權分散表 (id=1-5) ...")
    try:
        csv_text = fetch_holder_distribution()
        print(f"   OK: {len(csv_text)} bytes")
        rows = parse_holder_distribution_csv(csv_text)
        print(f"   parsed {len(rows)} rows")
        # 找 2330 (台積電)
        for r in rows[:5]:
            print(f"   sample: {r}")
        # 算 2330 與 2454 的彙總
        for code in ["2330", "2454", "2317"]:
            agg = aggregate_to_pct_400_1000(rows, code)
            print(f"   {code} aggregated: {agg}")
    except Exception as e:
        import traceback
        traceback.print_exc()
    print()
    print("2. 下載上市公司清單 (id=1-2) ...")
    try:
        text = fetch_issuer_list()
        print(f"   OK: {len(text)} bytes")
    except Exception as e:
        print(f"   ERROR: {e}")