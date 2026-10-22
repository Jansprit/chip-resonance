"""
scrapers/wantgoo.py — 玩股網 (wantgoo.com) 抓取器

資料源：https://www.wantgoo.com/stock/<code>/...
- 融資券 → F9 價籌背離懲罰（margin_pct / short_ratio）
- 法人買賣超 → F8 回調籌碼守穩 / F10 利空籌碼修復
- 主力動向 → F10

**2026-10 修正（BUG-03）**
舊版的 4 個 URL 全部 404：

    /stock/{code}/balance-sheet              → 404
    /stock/{code}/financial/BS               → 404
    /stock/{code}/finance/balance_sheet      → 404
    /stock/{code}/institutional-investors    → 404

正確的頁面 URL（2026-10 實測 200）：
    /stock/{code}/margin-trading/synopsis          融資融券變化
    /stock/{code}/institutional-investors/trend     法人買賣超
    /stock/{code}/major-investors/main-trend       主力動向
    /stock/{code}/financial-statements/balance-sheet  財務報表

**資料 API**：每檔個股的 JSON API 會回 400 BadRequest。
原因不是參數或簽章 —— 站方自己的頁面請求（帶著站方自己產生的
`x-client-signature`）同樣回 400，代表該 API 目前對未登入訪客封鎖
（推測需會員登入）。因此本模組：

1. 先修好頁面 URL（原本 404 → 現在 200）
2. 解析改以「渲染後的表格」為主（表頭一定在，資料列由 API 填入）
3. **API 被擋時必須誠實回報錯誤，不得填 0** ——
   填 0 會讓 F9 以為「融資使用率 0%」，是比沒有資料更糟的假訊號

節流：8 秒/次（HTML 較大），單日上限 200 次。
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any, Optional

from .base import (
    BrowserSession,
    SessionStore,
    SessionNotFound,
    SessionExpired,
    CredentialManager,
    write_json,
    taipei_today,
    random_delay,
)


# 玩股網個股頁面
WANTAOO_BASE = "https://www.wantgoo.com/stock"

# 正確的頁面路徑（舊版這 4 個全 404）
PAGE_MARGIN = "margin-trading/synopsis"            # 融資融券變化
PAGE_INSTITUTIONAL = "institutional-investors/trend"  # 法人買賣超
PAGE_MAIN = "major-investors/main-trend"           # 主力動向
PAGE_BALANCE = "financial-statements/balance-sheet"  # 財務報表

# 每個頁面對應的資料 API（站方 JS 裡實際使用的路徑）
API_MARGIN = "/stock/{code}/margin-trading/historical-lending-balance"
API_INSTITUTIONAL = "/stock/{code}/institutional-investors/trend-data?topdays=60"
API_MAIN = "/stock/{code}/major-investors/main-trend-data"


def create_wantgoo_session(cred: CredentialManager | None = None) -> BrowserSession:
    """玩股網不需要登入，但需要 Playwright 過 Cloudflare。"""
    if cred is None:
        cred = CredentialManager()
    return BrowserSession(
        site="wantgoo",
        credential_manager=cred,
        session_store=SessionStore(),
        headless=True,
        require_session=False,  # 玩股網免登入
    )


def is_available() -> bool:
    """玩股網資料全部免登入；只要有 Playwright + Chromium 就能跑。"""
    return True


# ============ 抓取（渲染後的 HTML）============

async def _fetch_page(
    stock_code: str,
    page_path: str,
    session: BrowserSession | None = None,
    label: str = "page",
) -> str:
    """開啟某個玩股網頁面並回傳渲染後的 HTML。"""
    own_session = session is None
    if own_session:
        session = create_wantgoo_session()
        await session.start()
    try:
        url = f"{WANTAOO_BASE}/{stock_code}/{page_path}"
        html = await session.fetch(
            url,
            wait_selector="table",
            min_delay=5.0,
            max_delay=10.0,
            wait_rows=True,
        )
        debug_dir = Path(__file__).resolve().parents[1] / "data" / "local" / "raw" / "wantgoo"
        debug_dir.mkdir(parents=True, exist_ok=True)
        (debug_dir / f"{label}_{stock_code}.html").write_text(html, encoding="utf-8")
        return html
    finally:
        if own_session:
            await session.close()


async def fetch_balance_sheet(
    stock_code: str,
    session: BrowserSession | None = None,
) -> str:
    """融資券（融資融券變化）頁面 HTML。"""
    return await _fetch_page(stock_code, PAGE_MARGIN, session, "balance")


async def fetch_institutional(
    stock_code: str,
    session: BrowserSession | None = None,
) -> str:
    """法人買賣超頁面 HTML。"""
    return await _fetch_page(stock_code, PAGE_INSTITUTIONAL, session, "institutional")


async def fetch_main_page(
    stock_code: str,
    session: BrowserSession | None = None,
) -> str:
    """主力動向頁面 HTML。"""
    return await _fetch_page(stock_code, PAGE_MAIN, session, "main")


# ============ 解析 ============

def _build_grid(table) -> list[list[str]]:
    """把 HTML table 展開成二維陣列，正確處理 colspan / rowspan。

    玩股網的表格是**兩層表頭**（例：融資 → 餘額 / 限額 / 使用率%），
    不處理 rowspan 就會算錯欄位對應。
    """
    grid: list[list[str]] = []
    occupied: list[list[bool]] = []

    def _ensure(r: int, c: int) -> None:
        while len(grid) <= r:
            grid.append([])
            occupied.append([])
        while len(grid[r]) <= c:
            grid[r].append("")
            occupied[r].append(False)

    for r_i, tr in enumerate(table.find_all("tr")):
        col = 0
        for cell in tr.find_all(["td", "th"]):
            # 跳過被上方 rowspan 占用的欄位
            while True:
                _ensure(r_i, col)
                if occupied[r_i][col]:
                    col += 1
                    continue
                break
            try:
                rowspan = max(1, int(cell.get("rowspan", 1) or 1))
                colspan = max(1, int(cell.get("colspan", 1) or 1))
            except (TypeError, ValueError):
                rowspan = colspan = 1
            text = cell.get_text(" ", strip=True).replace("\n", "")
            for rr in range(r_i, r_i + rowspan):
                for cc in range(col, col + colspan):
                    _ensure(rr, cc)
                    grid[rr][cc] = text
                    occupied[rr][cc] = True
            col += colspan
    return grid


def _flatten_headers(header_rows: list[list[str]]) -> list[str]:
    """把多層表頭壓成單層：'融資' + '使用率%' → '融資使用率%'。"""
    width = max((len(r) for r in header_rows), default=0)
    out: list[str] = []
    for c in range(width):
        parts: list[str] = []
        for row in header_rows:
            value = row[c] if c < len(row) else ""
            value = value.strip()
            if value and (not parts or parts[-1] != value):
                parts.append(value)
        out.append("".join(parts))
    return out


def _tables(html: str) -> list[dict[str, Any]]:
    """把 HTML 拆成 [{headers, rows}, ...]。

    headers = 壓平後的單層表頭；rows = 真正的資料列
    （以「第一欄是日期」判定資料列起點，避免把第二層表頭當資料）。
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError as e:  # pragma: no cover
        raise RuntimeError(
            "需要 beautifulsoup4 才能解析玩股網 HTML："
            "pip install -r backend/requirements.txt"
        ) from e

    soup = BeautifulSoup(html, "lxml")
    date_re = re.compile(r"^\d{4}/\d{2}/\d{2}$")
    out: list[dict[str, Any]] = []
    for table in soup.find_all("table"):
        grid = _build_grid(table)
        grid = [r for r in grid if any(c.strip() for c in r)]
        if not grid:
            continue
        # 表頭列 = 資料列開始之前的列
        header_rows: list[list[str]] = []
        data_rows: list[list[str]] = []
        for row in grid:
            first = row[0].strip() if row else ""
            if date_re.match(first):
                data_rows.append(row)
            elif not data_rows:
                header_rows.append(row)
            else:
                data_rows.append(row)
        if not header_rows:
            continue
        out.append({
            "headers": _flatten_headers(header_rows),
            "rows": data_rows,
            "header_rows": header_rows,
        })
    return out


