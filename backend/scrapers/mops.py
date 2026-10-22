"""
scrapers/mops.py — 公開資訊觀測站 (MOPS) 抓取器

MOPS 提供：董監事持股餘額明細、內部人設質解質、財務報表。

**2026-10 重大修正（BUG-02）**
先前版本的端點是錯的，難怪只會拿到 65 bytes 的錯誤頁：
    https://mops.twse.com.tw/mops/web/t146sb05  → 302 → /mops/error/404
正確的主機是 **mopsov.twse.com.tw**（不是 mops.twse.com.tw），
而且正確的查詢端點是 ajax 型：

    POST https://mopsov.twse.com.tw/mops/web/ajax_stapap1
      step=1&firstin=ture&off=1&TYPEK=all&isnew=false
      &queryName=co_id&inpuType=co_id&co_id=<代號>&year=<民國年>&month=<月>

回傳「董監事持股餘額明細」HTML 表格，欄位：
    職稱 | 姓名 | 選任時持股 | 目前持股 | 設質股數 | 設質股數佔持股比例
    | (配偶/未成年子女/他人名義持有)目前持股合計 | 設質股數 | 設質比例

實測結論：
- **不需要 cookie、也不需要 Playwright**，純 requests + Referer 即可。
- 回應是 UTF-8（不是 Big5），標籤是大寫 <TR>/<TD>。
- 查詢月份用**民國年**（西元 − 1911；2026 → 115），月份兩位數補零。

另外還有內部人設質解質異動：
    POST https://mopsov.twse.com.tw/mops/web/ajax_STAMAK03_1
      ...&b_date=<民國 YYYYMMDD>&e_date=<民國 YYYYMMDD>
（b_date / e_date 一定要用民國，給西元會回 "只可輸入民國日期"）

節流：8 秒/次，單日上限 100 次（保守，避免被 ban）。
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any, Optional

from .base import (
    HttpClient,
    RateLimiter,
    SourceHealth,
    RetryPolicy,
    write_json,
    taipei_today,
)


# ============ 端點 ============

MOPS_BASE = "https://mopsov.twse.com.tw"
# 董監事持股餘額明細（ajax）
MOPS_AJAX_DIRECTOR = f"{MOPS_BASE}/mops/web/ajax_stapap1"
# 內部人設質解質異動（ajax）
MOPS_AJAX_PLEDGE_EVENT = f"{MOPS_BASE}/mops/web/ajax_STAMAK03_1"
# 對應的查詢頁（當 Referer 用）
MOPS_PAGE_DIRECTOR = f"{MOPS_BASE}/mops/web/stapap1"
MOPS_PAGE_PLEDGE = f"{MOPS_BASE}/mops/web/STAMAK03_1"


# ============ 風控 ============

MOPS_MIN_INTERVAL_SEC = 8.0
MOPS_DAILY_QUOTA = 100
MOPS_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def is_available() -> bool:
    """MOPS 公開資訊觀測站免登入、純 HTTP 可用。"""
    return True


def create_mops_client() -> HttpClient:
    """建立受風控保護的 MOPS HTTP 客戶端（POST form-encoded）。"""
    rl = RateLimiter(min_interval=MOPS_MIN_INTERVAL_SEC, source_name="mops")
    health = SourceHealth(source_name="mops", daily_quota=MOPS_DAILY_QUOTA)
    client = HttpClient(
        rate_limiter=rl,
        health=health,
        retry=RetryPolicy(),
        user_agent=MOPS_USER_AGENT,
        timeout=40,
    )
    client.session.headers.update({
        "Referer": MOPS_PAGE_DIRECTOR,
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    })
    return client


# ============ 民國年 / 月 換算 ============

def to_roc(year: int, month: int) -> tuple[int, str]:
    """西元 (year, month) → (民國年, 民國月字串)。2026-10 → (115, '10')。"""
    return year - 1911, f"{month:02d}"


def roc_period_to_ym(period: str) -> tuple[int, int]:
    """民國年月的字串（'11509'）→ 西元 (2026, 9)。"""
    roc_y = int(period[:3])
    roc_m = int(period[3:5])
    return roc_y + 1911, roc_m


def shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    """把 (西元年, 月) 平移 delta 個月，回傳 (年, 月)。"""
    total = year * 12 + (month - 1) + delta
    return total // 12, total % 12 + 1


# ============ 抓取 ============

def fetch_director_holding(
    stock_id: str,
    year: int,
    month: int,
    client: Optional[HttpClient] = None,
    is_new: bool = False,
) -> str:
    """
    抓取特定股票某個月的「董監事持股餘額明細」HTML。

    year/month 為**西元**；內部會轉成民國年 + 兩位數月。

    is_new=True 時改抓「最新已公布月份」（MOPS 會自行挑最新有資料的月份）。
    這是必要的：當月的資料通常要次月才公布，直接查本月會得到
    「資料庫中查無資料」的空頁。呼叫端應先 is_new=True 拿 period，
    再往前推 3 個月查第二張表。
    """
    own_client = client is None
    if own_client:
        client = create_mops_client()
    try:
        roc_year, roc_month = to_roc(year, month)
        data = {
            "encodeURIComponent": "1",
            "step": "1",
            "firstin": "ture",
            "off": "1",
            "TYPEK": "all",
            "isnew": "true" if is_new else "false",
            "queryName": "co_id",
            "inpuType": "co_id",
            "co_id": stock_id,
        }
        if not is_new:
            data["year"] = str(roc_year)
            data["month"] = roc_month
        html = client.post_text(MOPS_AJAX_DIRECTOR, data=data)
        _save_debug(
            f"director_{stock_id}_{'latest' if is_new else f'{roc_year}{roc_month}'}.html",
            html,
        )
        return html
    finally:
        if own_client:
            client.session.close()


def fetch_pledge(
    stock_id: str,
    year: int,
    month: int,
    client: Optional[HttpClient] = None,
    lookback_months: int = 12,
) -> str:
    """
    抓取「內部人設質解質」異動明細 HTML。

    year/month 為西元（區間的結束月）；內部轉民國。
    b_date / e_date 必須是民國日期，給西元會被 MOPS 擋下
    （"只可輸入民國日期"）。

    lookback_months：往前追溯幾個月（預設 12）。單月的區間常常查無資料，
    用較長的區間才看得到董監的質設異動軌跡。
    """
    own_client = client is None
    if own_client:
        client = create_mops_client()
    try:
        import calendar

        # 區間：從 lookback_months 前的該月 1 號 ~ 到本月最後一天
        sy, sm = shift_month(year, month, -lookback_months)
        s_roc_year, s_roc_month = to_roc(sy, sm)
        start = s_roc_year * 10000 + int(s_roc_month) * 100 + 1

        end_year, end_month = shift_month(year, month, 1)
        end_roc_year, end_roc_month = to_roc(end_year, end_month)
        last_day = calendar.monthrange(end_year, end_month)[1]
        end = end_roc_year * 10000 + int(end_roc_month) * 100 + last_day

        data = {
            "encodeURIComponent": "1",
            "step": "1",
            "firstin": "ture",
            "off": "1",
            "TYPEK": "all",
            "queryName": "co_id",
            "inpuType": "co_id",
            "co_id": stock_id,
            "b_date": str(start),
            "e_date": str(end),
        }
        html = client.post_text(MOPS_AJAX_PLEDGE_EVENT, data=data)
        _save_debug(f"pledge_{stock_id}.html", html)
        return html
    finally:
        if own_client:
            client.session.close()


def _save_debug(name: str, html: str) -> None:
    """存 raw HTML 供 parser 之後 tune（受 .gitignore 保護的私有層）。"""
    debug_dir = Path(__file__).resolve().parents[1] / "data" / "local" / "raw" / "mops"
    debug_dir.mkdir(parents=True, exist_ok=True)
    (debug_dir / name).write_text(html, encoding="utf-8")


# ============ 解析 ============

_NUM_RE = re.compile(r"-?[\d,]+(?:\.\d+)?")


def _to_float(text: str) -> Optional[float]:
    """'1,600,000' → 1600000.0；'20.89%' → 20.89；無法解析回 None。"""
    if text is None:
        return None
    cleaned = text.replace(",", "").replace("%", "").strip()
    if not cleaned or cleaned in {"--", "-", "---"}:
        return None
    m = _NUM_RE.search(cleaned)
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


def _cell_texts(html: str) -> list[list[str]]:
    """把 MOPS 表格攤平成「每列的欄位文字」。

    MOPS 的標籤大小寫不一致（<TR>/<TD>、<tr>/<td>），
    這裡用 BeautifulSoup 正規化處理，並自動略過表頭列。
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError as e:  # pragma: no cover - requirements 已含 beautifulsoup4
        raise RuntimeError(
            "需要 beautifulsoup4 才能解析 MOPS HTML："
            "pip install -r backend/requirements.txt"
        ) from e

    soup = BeautifulSoup(html, "lxml")
    rows: list[list[str]] = []
    for tr in soup.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
        if cells:
            rows.append(cells)
    return rows


