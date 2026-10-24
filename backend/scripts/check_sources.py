"""
scripts/check_sources.py — 資料來源可達性健康度檢查

對應修復計畫 P2.2：「產出 source_health.json；矩陣文件涵蓋 8 源」。

**為什麼需要這支工具？**
本專案最貴的成本不是程式碼，是「以為某個來源還能用」。
MoneyDJ 被當成免費來源、FinMind 被當成免費 API、
集保 6-1 被當成股東人數 —— 每一個都是「看起來能用，實際上不能」，
而且都是寫完程式才發現。

把「來源還能不能用」變成**可程式化檢查 + 可版本控制的報告**，
才能讓下一個人（或半年後的我）不必重走一遍。

**誠實原則**
- 403 / 429 → `blocked`（不是 ok）。被擋就是被擋，不做美化。
- 200 但沒資料 → `empty`（不是 ok）。
- 連線失敗 → `error`，捕捉成結果而不是讓流程中斷。
- 筆數是「實際解析出來的」，不是猜的。

用法：
    python -m backend.scripts.check_sources                     # 全部來源
    python -m backend.scripts.check_sources --public-only       # 只查 public（CI 用）
    python -m backend.scripts.check_sources --output data/latest/source_health.json
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field, replace as _replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.console import configure_console  # noqa: E402

configure_console()

TAIPEI_TZ = timezone(timedelta(hours=8))
LATEST = REPO_ROOT / "data" / "latest"
DEFAULT_OUTPUT = LATEST / "source_health.json"

USER_AGENT = (
    "Mozilla/5.0 (compatible; ChipResonanceHealthCheck/1.0; "
    "+https://github.com/Jansprit/chip-resonance)"
)


# ==================================================================
# 來源清單（端點契約皆為 2026-10-24 實測結果）
# ==================================================================

@dataclass(frozen=True)
class SourceProbe:
    """一個來源的探測設定。"""
    name: str
    category: str            # public = 可在 CI / datacenter IP 執行；private = 僅本機
    method: str              # GET / POST
    url: str
    description: str
    headers: dict = field(default_factory=dict)
    data: dict = field(default_factory=dict)      # POST 表單
    timeout: int = 20
    # 需要日期參數的端點（TWSE T86 之類）在非交易日會回
    # 「很抱歉，沒有符合條件的資料」。若不往回試其他日期，
    # 會把「那天沒交易」誤判成「來源壞了」。
    fallback_urls: tuple[str, ...] = ()
    # 需登入的來源：回應裡出現這些標記就代表「被導到登入頁」，
    # 即使 HTTP 200 也不代表拿得到資料（MoneyDJ 就是這樣回 200 的）。
    block_markers: tuple[str, ...] = ()

    @property
    def blocked_reason(self) -> str:
        """這個來源在 CI 上不可用的原因（給矩陣文件用）。"""
        return {
            "wantgoo_price": "本機可用；GitHub Actions datacenter IP 回 403",
            "wantgoo_all_quote": "本機可用；datacenter IP 回 403",
            "moneydj_chip": "籌碼頁需會員（實測 2330 可、其餘 SSO）",
            "goodinfo_chip": "需登入 session",
            "finmind_api": "付費牆（免費層不提供該資料集）",
        }.get(self.name, "")


def _prev_weekday(days: int = 1) -> str:
    """回傳 N 個工作日前的 YYYYMMDD（給需要日期參數的 TWSE RWD 端點）。"""
    d = datetime.now(TAIPEI_TZ).date()
    left = days
    while left > 0:
        d -= timedelta(days=1)
        if d.weekday() < 5:
            left -= 1
    return d.strftime("%Y%m%d")


def _prev_month_first() -> str:
    """上一個月的 1 號 YYYYMMDD（TWSE RWD STOCK_DAY 每次回一個月）。"""
    today = datetime.now(TAIPEI_TZ).date()
    first = today.replace(day=1)
    last_month = first - timedelta(days=1)
    return last_month.strftime("%Y%m%d") + "01"


def _roc_date(days: int = 0) -> tuple[str, str]:
    """回傳 (民國年, 民國月) —— MOPS 的參數是民國。"""
    d = datetime.now(TAIPEI_TZ).date() - timedelta(days=days)
    return str(d.year - 1911), f"{d.month:02d}"


def _taipei_midnight_ms() -> int:
    """台北時區「今天 00:00」的毫秒時間戳。"""
    now = datetime.now(TAIPEI_TZ)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return int(midnight.timestamp() * 1000)


def _wantgoo_before(days_back: int) -> int:
    """
    玩股網 `before` 參數：某一天 00:00 台北的毫秒時間戳。

    伺服器的接受規則不透明（2026-10-25 實測：「今天 00:00」會 400，
    往前幾天才行），所以這裡用「往回推 N 天」的候選策略，
    與 backend/scrapers/wantgoo.py 的 price_history_before_candidates 同源。
    """
    now = datetime.now(TAIPEI_TZ)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(
        days=days_back
    )
    return int(midnight.timestamp() * 1000)


ROC_YEAR, ROC_MONTH = _roc_date(30)

SOURCE_REGISTRY: tuple[SourceProbe, ...] = (
    # ---------- TWSE 官方開放 API ----------
    SourceProbe(
        name="twse_stock_day_all",
        category="public",
        method="GET",
        url="https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL",
        description="TWSE 每日收盤行情（全市場）",
    ),
    SourceProbe(
        name="twse_mi_index",
        category="public",
        method="GET",
        url="https://openapi.twse.com.tw/v1/exchangeReport/MI_INDEX",
        description="TWSE 發行量加權指數（0050 對照組）",
    ),
    SourceProbe(
        name="twse_margin",
        category="public",
        method="GET",
        url="https://openapi.twse.com.tw/v1/exchangeReport/MI_MARGN",
        description="TWSE 融資融券餘額 → F9 融資使用率 / 融券比率",
    ),
    SourceProbe(
        name="twse_valuation",
        category="public",
        method="GET",
        url="https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_d",
        description="TWSE 基本資料（殖利率）→ F5 現金殖利率",
    ),
    SourceProbe(
        name="twse_company_basic",
        category="public",
        method="GET",
        url="https://openapi.twse.com.tw/v1/opendata/t187ap03_L",
        description="TWSE 公司基本資料（產業別 CID）→ F2 產業分類",
    ),
    SourceProbe(
        name="twse_stock_day",
        category="public",
        method="GET",
        url=(
            "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY"
            f"?date={_prev_month_first()}&stockNo=2330&response=json"
        ),
        description="TWSE 月線 OHLCV（官方，價格歷史交叉校驗用）",
    ),
    SourceProbe(
        name="twse_fund_t86",
        category="public",
        method="GET",
        url=(
            "https://www.twse.com.tw/rwd/zh/fund/T86"
            f"?date={_prev_weekday(1)}&response=json"
        ),
        description="TWSE 三大法人買賣超",
        # 非交易日會回「很抱歉，沒有符合條件的資料」→ 往回試前幾個工作日
        fallback_urls=tuple(
            f"https://www.twse.com.tw/rwd/zh/fund/T86?date={_prev_weekday(n)}&response=json"
            for n in range(2, 7)
        ),
    ),

    # ---------- TPEx ----------
    SourceProbe(
        name="tpex_daily_close",
        category="public",
        method="GET",
        url="https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes",
        description="TPEx 上櫃每日收盤行情",
    ),

    # ---------- 集保開放資料 ----------
    SourceProbe(
        name="tdcc_chip_grades",
        category="public",
        method="GET",
        url="https://opendata.tdcc.com.tw/getOD.ashx?id=1-5&type=csv",
        description="集保持股分級（1-5）→ F1 大戶持股比例 / F8",
    ),
    SourceProbe(
        name="tdcc_holder_index",
        category="public",
        method="GET",
        url="https://opendata.tdcc.com.tw/getOD.ashx?id=6-1&type=csv",
        description="集保 6-1（實測為指數清單，非個股股東人數）",
    ),

    # ---------- 價格歷史 ----------
    SourceProbe(
        name="yahoo_chart",
        category="public",
        method="GET",
        url="https://query1.finance.yahoo.com/v8/finance/chart/2330.TW?range=2y&interval=1d",
        description="Yahoo Finance 價格歷史（CI 可用的價格來源）",
    ),

    # ---------- MOPS ----------
    SourceProbe(
        name="mops_director",
        category="public",
        method="POST",
        url="https://mopsov.twse.com.tw/mops/web/ajax_stapap1",
        description="MOPS 董監持股 → F3 董監籌碼背離",
        data={
            "step": "1", "firstin": "ture", "off": "1", "TYPEK": "all",
            "isnew": "false", "queryName": "co_id", "inpuType": "co_id",
            "co_id": "2330", "year": ROC_YEAR, "month": ROC_MONTH,
        },
    ),

    # ---------- 需登入 / 付費 / datacenter IP 不可用 ----------
    SourceProbe(
        name="wantgoo_price",
        category="private",
        method="GET",
        url=(
            "https://www.wantgoo.com/investrue/2330/historical-daily-candlesticks"
            f"?before={_wantgoo_before(0)}&top=490"
        ),
        description="玩股網價格歷史（備援）",
        # 伺服器對 before 的接受規則不透明（今天 00:00 會 400）→ 往回試
        fallback_urls=tuple(
            "https://www.wantgoo.com/investrue/2330/historical-daily-candlesticks"
            f"?before={_wantgoo_before(k)}&top=490"
            for k in range(1, 8)
        ),
    ),
    SourceProbe(
        name="wantgoo_all_quote",
        category="private",
        method="GET",
        url="https://www.wantgoo.com/investrue/all-quote-info",
        description="玩股網全市場報價（6,044 檔）",
    ),
    SourceProbe(
        name="moneydj_chip",
        category="private",
        method="GET",
        url="https://www.moneydj.com/z/zc/zcj/2330.djhtm",
        description="MoneyDJ 籌碼頁（需會員）",
        # 未登入時會 302 到 SSO 登入頁（HTTP 200 + "Sign in Page"）
        block_markers=("Sign in Page",),
    ),
    SourceProbe(
        name="goodinfo_chip",
        category="private",
        method="GET",
        url="https://goodinfo.tw/tw/StockChipDetail.asp?STOCK_ID=2330",
        description="Goodinfo 籌碼（需登入 session）",
        block_markers=("請先登入", "登入"),
    ),
    SourceProbe(
        name="finmind_api",
        category="private",
        method="GET",
        url="https://api.finmindtrade.com/api/v4/data",
        description="FinMind 資料集（免費層為付費牆）",
    ),
)


# ==================================================================
# 探測
# ==================================================================

def _http_fetch(probe: SourceProbe, timeout: int) -> tuple[int, str]:
    """
    實際發出 HTTP 請求，回傳 (status_code, body_text)。

    5xx 與連線錯誤會**重試一次**（間隔 2 秒）：
    官方站點偶發的 502（例如 MOPS 在短時間內被密集請求時）
    不該被誤判成「來源壞掉」—— 那會讓人白白棄用一個可用的來源。
    """
    import time as _time

    import requests

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-TW,zh;q=0.9",
    }
    headers.update(probe.headers)
    last_exc: Optional[Exception] = None
    for attempt in range(2):
        try:
            if probe.method == "POST":
                resp = requests.post(
                    probe.url, data=probe.data, headers=headers, timeout=timeout
                )
            else:
                resp = requests.get(probe.url, headers=headers, timeout=timeout)
        except requests.RequestException as exc:
            last_exc = exc
            resp = None
        if resp is not None and resp.status_code < 500:
            return resp.status_code, resp.text
        if attempt == 0:
            _time.sleep(2)
    if resp is not None:
        return resp.status_code, resp.text
    raise last_exc if last_exc else RuntimeError("unknown fetch failure")


def _count_html_rows(body: str) -> int:
    """計算 HTML 表格的資料列數（不含表頭列）。"""
    import re

    rows = re.findall(r"<tr\b[^>]*>(.*?)</tr>", body, re.I | re.S)
    data_rows = 0
    for row in rows:
        cells = re.findall(r"<t[dh]\b", row, re.I)
        if not cells:
            continue
        # 只有 <th> 的列是表頭，不算資料
        if not re.search(r"<td\b", row, re.I):
            continue
        data_rows += 1
    return data_rows


def _count_records(body: str) -> int:
    """
    計算實際筆數。

    各來源的回應結構完全不同，**不可只算 JSON 陣列長度**：
      - TWSE openapi      → 頂層 JSON 陣列
      - TWSE RWD (T86 等) → {"tables": [[欄位陣列...]]}，長度 = 檔數
      - Yahoo chart       → {"chart": {"result": [{"timestamp": [...]}]}}
      - 集保              → CSV（扣表頭）
      - MOPS              → HTML 表格
    算不出來就回 0（誠實），不可猜。
    """
    text = (body or "").strip()
    if not text:
        return 0

    if text[0] in "[{":
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            data = None
        if isinstance(data, list):
            return len(data)
        if isinstance(data, dict):
            # Yahoo Finance：chart.result[0].timestamp
            chart = data.get("chart")
            if isinstance(chart, dict):
                results = chart.get("result") or []
                total = 0
                for item in results:
                    if isinstance(item, dict):
                        stamps = item.get("timestamp")
                        if isinstance(stamps, list):
                            total += len(stamps)
                        else:
                            total += 1
                if total:
                    return total
            # TWSE RWD（STOCK_DAY / T86 / …）：total = 資料列數，最權威
            # （total = 0 代表「那天沒有符合條件的資料」，是 0 不是 1）
            if "total" in data and isinstance(data.get("total"), int):
                return max(0, data["total"])
            # TWSE RWD 另一種外框：tables = [ [欄位...], [資料...] ]
            tables = data.get("tables")
            if isinstance(tables, list) and tables:
                best = 0
                for t in tables:
                    if isinstance(t, list):
                        best = max(best, len(t))
                return best
            for key in ("data", "aaData", "rows"):
                val = data.get(key)
                if isinstance(val, list):
                    return len(val)
            return 1
        return 0

    if "<tr" in text.lower() or "<table" in text.lower():
        return _count_html_rows(text)

    first_line = text.split("\n", 1)[0]
    if "," in first_line or "\t" in first_line:
        lines = [ln for ln in text.splitlines() if ln.strip()]
        return max(0, len(lines) - 1)
    return 0



def probe_source(
    probe: SourceProbe,
    fetcher: Optional[Callable[[SourceProbe, int], tuple[int, str]]] = None,
    timeout: Optional[int] = None,
) -> dict[str, Any]:
    """
    探測單一來源。

    **絕不拋例外** —— 任何失敗都轉成結果記錄，
    因為健康度檢查的用途就是「知道哪裡壞了」，不是「因為壞了所以看不到報告」。

    若第一個網址回 200 但沒有資料，會依序試 `fallback_urls`
    （用於「非交易日」的日期參數端點）。
    """
    fetch = fetcher or _http_fetch
    tmo = timeout or probe.timeout
    started = time.monotonic()

    status_code: Optional[int] = None
    body = ""
    error: Optional[str] = None
    used_url = probe.url

    for candidate in (probe.url, *probe.fallback_urls):
        attempt_probe = probe if candidate == probe.url else _replace(probe, url=candidate)
        try:
            status_code, body = fetch(attempt_probe, tmo)
        except Exception as exc:                  # noqa: BLE001 — 檢查工具必須吃掉所有錯誤
            if error is None:
                error = f"{type(exc).__name__}: {exc}"
            status_code = None
            body = ""
            continue
        used_url = candidate
        error = None
        records = _count_records(body) if body else 0
        if status_code and 200 <= status_code < 300 and records > 0:
            break

    latency_ms = int((time.monotonic() - started) * 1000)
    records = _count_records(body) if (error is None and body) else 0

    if error is not None:
        status = "error"
    elif status_code in (401, 403, 429):
        status = "blocked"
    elif status_code is not None and 200 <= status_code < 300:
        if probe.block_markers and all(m in (body or "") for m in probe.block_markers):
            # 登入頁：200 但拿不到資料 → blocked（不是 ok 也不是 empty）
            status = "blocked"
            error = "登入頁（需會員／session）"
        else:
            status = "ok" if records > 0 else "empty"
    else:
        status = "error"
        error = f"HTTP {status_code}"

    return {
        "name": probe.name,
        "category": probe.category,
        "method": probe.method,
        "url": used_url,
        "description": probe.description,
        "status": status,
        "http_status": status_code,
        "records": records,
        "latency_ms": latency_ms,
        "error": error,
        "blocked_reason": probe.blocked_reason,
        "checked_at": datetime.now(TAIPEI_TZ).isoformat(timespec="seconds"),
    }


def check_all(
    fetcher: Optional[Callable[[SourceProbe, int], tuple[int, str]]] = None,
    categories: Optional[tuple[str, ...]] = None,
    output: Optional[Path] = None,
    timeout: Optional[int] = None,
) -> dict[str, Any]:
    """探測所有來源，回傳健康度報告（並可寫出 JSON）。"""
    probes = [
        p for p in SOURCE_REGISTRY
        if categories is None or p.category in categories
    ]
    sources = [probe_source(p, fetcher=fetcher, timeout=timeout) for p in probes]

    counts: dict[str, int] = {}
    for s in sources:
        counts[s["status"]] = counts.get(s["status"], 0) + 1

    public_sources = [s for s in sources if s["category"] == "public"]
    public_ok = sum(1 for s in public_sources if s["status"] == "ok")

    report = {
        "generated_at": datetime.now(TAIPEI_TZ).isoformat(timespec="seconds"),
        "total": len(sources),
        "ok": counts.get("ok", 0),
        "blocked": counts.get("blocked", 0),
        "empty": counts.get("empty", 0),
        "error": counts.get("error", 0),
        "public_total": len(public_sources),
        "public_ok": public_ok,
        # public 來源有任何一個不是 ok → 降級
        "degraded": public_ok < len(public_sources),
        "categories": list(categories) if categories else ["public", "private"],
        "sources": sources,
    }

    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return report


# ==================================================================
# 矩陣文件產生
# ==================================================================

def render_matrix(report: dict[str, Any]) -> str:
    """把健康度報告轉成 Markdown 矩陣（供 docs/ 使用）。"""
    lines = [
        "<!-- 這份表格由 `python -m backend.scripts.check_sources` 產生，勿手動編輯 -->",
        "",
        "| 來源 | 分類 | 端點 | 狀態 | HTTP | 筆數 | 延遲 | 備註 |",
        "|---|---|---|---|---|---:|---:|---|",
    ]
    for s in report["sources"]:
        note = s.get("blocked_reason") or ""
        if s.get("error"):
            note = f"{note}；{s['error']}" if note else s["error"]
        lines.append(
            f"| `{s['name']}` | {s['category']} | `{s['url']}` | "
            f"{s['status']} | {s.get('http_status') or '-'} | "
            f"{s.get('records', 0)} | {s.get('latency_ms', 0)} ms | {note} |"
        )
    lines.append("")
    lines.append(
        f"產生時間：{report['generated_at']}　"
        f"（{report['ok']}/{report['total']} 正常、"
        f"{report['blocked']} 被擋、{report['empty']} 空資料、{report['error']} 錯誤）"
    )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    configure_console()
    ap = argparse.ArgumentParser(description="資料來源可達性健康度檢查")
    ap.add_argument("--public-only", action="store_true", help="只檢查 public 集合")
    ap.add_argument("--private-only", action="store_true", help="只檢查 private 集合")
    ap.add_argument("--output", default=str(DEFAULT_OUTPUT), help="輸出 JSON 路徑")
    ap.add_argument("--matrix", default=None, help="額外輸出 Markdown 矩陣")
    args = ap.parse_args()

    categories: Optional[tuple[str, ...]] = None
    if args.public_only:
        categories = ("public",)
    elif args.private_only:
        categories = ("private",)

    report = check_all(categories=categories, output=Path(args.output))

    print(f"=== 來源健康度 {report['generated_at']} ===")
    for s in report["sources"]:
        flag = {"ok": "OK  ", "blocked": "BLOCK", "empty": "EMPTY",
                "error": "ERR "}[s["status"]]
        print(
            f"  {flag} {s['name']:22s} {s['category']:8s} "
            f"{str(s.get('http_status') or '-'):>4s} "
            f"n={s.get('records', 0):<6d} {s.get('latency_ms', 0):>5d}ms"
            + (f"  {s['error']}" if s.get("error") else "")
        )
    print()
    print(f"  正常 {report['ok']} / {report['total']}　"
          f"被擋 {report['blocked']}　空 {report['empty']}　錯誤 {report['error']}")
    print(f"  public：{report['public_ok']}/{report['public_total']}"
          f"{'  ⚠️ 已降級' if report['degraded'] else ''}")
    print(f"  Wrote {args.output}")

    if args.matrix:
        Path(args.matrix).write_text(render_matrix(report), encoding="utf-8")
        print(f"  Wrote {args.matrix}")

    # 降級不讓 CLI 回傳非 0：健康度檢查是「回報」工具，不是「守門」工具。
    # 真正的守門在 CI 的 scrape 步驟（來源真的抓不到時它會失敗）。
    return 0


if __name__ == "__main__":
    sys.exit(main())
