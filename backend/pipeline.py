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
    is_available as mops_available,
)
from backend.scrapers import tdcc_opendata
from backend.scrapers.tdcc import (
    create_tdcc_session, fetch_daily_range,
    save_latest as tdcc_save_latest,
)
# 注意：tdcc.py 的 Playwright 抓取已被 tdcc_opendata 取代（CSV 更穩定）
# 保留 import 以防有需要時用
# 主要路徑請見 run_tdcc_opendata_async
from backend.scrapers.pyramid import (
    create_pyramid_session,
    fetch_stock_page,
    fetch_kline_bcd,
    parse_kline_bcd_csv,
    save_latest as pyramid_save_latest,
)
from backend.scrapers.goodinfo import (
    create_goodinfo_session,
    fetch_director_pledge, fetch_margin_short, fetch_daytrade,
    save_latest as goodinfo_save_latest,
)
from backend.scrapers.us_markets import credentials_status as us_creds_status
from backend.scrapers import wantgoo as wantgoo_scraper


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


async def run_mops_async(out_dir: Path) -> dict:
    """MOPS 公開資訊觀測站：抓董監事與質押資料（2026-09 啟用）。"""
    from backend.scrapers import mops as mops_scraper
    status = {
        "status": "ok",
        "min_interval_sec": 8, "daily_quota": 100, "rows_count": 0,
    }
    if not mops_scraper.is_available():
        status["status"] = "skipped"
        status["reason"] = "MOPS unavailable"
        return status
    try:
        try:
            universe = json.loads((out_dir / "latest" / "universe.json").read_text(encoding="utf-8"))
            codes = [s["code"] for s in universe[:5]]
        except Exception:
            codes = ["2330", "2454", "2317", "2884", "2882"]
        current_year = _taipei_now().year
        director_results = []
        pledge_results = []
        session = mops_scraper.create_mops_session()
        await session.start()
        try:
            for code in codes:
                try:
                    h_dir = await mops_scraper.fetch_director_holding(code, current_year, session=session)
                    director_results.append({"code": code, "year": current_year, "html": h_dir})
                except Exception as e:
                    director_results.append({"code": code, "error": str(e)})
                try:
                    h_plg = await mops_scraper.fetch_pledge(code, session=session)
                    pledge_results.append({"code": code, "html": h_plg})
                except Exception as e:
                    pledge_results.append({"code": code, "error": str(e)})
        finally:
            await session.close()
        mops_scraper.save_latest(out_dir, "director", director_results)
        mops_scraper.save_latest(out_dir, "pledge", pledge_results)
        status["rows_count"] = len(director_results) + len(pledge_results)
        status["note"] = "Raw HTML stored; parsing needs selector tuning"
        return status
    except Exception as e:
        import traceback as _tb
        status["status"] = "failed"
        status["error"] = str(e)
        status["trace"] = _tb.format_exc()
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
    """神秘金字塔 MoneyDJ — 抓 K 線歷史（30+ 年）+ 個股頁面。"""
    from backend.scrapers.pyramid import (
        create_pyramid_session, fetch_stock_page, fetch_kline_bcd,
    )
    status = {
        "status": "ok",
        "min_interval_sec": 8, "daily_quota": 100, "rows_count": 0,
    }
    if not mops_available():
        status["status"] = "skipped"
        return status
    try:
        session = create_pyramid_session()
        await session.start()
        try:
            # 只抓 3 檔示範個股避免觸發風控
            try:
                universe = json.loads((out_dir / "latest" / "universe.json").read_text(encoding="utf-8"))
                codes = [s["code"] for s in universe[:3]]
            except Exception:
                codes = ["2330", "2454", "2454"]  # 示範用

            all_results = {"pages": [], "klines": {}}
            for code in codes:
                try:
                    page = await fetch_stock_page(code, session=session)
                    all_results["pages"].append({"code": code, "html_len": len(page)})
                except Exception as e:
                    all_results["pages"].append({"code": code, "error": str(e)})
                try:
                    kline_csv = await fetch_kline_bcd(code, session=session)
                    parsed = parse_kline_bcd_csv(kline_csv)
                    all_results["klines"][code] = {"weeks": len(parsed), "first_date": parsed[0]["date"] if parsed else None, "last_date": parsed[-1]["date"] if parsed else None}
                except Exception as e:
                    all_results["klines"][code] = {"error": str(e)}
        finally:
            await session.close()
        # 存到 out_dir
        pyramid_save_latest(out_dir, all_results["pages"])
        # 將 kline summary 另存
        write_json(out_dir / "pyramid_kline_summary.json", all_results["klines"])
        status["rows_count"] = len(all_results["pages"])
        status["note"] = "K 線 30+ 年歷史 + 個股頁面 HTML 已存。Holder distribution 解析待 tune。"
        return status
    except Exception as e:
        import traceback as _tb
        status["status"] = "failed"
        status["error"] = str(e)
        status["trace"] = _tb.format_exc()
        return status


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