def _to_float(text: str) -> Optional[float]:
    if text is None:
        return None
    cleaned = text.replace(",", "").replace("%", "").strip()
    if not cleaned or cleaned in {"--", "-", "---", "N/A"}:
        return None
    m = re.search(r"-?\d+(?:\.\d+)?", cleaned)
    if not m:
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None


def _find_table(
    tables: list[dict[str, Any]],
    required: list[str],
) -> Optional[dict[str, Any]]:
    """找出同時含有指定欄位名稱的表格。"""
    for t in tables:
        joined = " ".join(t["headers"])
        if all(token in joined for token in required):
            return t
    return None


def _col(headers: list[str], token: str) -> int:
    """找欄位位置（token 可為子字串，例如 '使用率%'）。"""
    for i, h in enumerate(headers):
        if token in h:
            return i
    return -1


def parse_balance_sheet_html(html: str, stock_code: str) -> dict[str, Any]:
    """
    解析「融資融券變化」頁面。

    取得：
      - margin_pct   融資使用率 %
      - short_ratio  融券使用率 %
      - dt_ratio     當沖率 %

    **資料列是空的時必須回 error，不得回 0** ——
    0% 會讓 F9 以為「完全沒槓桿」，比沒有資料更糟。
    """
    tables = _tables(html)

    # 1) 融資 / 融券 使用率（兩層表頭：融資 → 餘額 / 限額 / 使用率%）
    margin_pct = short_ratio = None
    t1 = _find_table(tables, ["使用率%"])
    if t1 is not None:
        headers = t1["headers"]
        i_margin = _col(headers, "融資使用率%")
        i_short = _col(headers, "融券使用率%")
        rows = t1["rows"]
        if rows:
            row = rows[0]
            if 0 <= i_margin < len(row):
                margin_pct = _to_float(row[i_margin])
            if 0 <= i_short < len(row):
                short_ratio = _to_float(row[i_short])

    # 2) 當沖率%（在「資餘 / 資增 / 券餘 / … / 當沖率%」那張表）
    dt_ratio = None
    t0 = _find_table(tables, ["當沖率%"])
    if t0 is not None:
        idx = _col(t0["headers"], "當沖率%")
        rows = t0["rows"]
        if rows and 0 <= idx < len(rows[0]):
            dt_ratio = _to_float(rows[0][idx])

    if margin_pct is None and short_ratio is None and dt_ratio is None:
        return {
            "code": stock_code,
            "error": "融資融券表格沒有資料列（站方資料 API 目前對未登入訪客回 400）",
        }
    return {
        "code": stock_code,
        "margin_pct": margin_pct,
        "short_ratio": short_ratio,
        "dt_ratio": dt_ratio,
    }


