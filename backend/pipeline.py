"""
pipeline.py — 主流程 orchestrator（7 源整合版）

執行順序：
1. 公開 API 源（無認證）：TWSE, TPEx, MOPS
2. 公開 API 源（可選認證）：FinMind（無 token 自動降級）
3. Playwright 源（需認證）：集保, 神秘金字塔, Goodinfo
4. 合併：normalize.py 統一 STOCK_UNIVERSE schema
5. 寫 meta.json（各源狀態、節流配額）

每個來源獨立失敗 → 不影響其他源。缺少憑證的來源自動 skip。
"""

from __future__ import annotations

import asyncio
import json
import sys
import traceback
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

# 注意：不修改 sys.path，避免 scrapers 與 backend.scrapers 變成兩個不同 module instance
# 若直接執行此檔（python pipeline.py），請從 repo root 用 `python -m backend.pipeline`

from backend.scrapers.base import (
    CredentialManager,
    SessionNotFound,
    SessionExpired,
    SourceBannedError,
    SourceDisabledError,
    SessionStore,
    taipei_now_iso,
    taipei_today,
    write_json,
)
from backend.scrapers.twse import (
    create_twse_client, fetch_prices, fetch_market_index,
    save_latest as twse_save_latest,
)
from backend.scrapers.tpex import (
    create_tpex_client, fetch_daily_quotes,
    save_latest as tpex_save_latest,
)
from backend.scrapers.finmind import (
    create_finmind_client,
    is_available as finmind_available,
    fetch_stock_prices,
    save_latest as finmind_save_latest,
)
from backend.scrapers.mops import (
    create_mops_client, fetch_director_holding,
    save_latest as mops_save_latest,
)
from backend.scrapers.tdcc import (
    create_tdcc_session, fetch_daily_range,
    save_latest as tdcc_save_latest,
)
from backend.scrapers.pyramid import (
    create_pyramid_session, fetch_chip_holders,
    save_latest as pyramid_save_latest,
)
from backend.scrapers.goodinfo import (
    create_goodinfo_session,
    fetch_director_pledge, fetch_margin_short, fetch_daytrade,
    save_latest as goodinfo_save_latest,
)
from backend.scrapers.us_markets import credentials_status as us_creds_status


def _taipei_now() -> datetime:
    tz = timezone(timedelta(hours=8))
    return datetime.now(tz)


# ============ 來源狀態更新 ============

def update_meta(out_dir: Path, sources_status: dict[str, Any], notes: str = "") -> None:
    """更新 data/latest/meta.json。"""
    now = _taipei_now()
    today = now.date().isoformat()
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
            freshness_hours = 168

    cred = CredentialManager()
    meta = {
        "last_update_taipei": taipei_now_iso(),
        "snapshot_date": today,
        "previous_snapshot_date": last_snapshot,
        "data_freshness_hours": freshness_hours,
        "sources": sources_status,
        "credentials": cred.summary(),
        "us_markets_credentials": us_creds_status(cred),
        "notes": notes,
    }
    write_json(out_dir / "meta.json", meta)


# ============ 個別來源 runner ============

def run_twse(out_dir: Path) -> dict:
    status = {"status": "ok", "stocks_count": 0, "indices_count": 0, "min_interval_sec": 3, "daily_quota": 500}
    try:
        client = create_twse_client()
        prices = fetch_prices(client)
        idx = fetch_market_index(client)
        # out_dir 是 repo/data/latest/，但 twse_save_latest 內部建 latest/ + <date>/
        # 所以傳 out_dir.parent（= repo/data/）讓它能正確建 repo/data/latest/ + repo/data/<date>/
        twse_save_latest(out_dir.parent, prices, idx)
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


def run_tpex(out_dir: Path) -> dict:
    status = {"status": "ok", "stocks_count": 0, "min_interval_sec": 3, "daily_quota": 500}
    try:
        client = create_tpex_client()
        rows = fetch_daily_quotes(client)
        # 傳 out_dir.parent（= repo/data/）讓 tpex_save_latest 正確建 latest/ + <date>/
        tpex_save_latest(out_dir.parent, rows)
        status["stocks_count"] = len(rows)
        return status
    except (SourceBannedError, SourceDisabledError) as e:
        status["status"] = "disabled"
        status["error"] = str(e)
        return status
    except Exception as e:
        import traceback as _tb
        status["status"] = "failed"
        status["error"] = str(e)
        status["trace"] = _tb.format_exc()
        print("  DEBUG run_tpex trace:\n" + status["trace"], flush=True)
        return status


