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
import os
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
    env_get,
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
from backend.scrapers.pyramid import (
    is_available as pyramid_is_available,
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


def pipeline_limit(default: int = 5) -> int:
    """
    讀取 PIPELINE_LIMIT 設定，控制瀏覽器類來源要抓幾檔個股。

    這是**風控機制**：瀏覽器類來源（神秘金字塔 / 集保 / 玩股網 / MOPS）
    每檔都要發多次請求，檔數越多被封鎖的風險越高。
    設為 0 表示不限制（不建議）。

    讀取順序：程序環境變數 → backend/.env（與其他設定走同一條路徑，
    避免 .env.example 寫的值被靜默忽略 — 見體檢報告 BUG-13）。
    """
    raw = (env_get("PIPELINE_LIMIT") or "").strip()
    if not raw:
        return default
    try:
        n = int(raw)
    except ValueError:
        print(f"[WARN] PIPELINE_LIMIT 不是整數：{raw!r}，使用預設 {default}")
        return default
    if n <= 0:
        return 0  # 0 = 不限制
    return n


def _demo_codes() -> list[str]:
    """示範清單（backend/seed/demo_universe.json）的股票代號。

    這是 demo_subset.json 的母體；所有要合併進評分引擎的來源
    都必須抓「同一批」代號，否則合併層對不上。
    """
    seed_path = Path(__file__).resolve().parents[0] / "seed" / "demo_universe.json"
    try:
        payload = json.loads(seed_path.read_text(encoding="utf-8"))
        codes = [s["code"] for s in payload["stocks"] if s.get("code")]
        if codes:
            return codes
    except Exception:
        pass
    return ["2330", "2454", "2317", "2884", "2882"]


def _select_codes(out_dir: Path, default: int) -> list[str]:
    """從示範清單取出「要抓」的股票代號（受 PIPELINE_LIMIT 控管）。

    修正（2026-10）：舊版讀 `out_dir / "latest" / "universe.json"`，
    但 out_dir 本身就是 data/latest，實際路徑變成
    `data/latest/latest/universe.json`（不存在）→ 每次都靜默掉進
    fallback 的 5 檔硬編碼清單，等於所有來源都只抓那 5 檔。

    這是給「抓取成本高」的來源用的（MOPS / MoneyDJ / 玩股網）。
    要「發布」的代號請用 _publish_codes()（不設上限）。
    """
    limit = pipeline_limit(default)
    codes = _demo_codes()
    if limit > 0:
        codes = codes[:limit]
    return codes


def _publish_codes() -> list[str]:
    """要發布到 data/latest/ 的完整示範清單（**不受 PIPELINE_LIMIT 限制**）。

    為什麼要分開？
    PIPELINE_LIMIT 的目的是省下「抓取成本」（每檔要發多���請求），
    但「發布範圍」不該跟著縮 —— 否則只有前 N 檔有集保資料、
    其餘沒有，合併後的 demo_subset 會變成資料覆蓋不均，
    前端顯示的資料品質徽章也會不一致。
    """
    return _demo_codes()


# ============ 來源狀態更新 ============

# 所有已知來源（meta.json 一定要全部列出，
# 沒跑到的標成 not_run —— 前端 banner 才不會對 3/8 來源顯示「?」）
ALL_SOURCES = (
    "twse", "tpex", "finmind", "mops", "tdcc",
    "wantgoo_price", "wantgoo", "pyramid", "goodinfo",
)


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

    # 補上這次沒跑的來源（BUG-10：meta.json 原本只列有跑的來源）
    complete_sources: dict[str, Any] = {}
    for name in ALL_SOURCES:
        if name in sources_status:
            complete_sources[name] = sources_status[name]
        else:
            complete_sources[name] = {
                "status": "not_run",
                "reason": "本次排程未包含此來源",
            }
    # 若有不在 ALL_SOURCES 裡的來源（例如未來新增），也要保留
    for name, st in sources_status.items():
        if name not in complete_sources:
            complete_sources[name] = st

    cred = CredentialManager()
    meta = {
        "last_update_taipei": taipei_now_iso(),
        "snapshot_date": today,
        "previous_snapshot_date": last_snapshot,
        "data_freshness_hours": freshness_hours,
        "sources": complete_sources,
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
        stock_ids = _select_codes(out_dir, 50)
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
    """MOPS 公開資訊觀測站：抓董監事持股餘額明細（2026-10 修正 BUG-02）。

    純 HTTP（requests + Referer）即可，不需要 cookie 也不需要 Playwright。
    每檔股票需要 2 個請求：
      1. 本月的董監事持股餘額明細（→ 目前持股、設質股數、設質比例）
      2. 3 個月前的同一張表（→ 計算近 3 月持股變化率）
    """
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
        codes = _select_codes(out_dir, 5)

        director_results: list[dict[str, Any]] = []
        client = mops_scraper.create_mops_client()
        try:
            for code in codes:
                try:
                    # (1) 最新已公布月份（本月通常還沒公布，必須用 isnew=true）
                    cur_html = mops_scraper.fetch_director_holding(
                        code, 0, 0, client=client, is_new=True
                    )
                    cur = mops_scraper.parse_director_holding_html(cur_html, code)
                    if cur.get("no_data") or not cur.get("period"):
                        director_results.append({
                            "code": code,
                            "error": "MOPS 查無該公司的董監事持股資料",
                            "period": cur.get("period", ""),
                        })
                        continue

                    # (2) 往前推 3 個月 → 近 3 月持股變化率
                    py, pm = mops_scraper.roc_period_to_ym(cur["period"])
                    past_year, past_month = mops_scraper.shift_month(py, pm, -3)
                    past = None
                    try:
                        past_html = mops_scraper.fetch_director_holding(
                            code, past_year, past_month, client=client
                        )
                        past = mops_scraper.parse_director_holding_html(past_html, code)
                    except Exception as pe:
                        cur["past_error"] = str(pe)

                    director_results.append(
                        mops_scraper.combine_director_periods(cur, past)
                    )
                except Exception as e:
                    director_results.append({"code": code, "error": str(e)})

            # 董監質設異動（近 12 個月）
            pledge_results: list[dict[str, Any]] = []
            today = _taipei_now()
            for code in codes:
                try:
                    pl_html = mops_scraper.fetch_pledge(
                        code, today.year, today.month, client=client
                    )
                    pledge_results.append(
                        mops_scraper.parse_pledge_html(pl_html, code)
                    )
                except Exception as e:
                    pledge_results.append({"code": code, "error": str(e)})
        finally:
            client.session.close()

        mops_scraper.save_latest(out_dir, "director", director_results)
        mops_scraper.save_latest(out_dir, "pledge", pledge_results)

        ok = [d for d in director_results if "error" not in d]
        periods = sorted({d.get("period", "") for d in ok if d.get("period")})
        status["rows_count"] = len(ok)
        status["stocks_count"] = len(codes)
        status["pledge_events"] = sum(
            p.get("events", 0) for p in pledge_results if "error" not in p
        )
        status["note"] = (
            f"董監事持股餘額明細：{len(ok)}/{len(codes)} 檔成功"
            f"（資料年月 {', '.join(periods) or 'n/a'}）；"
            f"近 12 月質設異動 {status['pledge_events']} 筆"
        )
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
    """神秘金字塔 MoneyDJ — 抓週 K 線歷史（30+ 年）→ 價格衍生因子。

    2026-10 修正：
    - BCD 端點是公開下載型 API，**純 HTTP** 即可，不需要 Playwright
      （省下每檔 1-2 秒的瀏覽器啟動成本）
    - MoneyDJ 的 BCD 是「欄位-major」格式，舊的 parser 把它當成
      逐行 CSV 解析，結果只會得到 values 陣列 → 已重寫
    - 「持有人分級」HTML 解析器仍未實作（NotImplementedError），
      這裡只抓有實用價值的 K 線，節省額度
    """
    from backend.scrapers.pyramid import (
        create_pyramid_client,
        fetch_kline_bcd_http,
        is_sso_page,
        parse_kline_bcd_csv,
    )
    from backend.normalize import compute_price_derived

    status = {
        "status": "ok",
        "min_interval_sec": 8, "daily_quota": 100, "rows_count": 0,
    }
    # 注意：這裡要用「金字塔自己的」可用性檢查。
    # 舊版誤用 mops_available()（複製貼上錯誤），MOPS 被停用時會連帶
    # 讓 MoneyDJ 一起被跳過。
    if not pyramid_is_available():
        status["status"] = "skipped"
        status["reason"] = "MoneyDJ pyramid unavailable"
        return status
    try:
        codes = _select_codes(out_dir, 50)
        results: list[dict[str, Any]] = []
        client = create_pyramid_client()
        sso_hits = 0
        try:
            for code in codes:
                try:
                    text = fetch_kline_bcd_http(code, client=client, bar="W", count=9999)
                    if is_sso_page(text):
                        # MoneyDJ 對 BCD 端點要求登入 session。
                        # 這不是資料錯誤，必須明確標記出來，
                        # 否則會靜默產生「0 根 bar」而看不出原因。
                        sso_hits += 1
                        results.append({
                            "code": code,
                            "error": "MoneyDJ 需要登入 session（請執行 "
                                     "python -m backend.scripts.auth_setup --site pyramid）",
                        })
                        continue
                    bars = parse_kline_bcd_csv(text)
                    derived = compute_price_derived(bars, bar_days=5)
                    row = {
                        "code": code,
                        "ret_60d": derived["ret_60d"],
                        "drawdown_120d": derived["drawdown_120d"],
                        "is_60d_high": derived["is_60d_high"],
                        "crash_60d": derived["crash_60d"],
                        "bars": derived["bars"],
                        "last_date": derived["last_date"],
                    }
                    results.append(row)
                except Exception as e:
                    results.append({"code": code, "error": str(e)})
        finally:
            client.session.close()

        write_json(out_dir / "pyramid_price.json", results)
        ok = [r for r in results if "error" not in r]
        status["rows_count"] = len(ok)
        status["stocks_count"] = len(codes)
        status["sso_required"] = sso_hits
        if sso_hits:
            status["status"] = "skipped" if not ok else "partial"
            status["reason"] = (
                f"{sso_hits}/{len(codes)} 檔需要 MoneyDJ 登入 session"
            )
        status["note"] = (
            f"MoneyDJ 週 K 線：{len(ok)}/{len(codes)} 檔成功"
            f"（{ok[0]['bars'] if ok else 0} 根週 bar）"
        )
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
        codes = _select_codes(out, 5)
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


async def run_wantgoo_price_async(out_dir: Path) -> dict:
    """玩股網歷史 K 線（純 HTTP，免登入、免簽章）→ 價格衍生因子。

    這是 F2 / F3 / F8 / F9 / F10 的價格輸入來源。
    2026-10 實測：FinMind 已被付費牆擋、MoneyDJ 免登入只開放少數股票，
    玩股網的 /investrue/{code}/historical-daily-candlesticks 反而完整可用
    （每檔 490 根日 K 線，約兩年）。

    端點契約見 backend/scrapers/wantgoo.py 的說明（top 必須 490、
    before 必須是今天 00:00 台北的毫秒時間戳）。
    """
    from backend.scrapers import wantgoo as wantgoo_scraper
    from backend.normalize import compute_price_derived

    status = {
        "status": "ok",
        "min_interval_sec": 6, "daily_quota": 200, "rows_count": 0,
    }
    if not wantgoo_scraper.is_available():
        status["status"] = "skipped"
        status["reason"] = "wantgoo unavailable"
        return status
    try:
        # 價格歷史是所有因子的共同輸入 → 抓完整示範清單，不受 PIPELINE_LIMIT 限制
        codes = _publish_codes()
        results: list[dict[str, Any]] = []
        client = wantgoo_scraper.create_price_client()
        try:
            for code in codes:
                try:
                    bars = wantgoo_scraper.fetch_price_history(code, client=client)
                    if not bars:
                        results.append({"code": code, "error": "回傳空的 K 線資料"})
                        continue
                    derived = compute_price_derived(bars, bar_days=1)
                    results.append({
                        "code": code,
                        "ret_60d": derived["ret_60d"],
                        "drawdown_120d": derived["drawdown_120d"],
                        "is_60d_high": derived["is_60d_high"],
                        "crash_60d": derived["crash_60d"],
                        "bars": derived["bars"],
                        "last_date": derived["last_date"],
                    })
                except Exception as e:
                    results.append({"code": code, "error": str(e)})
        finally:
            client.session.close()

        write_json(out_dir / "wantgoo_price.json", results)
        ok = [r for r in results if "error" not in r]
        status["rows_count"] = len(ok)
        status["stocks_count"] = len(codes)
        if len(ok) == 0:
            status["status"] = "failed"
            status["error"] = next(
                (r["error"] for r in results if "error" in r), "unknown"
            )
        elif len(ok) < len(codes):
            status["status"] = "partial"
        status["note"] = (
            f"玩股網日 K 線：{len(ok)}/{len(codes)} 檔成功"
            f"（{ok[0]['bars'] if ok else 0} 根日 bar）"
        )
        return status
    except Exception as e:
        import traceback as _tb
        status["status"] = "failed"
        status["error"] = str(e)
        status["trace"] = _tb.format_exc()
        return status


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
        # 瀏覽器類來源很慢（每頁 5-10 秒延遲），先抓少量示範股
        codes = _select_codes(out_dir, 5)

        results: dict[str, list[dict[str, Any]]] = {
            "balance_sheet": [], "institutional": [], "main": [],
        }
        session = wantgoo_scraper.create_wantgoo_session()
        await session.start()
        try:
            for code in codes:
                for category, fetcher, parser in (
                    ("balance_sheet", wantgoo_scraper.fetch_balance_sheet,
                     wantgoo_scraper.parse_balance_sheet_html),
                    ("institutional", wantgoo_scraper.fetch_institutional,
                     wantgoo_scraper.parse_institutional_html),
                    ("main", wantgoo_scraper.fetch_main_page,
                     wantgoo_scraper.parse_main_page_html),
                ):
                    try:
                        html = await fetcher(code, session=session)
                        results[category].append(parser(html, code))
                    except Exception as e:
                        results[category].append({"code": code, "error": str(e)})
        finally:
            await session.close()

        for category, items in results.items():
            wantgoo_scraper.save_latest(out_dir, category, items)

        total = sum(len(v) for v in results.values())
        errors = [
            item for items in results.values() for item in items
            if item.get("error")
        ]
        status["rows_count"] = total - len(errors)
        status["errors"] = len(errors)
        if errors and status["rows_count"] == 0:
            status["status"] = "failed"
            status["error"] = errors[0]["error"]
        elif errors:
            status["status"] = "partial"
        status["note"] = (
            f"玩股網：{total - len(errors)}/{total} 筆成功"
            + (f"；{errors[0]['error']}" if errors else "")
        )
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
        # 3. 累積存 data/local/tdcc_history/<date>.json
        #    注意：傳 repo/"data"，save_history 內部會再接 "local/tdcc_history"，
        #    這樣才會落在 data/local/（受 .gitignore 保護的私有層），
        #    而非 repo 根目錄的 local/（BUG-06：曾被誤 commit 到公開倉庫）。
        data_root = repo / "data"
        if aggregated:
            first_date = aggregated[0].get("date")
            tdcc_opendata.save_history(aggregated, data_root, iso_date=first_date)
        # 4. 計算多週趨勢
        #    **順序很重要**：趨勢必須在存檔之前算好。
        #    舊版先 save_latest 再算 trend，導致 data/latest/tdcc_chip.json
        #    永遠缺少 pct_1000up_w1/w2/w3/trend → F1/F9/F10 永遠無法 strict 計算。
        #    歷史來源 = 私有完整歷史（本地）＋ 公開精簡歷史（CI 也能累積）
        history = tdcc_opendata.merge_history(
            tdcc_opendata.load_history(data_root, weeks=4),
            tdcc_opendata.load_public_history(out_dir),
        )
        if history:
            codes = [r["code"] for r in aggregated]
            by_code_map = {r["code"]: r for r in aggregated}
            for code in codes:
                trend = tdcc_opendata.compute_multi_week_trend(history, code)
                r = by_code_map.get(code)
                if r is None:
                    continue
                r["pct_1000up_trend"] = trend.get("pct_1000up_trend")
                r["pct_1000up_w1"] = trend.get("pct_1000up_w1")
                r["pct_1000up_w2"] = trend.get("pct_1000up_w2")
                r["pct_1000up_w3"] = trend.get("pct_1000up_w3")
        # 5. 存 data/latest/（含趨勢欄位）
        #    只發布**示範清單內**的個股：全市場版本有 4,000+ 檔、1.4MB，
        #    每天提交會讓公開倉庫快速膨脹（與 BUG-06 同一類問題）。
        #    全市場版本改存到私有層 data/local/tdcc_chip_full.json。
        demo_codes = _publish_codes()
        code_set = set(demo_codes)
        trimmed = [r for r in aggregated if r["code"] in code_set]
        tdcc_opendata.save_latest(out_dir, trimmed)
        full_path = repo / "data" / "local" / "tdcc_chip_full.json"
        write_json(full_path, aggregated)
        # 6. 存公開精簡歷史（讓 CI 也能累積多週趨勢）
        public_path = tdcc_opendata.save_public_history(aggregated, out_dir, demo_codes)
        status["public_history"] = bool(public_path)
        status["rows_count"] = len(rows)
        status["stocks_count"] = len(aggregated)
        status["published_stocks"] = len(trimmed)
        status["trend_codes"] = len([r for r in aggregated if r.get("pct_1000up_w3") is not None])
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
    # --- public 集合：全是政府 / 官方開放 API，純 HTTP，適合 CI 排程 ---
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

    # BUG-04：tdcc_opendata 原本只在 all/private 跑，
    # CI 的 public 排程從來沒執行過 → 集保資料永遠是舊的。
    # 集保開放平台是政府免費 API，純 HTTP，適合放進 CI。
    if source in ("all", "public", "private", "tdcc"):
        print("[6/8] TDCC 政府資料開放平台 (CSV, 免登入免費) ...")
        sources_status["tdcc"] = await run_tdcc_opendata_async(repo, out_dir)
        print(f"    {sources_status['tdcc']}")

    # --- private 集合：需要瀏覽器 / 登入 session / 較高負載，本地跑 ---
    # 玩股網**價格歷史**是純 HTTP、免登入 → 放 public（CI 排程）
    if source in ("all", "public", "private", "wantgoo_price"):
        print("[5a/8] Wantgoo 歷史 K 線 (純 HTTP, 免登入) ...")
        sources_status["wantgoo_price"] = await run_wantgoo_price_async(out_dir)
        print(f"    {sources_status['wantgoo_price']}")

    # Wantgoo 籌碼資料（法人 / 主力 / 融資券）：
    # 站方的個股 JSON API 需要 Cloudflare 注入的 x-client-signature，
    # 目前對未登入訪客回 400 → 這條路徑需要登入 session
    if source in ("all", "private", "wantgoo"):
        print("[5b/8] Wantgoo 籌碼 (法人/主力/融資券 — 目前需登入) ...")
        sources_status["wantgoo"] = await run_wantgoo_async(out_dir)
        print(f"    {sources_status['wantgoo']}")

    # MoneyDJ：BCD 端點現在要求登入 session（2026-10 實測），
    # 放 private 避免 CI 用 datacenter IP 大量打第三方站台。
    if source in ("all", "private", "pyramid"):
        print("[7/8] Pyramid (神秘金字塔 MoneyDJ 週 K 線) ...")
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
            "public = TWSE + TPEx + FinMind + MOPS + 集保開放平台（純 HTTP，CI 排程）。"
            "private = Wantgoo / MoneyDJ / Goodinfo（需瀏覽器或登入 session，本地跑）。"
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