def parse_institutional_html(html: str, stock_code: str) -> dict[str, Any]:
    """
    解析「法人買賣超」頁面 → 三大法人近 N 日買賣超（張）。

    回傳 {"code":..., "rows": [{date, foreign, investment_trust, dealer, total}, ...]}
    """
    tables = _tables(html)
    t = _find_table(tables, ["法人買賣超"])
    if t is None:
        t = _find_table(tables, ["三大法人"])
    if t is None:
        return {"code": stock_code, "error": "找不到法人買賣超表格"}
    if not t["rows"]:
        return {
            "code": stock_code,
            "error": "法人買賣超表格沒有資料列（站方資料 API 目前對未登入訪客回 400）",
        }

    headers = t["headers"]
    i_date = _col(headers, "日期")
    i_foreign = _col(headers, "外資")
    i_trust = _col(headers, "投信")
    i_dealer = _col(headers, "自營商")
    i_total = _col(headers, "總合")
    if i_foreign < 0 or i_trust < 0 or i_dealer < 0:
        return {"code": stock_code, "error": "法人欄位（外資/投信/自營商）找不到"}

    out = []
    for row in t["rows"]:
        if i_date < 0 or i_date >= len(row):
            continue
        date = row[i_date].strip()
        if not re.match(r"^\d{4}/\d{2}/\d{2}$", date):
            continue
        def _at(i: int) -> Optional[float]:
            return _to_float(row[i]) if 0 <= i < len(row) else None
        out.append({
            "date": date,
            "foreign": _at(i_foreign),
            "investment_trust": _at(i_trust),
            "dealer": _at(i_dealer),
            "total": _at(i_total),
        })
    if not out:
        return {"code": stock_code, "error": "法人買賣超表格沒有可解析的日期列"}
    return {"code": stock_code, "rows": out}