def parse_director_holding_html(html: str, stock_id: str) -> dict[str, Any]:
    """
    解析 MOPS「董監事持股餘額明細」→ 持股與質押彙總。

    回傳：
        {
          "code": "2330",
          "period": "11509",          # 資料年月（民國年 + 月）
          "rows": 12,                 # 董監事筆數
          "holding_total": 1.66e9,    # Σ 目前持股（股）
          "pledged_total": 1.6e6,     # Σ 設質股數（股）
          "pledge_pct": 0.096,        # 設質比例 %
        }
    """
    rows = _cell_texts(html)

    holding_total = 0.0
    pledged_total = 0.0
    count = 0
    for cells in rows:
        # 資料列：9 欄，前兩欄是職稱與姓名
        if len(cells) < 6:
            continue
        name = cells[1]
        if not name or name in {"姓名", "職稱"}:
            continue
        holding = _to_float(cells[3])
        pledged = _to_float(cells[4])
        if holding is None and pledged is None:
            continue
        holding_total += holding or 0.0
        pledged_total += pledged or 0.0
        count += 1

    period = ""
    m = re.search(r"資料年月\s*:\s*(\d{5,6})", html)
    if m:
        period = m.group(1)

    # MOPS 對沒有資料的月份會回「資料庫中查無資料 !」
    no_data = "查無資料" in html

    pledge_pct = (pledged_total / holding_total * 100) if holding_total > 0 else None
    return {
        "code": stock_id,
        "period": period,
        "no_data": no_data,
        "rows": count,
        "holding_total": holding_total,
        "pledged_total": pledged_total,
        "pledge_pct": round(pledge_pct, 4) if pledge_pct is not None else None,
    }