async def run_wantgoo_async(out_dir: Path) -> dict:
    """玩股網 (wantgoo.com.tw) — 免登入但需 Playwright 過 Cloudflare。

    提供：
    - 融資券變化（F9 價籌背離懲罰）
    - 法人買賣超（F8 回調籌碼守穩 / F10 利空籌碼修復）
    - 當沖比（F9）

    8 秒/次節流，單日 200 次上限。
    """
    status = {
        "status": "ok",
        "min_interval_sec": 8, "daily_quota": 200, "rows_count": 0,
    }
    if not wantgoo_scraper.is_available():
        status["status"] = "skipped"
        status["reason"] = "wantgoo unavailable"
        return status
    try:
        # 從 universe.json 抓前 5 檔（MVP，避免 Playwright 來源耗時過長）
        try:
            universe = json.loads((out_dir / "latest" / "universe.json").read_text(encoding="utf-8"))
            codes = [s["code"] for s in universe[:5]]
        except Exception:
            codes = ["2330", "2454", "2317", "2884", "2882"]

        results = {"balance_sheet": [], "institutional": [], "main": []}
        session = wantgoo_scraper.create_wantgoo_session()
        await session.start()
        try:
            for code in codes:
                try:
                    results["balance_sheet"].append({"code": code, "html": await wantgoo_scraper.fetch_balance_sheet(code, session=session)})
                    results["institutional"].append({"code": code, "html": await wantgoo_scraper.fetch_institutional(code, session=session)})
                    results["main"].append({"code": code, "html": await wantgoo_scraper.fetch_main_page(code, session=session)})
                except Exception as e:
                    results["balance_sheet"].append({"code": code, "error": str(e)})
        finally:
            await session.close()

        # 存 raw HTML 供 parser 之後 tune selector
        for category, items in results.items():
            wantgoo_scraper.save_latest(out_dir, category, items)

        status["rows_count"] = sum(len(v) for v in results.values())
        status["note"] = "Raw HTML stored; parsing needs selector tuning"
        return status
    except Exception as e:
        import traceback as _tb
        status["status"] = "failed"
        status["error"] = str(e)
        status["trace"] = _tb.format_exc()
        return status


# ============ main ============

async def run_tdcc_opendata_async(repo: Path, out_dir: Path) -> dict:
    """
    TDCC 政府資料開放平台 — 完全免費、無需 API key。

    提供：全市場 1-15 級持股分級（含 400/600/800/1000 張以上），
    對應 F1 / F4 / F6 / F8 因子。

    每週五盤後釋出當週 CSV；本函式會：
    1. 下載當週 CSV
    2. 解析為結構化 pct_400up / 600up / 800up / 1000up
    3. 存到 data/latest/tdcc_chip.json
    4. 累積存到 data/local/tdcc_history/<date>.json（4 週保留）
    """
    status = {
        "status": "ok",
        "min_interval_sec": 1,
        "daily_quota": 100,
        "rows_count": 0,
        "stocks_count": 0,
    }
    if not tdcc_opendata.is_available():
        status["status"] = "skipped"
        status["reason"] = "TDCC opendata unavailable"
        return status
    try:
        # 1. 下載 + 解析
        client = tdcc_opendata.create_tdcc_opendata_client()
        csv_text = tdcc_opendata.fetch_holder_distribution(client=client)
        rows = tdcc_opendata.parse_holder_distribution_csv(csv_text)
        # 2. 依 code 彙總
        by_code = tdcc_opendata.parse_holder_csv_to_pct_per_stock(csv_text)
        aggregated = list(by_code.values())
        # 3. 存 data/latest/
        tdcc_opendata.save_latest(out_dir, aggregated)
        # 4. 累積存 data/local/tdcc_history/<date>.json
        if aggregated:
            first_date = aggregated[0].get("date")
            tdcc_opendata.save_history(aggregated, repo, iso_date=first_date)
        # 5. 計算多週趨勢
        history = tdcc_opendata.load_history(repo, weeks=4)
        if history:
            codes = [r["code"] for r in aggregated]
            for code in codes:
                trend = tdcc_opendata.compute_multi_week_trend(history, code)
                # 將 trend 合併進 aggregated
                for r in aggregated:
                    if r["code"] == code:
                        r["pct_1000up_trend"] = trend["pct_1000up_trend"]
                        r["pct_1000up_w1"] = trend["pct_1000up_w1"]
                        r["pct_1000up_w2"] = trend["pct_1000up_w2"]
                        r["pct_1000up_w3"] = trend["pct_1000up_w3"]
                        break
        status["rows_count"] = len(rows)
        status["stocks_count"] = len(aggregated)
        return status
    except Exception as e:
        import traceback as _tb
        status["status"] = "failed"
        status["error"] = str(e)
        status["trace"] = _tb.format_exc()
        return status


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
        print("[1/8] TWSE OpenAPI ...")
        sources_status["twse"] = run_twse(out_dir)
        print(f"    {sources_status['twse']}")

    if source in ("all", "public", "tpex"):
        print("[2/8] TPEx OpenAPI ...")
        sources_status["tpex"] = run_tpex(out_dir)
        print(f"    {sources_status['tpex']}")

    if source in ("all", "public", "finmind"):
        print("[3/8] FinMind ...")
        sources_status["finmind"] = run_finmind(out_dir)
        print(f"    {sources_status['finmind']}")

    if source in ("all", "public", "mops"):
        print("[4/8] MOPS ...")
        sources_status["mops"] = await run_mops_async(out_dir)
        print(f"    {sources_status['mops']}")

    if source in ("all", "public", "wantgoo"):
        print("[5/8] Wantgoo (玩股網 — 融資券/當沖比/法人) ...")
        sources_status["wantgoo"] = await run_wantgoo_async(out_dir)
        print(f"    {sources_status['wantgoo']}")

    # Playwright 源（async, 免登入但需 Playwright 過 Cloudflare）
    if source in ("all", "private", "tdcc"):
        print("[6/8] TDCC 政府資料開放平台 (CSV, 免登入免費) ...")
        sources_status["tdcc"] = await run_tdcc_opendata_async(repo, out_dir)
        print(f"    {sources_status['tdcc']}")

    if source in ("all", "private", "pyramid"):
        print("[7/8] Pyramid (神秘金字塔 — 免登入) ...")
        sources_status["pyramid"] = await run_pyramid_async(out_dir)
        print(f"    {sources_status['pyramid']}")

    if source in ("all", "private", "goodinfo"):
        print("[8/8] Goodinfo ...")
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