def run_finmind(out_dir: Path) -> dict:
    """FinMind：沒 token 就 skip，graceful degradation。"""
    status = {
        "status": "skipped",
        "reason": "FINMIND_TOKEN not set" if not finmind_available() else None,
        "min_interval_sec": 5, "daily_quota": 200,
    }
    if not finmind_available():
        return status

    status["status"] = "ok"
    status["reason"] = None
    try:
        client = create_finmind_client()
        # 抓近 120 天所有上市股票的歷史價格（為 F8 回撤 + 60 日報酬計算準備）
        today = _taipei_now()
        from datetime import timedelta
        start = (today - timedelta(days=120)).strftime("%Y-%m-%d")
        end = today.strftime("%Y-%m-%d")
        # 簡化版：先抓大盤代號（取個股清單從 universe.json）
        try:
            universe = json.loads((out_dir / "universe.json").read_text(encoding="utf-8"))
            stock_ids = [s["code"] for s in universe[:50]]  # MVP 只抓前 50 檔
        except Exception:
            stock_ids = ["2330", "2454", "2317", "2884", "2882", "2303", "2603", "2609", "2886", "2891"]
        prices = fetch_stock_prices(stock_ids, start, end, client=client)
        finmind_save_latest(out_dir, "prices", prices, snapshot_date=taipei_today())
        status["rows_count"] = len(prices)
        return status
    except (SourceBannedError, SourceDisabledError) as e:
        status["status"] = "disabled"
        status["error"] = str(e)
        return status
    except Exception as e:
        status["status"] = "failed"
        status["error"] = str(e)
        return status


def run_mops(out_dir: Path) -> dict:
    """MOPS: 2024 rev endpoint unavailable, graceful skip for now."""
    from backend.scrapers.mops import is_available as mops_avail
    status = {
        "status": "skipped" if not mops_avail() else "ok",
        "min_interval_sec": 8, "daily_quota": 100, "rows_count": 0,
    }
    if not mops_avail():
        status["reason"] = "MOPS endpoint migrated in 2024; pending new URL"
        return status
    return status


async def _run_playwright_source(site: str, fetch_fn, out_dir: Path) -> dict:
    """包裝 Playwright 來源的 async 跑法。"""
    status = {
        "status": "ok",
        "min_interval_sec": {"tdcc": 20, "pyramid": 10, "goodinfo": 15}[site],
        "daily_quota": {"tdcc": 30, "pyramid": 200, "goodinfo": 60}[site],
    }
    store = SessionStore()
    if not store.exists(site):
        status["status"] = "skipped"
        status["reason"] = f"no session for {site}; run python -m backend.scripts.auth_setup --site {site}"
        return status
    try:
        await fetch_fn(out_dir)
        return status
    except (SessionNotFound, SessionExpired) as e:
        status["status"] = "session_expired"
        status["reason"] = str(e)
        return status
    except Exception as e:
        status["status"] = "failed"
        status["error"] = str(e)
        return status


async def run_tdcc_async(out_dir: Path) -> dict:
    async def _fetch(out):
        session = create_tdcc_session()
        html = await fetch_daily_range(session=session)
        # TODO: parse_daily_range_html → normalize → save
        # 暫存 raw HTML
        debug_path = out / "local" / "raw" / "tdcc" / "latest.html"
        debug_path.parent.mkdir(parents=True, exist_ok=True)
        debug_path.write_text(html, encoding="utf-8")
        return html
    return await _run_playwright_source("tdcc", _fetch, out_dir)


async def run_pyramid_async(out_dir: Path) -> dict:
    async def _fetch(out):
        session = create_pyramid_session()
        # 先抓 5 檔示範個股（避免一次抓太多觸發風控）
        try:
            universe = json.loads((out / "latest" / "universe.json").read_text(encoding="utf-8"))
            codes = [s["code"] for s in universe[:5]]
        except Exception:
            codes = ["2330", "2454", "2317", "2884", "2882"]
        htmls = await fetch_chip_holders(codes, session=session)
        # TODO: parse_chip_holders_html → normalize → save
        return htmls
    return await _run_playwright_source("pyramid", _fetch, out_dir)