def parse_pledge_html(html: str, stock_id: str) -> dict[str, Any]:
    """
    解析 MOPS「內部人設質解質」異動明細 → 筆數與合計設質/解質股數。

    表格欄位（11 欄）：
        公司代號 | 公司名稱 | 設質人身份別 | 設質人姓名 | 質設異動發生日期
        | 設質股數 | 解質股數 | 累積質設股數 | 質權人姓名 | 備註 | 申報日期

    回傳：
        { "code": "2330", "events": 1, "pledged_total": 50000,
          "released_total": 0, "cumulative_max": 100000 }
    """
    rows = _cell_texts(html)
    events = 0
    pledged_total = 0.0
    released_total = 0.0
    cumulative_max = 0.0
    for cells in rows:
        if len(cells) < 8:
            continue
        # 第 5 欄（index 4）是異動日期，格式 114/04/08
        if not re.search(r"\d{3}/\d{2}/\d{2}", cells[4]):
            continue
        pledged = _to_float(cells[5])
        released = _to_float(cells[6])
        cumulative = _to_float(cells[7])
        if pledged is None and released is None:
            continue
        events += 1
        pledged_total += pledged or 0.0
        released_total += released or 0.0
        cumulative_max = max(cumulative_max, cumulative or 0.0)

    return {
        "code": stock_id,
        "events": events,
        "pledged_total": pledged_total,
        "released_total": released_total,
        "cumulative_max": cumulative_max,
        "no_data": "查無需求資料" in html or "查無資料" in html,
    }


def combine_director_periods(
    current: dict[str, Any],
    past: dict[str, Any] | None,
) -> dict[str, Any]:
    """
    合併兩個月份 → 董監近 3 個月持股變化率 (%)。

    current / past 都是 parse_director_holding_html() 的輸出。
    沒有 past 時，change 為 None（不可計算，該因子應標記為 unavailable）。
    """
    change = None
    if past and past.get("holding_total"):
        change = (
            (current.get("holding_total", 0.0) - past["holding_total"])
            / past["holding_total"]
            * 100
        )
        change = round(change, 4)
    return {
        "code": current.get("code"),
        "period": current.get("period"),
        "rows": current.get("rows", 0),
        "holding_total": current.get("holding_total", 0.0),
        "pledged_total": current.get("pledged_total", 0.0),
        "pledge_pct": current.get("pledge_pct"),
        "director_holding_change_3m": change,
    }


# ============ 寫入輔助 ============

def save_latest(out_dir: Path, dataset_name: str, parsed: list[dict[str, Any]], *, snapshot_date: str = "") -> dict[str, str]:
    """寫入 out_dir/mops_<dataset>.json 與快照。"""
    written = {}
    snapshot_date = snapshot_date or taipei_today()
    out_dir.mkdir(parents=True, exist_ok=True)
    snapshot_dir = out_dir.parent / snapshot_date
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    name = f"mops_{dataset_name}.json"
    latest_path = out_dir / name
    snapshot_path = snapshot_dir / name
    write_json(latest_path, parsed)
    write_json(snapshot_path, parsed)
    written[name] = str(latest_path)
    return written


if __name__ == "__main__":
    print(f"is_available: {is_available()}")
    print(f"MOPS_AJAX_DIRECTOR: {MOPS_AJAX_DIRECTOR}")
    print(f"MOPS_AJAX_PLEDGE_EVENT: {MOPS_AJAX_PLEDGE_EVENT}")
    print(f"roc(2026, 10) = {to_roc(2026, 10)}")
    print(f"shift_month(2026, 10, -3) = {shift_month(2026, 10, -3)}")