def parse_main_page_html(html: str, stock_code: str) -> dict[str, Any]:
    """
    解析「主力動向」頁面 → 主力買賣超（張）與集中度。

    回傳 {"code":..., "rows": [{date, close, net, broker_diff, conc5, conc20}, ...]}
    """
    tables = _tables(html)
    t = _find_table(tables, ["家數差"]) or _find_table(tables, ["買賣超"])
    if t is None:
        return {"code": stock_code, "error": "找不到主力動向表格"}
    if not t["rows"]:
        return {
            "code": stock_code,
            "error": "主力動向表格沒有資料列（站方資料 API 目前對未登入訪客回 400）",
        }

    headers = t["headers"]
    i_date = _col(headers, "日期")
    i_close = _col(headers, "收盤價")
    i_net = _col(headers, "買賣超")
    i_diff = _col(headers, "家數差")
    i_c5 = _col(headers, "5日集中")
    i_c20 = _col(headers, "20日集中")

    out = []
    for row in t["rows"]:
        if i_date < 0 or i_date >= len(row):
            continue
        date = row[i_date].strip()
        if not re.match(r"^\d{4}/\d{2}/\d{2}$", date):
            continue
        def _at(i: int) -> Optional[float]:
            return _to_float(row[i]) if 0 <= i < len(row) else None
        out.append({
            "date": date,
            "close": _at(i_close),
            "net": _at(i_net),
            "broker_diff": _at(i_diff),
            "conc5": _at(i_c5),
            "conc20": _at(i_c20),
        })
    if not out:
        return {"code": stock_code, "error": "主力動向表格沒有可解析的日期列"}
    return {"code": stock_code, "rows": out}


def parse_api_response(api_path: str, payload: Any) -> dict[str, Any]:
    """
    解析站方 JSON API 回應（若未來 API 恢復可用）。

    目前實測 API 一律回 400，因此這支主要作為格式契約的說明與未來接線點。
    """
    if isinstance(payload, dict) and payload.get("error"):
        return {"error": str(payload["error"])}
    if not isinstance(payload, list):
        return {"error": "API 回應不是陣列"}
    rows = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        rows.append(item)
    return {"rows": rows, "count": len(rows)}


# ============ 寫入輔助 ============

def save_latest(out_dir: Path, dataset_name: str, parsed: list[dict[str, Any]], *, snapshot_date: str = "") -> dict[str, str]:
    """寫入 out_dir/wantgoo_<dataset>.json 與快照。"""
    written = {}
    snapshot_date = snapshot_date or taipei_today()
    out_dir.mkdir(parents=True, exist_ok=True)
    snapshot_dir = out_dir.parent / snapshot_date
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    name = f"wantgoo_{dataset_name}.json"
    latest_path = out_dir / name
    snapshot_path = snapshot_dir / name
    write_json(latest_path, parsed)
    write_json(snapshot_path, parsed)
    written[name] = str(latest_path)
    return written


if __name__ == "__main__":
    print(f"is_available: {is_available()}")
    print(f"page margin      : {WANTAOO_BASE}/2330/{PAGE_MARGIN}")
    print(f"page institutional: {WANTAOO_BASE}/2330/{PAGE_INSTITUTIONAL}")
    print(f"page main         : {WANTAOO_BASE}/2330/{PAGE_MAIN}")
    print(f"api institutional : {API_INSTITUTIONAL.format(code='2330')}")