async def run_goodinfo_async(out_dir: Path) -> dict:
    async def _fetch(out):
        session = create_goodinfo_session()
        try:
            universe = json.loads((out / "latest" / "universe.json").read_text(encoding="utf-8"))
            codes = [s["code"] for s in universe[:5]]
        except Exception:
            codes = ["2330", "2454", "2317", "2884", "2882"]
        results = []
        for code in codes:
            try:
                h_dir = await fetch_director_pledge(code, session=session)
                m_dir = await fetch_margin_short(code, session=session)
                d_dir = await fetch_daytrade(code, session=session)
                results.append({"code": code, "html_director": h_dir, "html_margin": m_dir, "html_daytrade": d_dir})
            except Exception as e:
                results.append({"code": code, "error": str(e)})
        # TODO: parse_* → normalize → save
        return results
    return await _run_playwright_source("goodinfo", _fetch, out_dir)


# ============ main ============

async def _main_async(repo: Path | None, source: str, out_dir_name: str) -> int:
    repo = repo or Path(__file__).resolve().parents[1]
    out_dir = repo / out_dir_name
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"=== chip-resonance pipeline (async) {taipei_now_iso()} ===")
    print(f"  repo: {repo}")
    print(f"  out:  {out_dir}")
    print(f"  source: {source}\n")

    sources_status: dict[str, Any] = {}

    # 同步源（先跑，避免 Playwright 來源失敗時已建立的資料被覆蓋）
    if source in ("all", "public", "twse"):
        print("[1/7] TWSE OpenAPI ...")
        sources_status["twse"] = run_twse(out_dir)
        print(f"    {sources_status['twse']}")

    if source in ("all", "public", "tpex"):
        print("[2/7] TPEx OpenAPI ...")
        sources_status["tpex"] = run_tpex(out_dir)
        print(f"    {sources_status['tpex']}")

    if source in ("all", "public", "finmind"):
        print("[3/7] FinMind ...")
        sources_status["finmind"] = run_finmind(out_dir)
        print(f"    {sources_status['finmind']}")

    if source in ("all", "public", "mops"):
        print("[4/7] MOPS ...")
        sources_status["mops"] = run_mops(out_dir)
        print(f"    {sources_status['mops']}")

    # Playwright 源（async）
    if source in ("all", "private", "tdcc"):
        print("[5/7] TDCC (集保) ...")
        sources_status["tdcc"] = await run_tdcc_async(out_dir)
        print(f"    {sources_status['tdcc']}")

    if source in ("all", "private", "pyramid"):
        print("[6/7] Pyramid (神秘金字塔) ...")
        sources_status["pyramid"] = await run_pyramid_async(out_dir)
        print(f"    {sources_status['pyramid']}")

    if source in ("all", "private", "goodinfo"):
        print("[7/7] Goodinfo ...")
        sources_status["goodinfo"] = await run_goodinfo_async(out_dir)
        print(f"    {sources_status['goodinfo']}")

    # Update meta
    update_meta(
        out_dir,
        sources_status,
        notes=(
            "Real TWSE + TPEx + FinMind + MOPS + (optionally) 集保/神秘金字塔/Goodinfo. "
            "Browser-based sources require auth_setup.py first; otherwise gracefully skipped."
        ),
    )

    print(f"\n=== done ({taipei_now_iso()}) ===")

    statuses = [v.get("status") for v in sources_status.values()]
    if not statuses:
        return 0
    if all(s in ("ok", "skipped") for s in statuses):
        return 0
    if any(s == "ok" for s in statuses):
        return 1
    return 2


def main(repo: Path | None = None, source: str = "all", out_dir_name: str = "data/latest"):
    return asyncio.run(_main_async(repo, source, out_dir_name))


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--source", default="all",
                   choices=["all", "public", "private", "twse", "tpex", "finmind", "mops", "tdcc", "pyramid", "goodinfo"])
    p.add_argument("--out-dir", default="data/latest")
    p.add_argument("--repo", default=None)
    args = p.parse_args()

    repo_path = Path(args.repo) if args.repo else None
    sys.exit(main(repo=repo_path, source=args.source, out_dir_name=args.out_dir))