"""
pipeline.py — 主流程 orchestrator

執行順序：
1. TWSE 抓取（價格 + 指數）
2. build_universe.py：合併 demo_subset.json 與全市場 universe.json
3. 寫 meta.json（包含各源狀態、節流配額）

回傳 0 = 全部成功，1 = 部分失敗，2 = 全部失敗（CI 會顯示但不會擋網站）
"""

from __future__ import annotations

import json
import sys
import traceback
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from scrapers.base import SourceBannedError, SourceDisabledError, taipei_now_iso, taipei_today, write_json
from scrapers.twse import create_twse_client, fetch_prices, fetch_market_index


def _taipei_now() -> datetime:
    tz = timezone(timedelta(hours=8))
    return datetime.now(tz)


def update_meta(out_dir: Path, sources_status: dict, notes: str = "") -> None:
    """更新 data/latest/meta.json。"""
    now = _taipei_now()
    today = now.date().isoformat()

    # 計算資料陳舊時數（從 snapshot_date 到現在）
    try:
        last_run_meta = json.loads((out_dir / "meta.json").read_text(encoding="utf-8"))
        last_snapshot = last_run_meta.get("snapshot_date", today)
    except Exception:
        last_snapshot = today

    freshness_hours = 0
    if last_snapshot != today:
        try:
            last_dt = datetime.fromisoformat(last_snapshot)
            now_dt = datetime.fromisoformat(today)
            freshness_hours = (now_dt - last_dt).days * 24
        except Exception:
            freshness_hours = 168  # assume 1 week stale on parse error

    meta = {
        "last_update_taipei": taipei_now_iso(),
        "snapshot_date": today,
        "previous_snapshot_date": last_snapshot,
        "data_freshness_hours": freshness_hours,
        "sources": sources_status,
        "notes": notes,
    }
    write_json(out_dir / "meta.json", meta)


def run_twse(out_dir: Path) -> dict:
    """抓 TWSE 並回傳狀態 dict。"""
    status = {"status": "ok", "stocks_count": 0, "indices_count": 0}
    try:
        client = create_twse_client()
        prices = fetch_prices(client)
        idx = fetch_market_index(client)
        write_json(out_dir / "prices.json", prices)
        write_json(out_dir / "market_index.json", idx)
        status["stocks_count"] = len(prices)
        status["indices_count"] = len(idx)
        return status
    except (SourceBannedError, SourceDisabledError) as e:
        status["status"] = "disabled"
        status["error"] = str(e)
        return status
    except Exception as e:
        status["status"] = "failed"
        status["error"] = str(e)
        status["trace"] = traceback.format_exc()
        return status


def build_universe(repo: Path) -> dict:
    """
    從 data/latest/prices.json 與 data.js 產出 demo_subset.json + universe.json。
    若失敗，保留之前的版本，不阻斷 pipeline。
    """
    import subprocess
    helper = repo / "backend" / "scripts" / "build_universe.py"
    try:
        result = subprocess.run(
            [sys.executable, str(helper)],
            capture_output=True,
            text=True,
            cwd=str(repo),
            timeout=60,
        )
        if result.returncode != 0:
            return {"status": "failed", "error": result.stderr[-500:]}
        # parse last line for counts
        return {"status": "ok", "log": result.stdout.strip().split("\n")[-3:]}
    except Exception as e:
        return {"status": "failed", "error": str(e)}


def main(
    repo: Path | None = None,
    source: str = "all",
    out_dir_name: str = "data/latest",
):
    repo = repo or Path(__file__).resolve().parents[1]
    out_dir = repo / out_dir_name
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"=== chip-resonance pipeline start ({taipei_now_iso()}) ===")
    print(f"  repo: {repo}")
    print(f"  out:  {out_dir}")
    print(f"  source: {source}")
    print()

    sources_status = {}

    # 1) TWSE
    if source in ("all", "twse"):
        print("[1/2] TWSE OpenAPI ...")
        twse_status = run_twse(out_dir)
        twse_status["min_interval_sec"] = 3
        twse_status["daily_quota"] = 500
        sources_status["twse"] = twse_status
        print(f"    status={twse_status['status']}  "
              f"stocks={twse_status['stocks_count']}  "
              f"indices={twse_status['indices_count']}")

    # 2) Build universe + merge
    if source in ("all", "twse"):  # universe depends on TWSE
        print()
        print("[2/2] build_universe ...")
        univ_status = build_universe(repo)
        sources_status["build_universe"] = univ_status
        print(f"    status={univ_status['status']}")

    # 3) Update meta
    update_meta(
        out_dir,
        sources_status,
        notes=(
            "Real TWSE prices + indices. Demo subset merged with real prices "
            "for 40 of 43 stocks; 3 (5347, 4743, 4128) are TPEx-only or delisted. "
            "Chip-related factors remain illustrative until P2/P3 (集保/MOPS)."
        ),
    )

    print()
    print(f"=== done ({taipei_now_iso()}) ===")

    # 決定 exit code
    statuses = [v.get("status") for v in sources_status.values()]
    if all(s == "ok" for s in statuses):
        return 0
    if any(s == "ok" for s in statuses):
        return 1
    return 2


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--source", default="all", choices=["all", "twse"])
    p.add_argument("--out-dir", default="data/latest")
    p.add_argument("--repo", default=None)
    args = p.parse_args()

    repo_path = Path(args.repo) if args.repo else None
    sys.exit(main(repo=repo_path, source=args.source, out_dir_name=args.out_dir))