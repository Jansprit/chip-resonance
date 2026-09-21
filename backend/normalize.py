"""
normalize.py — 把不同源的欄位統一成 STOCK_UNIVERSE schema

每個源回傳的原始資料欄位不同（例如 FinMind 用 snake_case、TPEx 用 PascalCase 中文、神秘金字塔自定），
此模組負責把它們都對齊成前端 computeScores() 需要的統一 STOCK_UNIVERSE 結構。

統一後的 STOCK_UNIVERSE 欄位：
    code              — 股票代號
    name              — 公司簡稱
    industry          — CID 產業分類
    price             — 最新收盤價
    avg_volume        — 20 日均量（單位：張），若無則用當日成交量近似
    director_pledge   — 董監質押率 %
    eps_q4            — 近四季累計 EPS（元）
    list_year         — 上市年數
    warning           — 是否警示股
    margin_pct        — 融資使用率 %
    dt_ratio          — 當沖比 %
    pct_1000up_now    — 1000 張以上大戶持股比例 %
    pct_1000up_w1/w2/w3 — 1/2/3 週前同樣數據
    pct_400up         — 400 張以上大戶持股比例 %
    pct_400up_52w_high — 是否創 52 週新高
    holder_cnt_change_8w — 股東總人數 8 週變化率 %
    avg_lot_change_8w — 平均持有張數 8 週變化率 %
    drawdown_120d    — 自 120 日高點回撤 %
    ret_60d           — 60 日報酬率 %
    industry_ret_60d_med — 同產業 60 日報酬中位數 %
    director_holding_change_3m — 董監近 3 月持股變化 %
    div_years         — 連續配息年數
    yield_now         — 目前殖利率 %
    yield_5y_avg      — 5 年平均殖利率 %
    crash_60d         — 60 日內曾單週跌幅 >15%
    pct_1000up_trend  — '+/=/−'
    is_60d_high       — 是否股價創 60 日新高
    date              — 資料日期 ISO
    exchange          — 'TWSE' | 'TPEx'
"""

from __future__ import annotations

import statistics
from typing import Any


# ============ 預設值（避免前端拿到 NaN）============

DEFAULTS = {
    "industry": "OTHER",
    "price": 0.0,
    "avg_volume": 0,
    "director_pledge": 0.0,
    "eps_q4": 0.0,
    "list_year": 0,
    "warning": False,
    "margin_pct": 0.0,
    "dt_ratio": 0.0,
    "pct_1000up_now": 50.0,   # 假設中性值，避免落入極端
    "pct_1000up_w1": 50.0,
    "pct_1000up_w2": 50.0,
    "pct_1000up_w3": 50.0,
    "pct_400up": 60.0,
    "pct_400up_52w_high": False,
    "holder_cnt_change_8w": 0.0,
    "avg_lot_change_8w": 0.0,
    "drawdown_120d": 0.0,
    "ret_60d": 0.0,
    "industry_ret_60d_med": 0.0,
    "director_holding_change_3m": 0.0,
    "div_years": 0,
    "yield_now": 0.0,
    "yield_5y_avg": 0.0,
    "crash_60d": False,
    "pct_1000up_trend": "=",
    "is_60d_high": False,
}


def merge_with_defaults(stock: dict[str, Any], defaults: dict[str, Any] = DEFAULTS) -> dict[str, Any]:
    """把缺少的欄位補成預設值（不覆蓋現有值）。"""
    merged = dict(defaults)
    merged.update(stock)
    # 確保產業在合理清單
    if merged.get("industry") not in _INDUSTRY_CODES:
        merged["industry"] = "OTHER"
    return merged


_INDUSTRY_CODES = {
    "SEMI", "FIN", "PCB", "BIO", "SHIP", "AUTO", "PLAS", "FOOD", "ELEC",
    "OTHER", "BOND", "ETF",
}


# ============ 各源 → STOCK_UNIVERSE 對映 ============

def from_twse(rows: list[dict]) -> list[dict]:
    """
    TWSE 個股行情（無 chip 因子，回傳預設值）。
    rows: backend/scrapers/twse.py parse_stock_daily_all() 輸出
    """
    out = []
    for r in rows:
        merged = merge_with_defaults({
            "code": r["code"],
            "name": r["name"],
            "price": r["price"],
            "avg_volume": r["volume_lots"],   # 近似：當日量
            "date": r.get("date", ""),
            "exchange": r.get("exchange", "TWSE"),
        })
        out.append(merged)
    return out


def from_tpex(rows: list[dict]) -> list[dict]:
    """
    TPEx 個股行情（無 chip 因子）。
    """
    out = []
    for r in rows:
        merged = merge_with_defaults({
            "code": r["code"],
            "name": r["name"],
            "price": r["price"],
            "avg_volume": r["volume_lots"],
            "date": r.get("date", ""),
            "exchange": r.get("exchange", "TPEx"),
        })
        out.append(merged)
    return out


def from_pyramid(rows: list[dict]) -> list[dict]:
    """
    神秘金字塔大戶持股週資料 → 直接覆寫 pct_1000up_* 與 pct_400up。

    rows 預期結構：
        {
            'code': '2330',
            'name': '台積電',
            'date': '2026-09-15',
            'pct_1000up_now': 67.5,
            'pct_1000up_w1': 67.2,
            'pct_1000up_w2': 67.0,
            'pct_1000up_w3': 66.8,
            'pct_400up': 82.1,
            'pct_400up_52w_high': False,
            'holder_cnt_change_8w': -2.1,
            'avg_lot_change_8w': 3.5,
        }
    """
    out = []
    for r in rows:
        merged = merge_with_defaults({
            "code": r["code"],
            "name": r.get("name", ""),
            "date": r.get("date", ""),
            "exchange": r.get("exchange", "TWSE"),
            "pct_1000up_now": r.get("pct_1000up_now", DEFAULTS["pct_1000up_now"]),
            "pct_1000up_w1": r.get("pct_1000up_w1", DEFAULTS["pct_1000up_w1"]),
            "pct_1000up_w2": r.get("pct_1000up_w2", DEFAULTS["pct_1000up_w2"]),
            "pct_1000up_w3": r.get("pct_1000up_w3", DEFAULTS["pct_1000up_w3"]),
            "pct_400up": r.get("pct_400up", DEFAULTS["pct_400up"]),
            "pct_400up_52w_high": r.get("pct_400up_52w_high", False),
            "holder_cnt_change_8w": r.get("holder_cnt_change_8w", 0.0),
            "avg_lot_change_8w": r.get("avg_lot_change_8w", 0.0),
        })
        # 計算 pct_1000up_trend
        delta = merged["pct_1000up_now"] - merged["pct_1000up_w3"]
        if delta > 0.5:
            merged["pct_1000up_trend"] = "+"
        elif delta < -0.5:
            merged["pct_1000up_trend"] = "-"
        else:
            merged["pct_1000up_trend"] = "="
        out.append(merged)
    return out


def from_tdcc(rows: list[dict]) -> list[dict]:
    """
    集保中心週股權分散表 → 同 from_pyramid，但用更多 1000 張級距。

    rows 預期結構：
        {
            'code': '2330',
            'date': '2026-09-15',
            'pct_1000up_now': 67.5, 'pct_1000up_w1': ..., 'pct_1000up_w2': ..., 'pct_1000up_w3': ...,
            'pct_400up_now': 82.1, 'pct_400up_w1': ..., ...
            'pct_600up_now': 73.2, ...,
            'pct_800up_now': 70.0, ...,
        }
    """
    out = []
    for r in rows:
        merged = merge_with_defaults({
            "code": r["code"],
            "date": r.get("date", ""),
            "pct_1000up_now": r.get("pct_1000up_now", DEFAULTS["pct_1000up_now"]),
            "pct_1000up_w1": r.get("pct_1000up_w1", DEFAULTS["pct_1000up_w1"]),
            "pct_1000up_w2": r.get("pct_1000up_w2", DEFAULTS["pct_1000up_w2"]),
            "pct_1000up_w3": r.get("pct_1000up_w3", DEFAULTS["pct_1000up_w3"]),
            "pct_400up": r.get("pct_400up_now", DEFAULTS["pct_400up"]),
            "pct_400up_52w_high": r.get("pct_400up_52w_high", False),
            "holder_cnt_change_8w": r.get("holder_cnt_change_8w", 0.0),
            "avg_lot_change_8w": r.get("avg_lot_change_8w", 0.0),
        })
        delta = merged["pct_1000up_now"] - merged["pct_1000up_w3"]
        merged["pct_1000up_trend"] = "+" if delta > 0.5 else ("-" if delta < -0.5 else "=")
        out.append(merged)
    return out


def from_mops_director(rows: list[dict]) -> list[dict]:
    """
    MOPS 董監事持股 → 覆寫 director_holding_change_3m 與 director_pledge。

    rows 預期結構：
        {
            'code': '2330',
            'date': '2026-09-15',
            'director_holding_pct': 0.5,     # 董監持股比例
            'director_holding_change_3m': 0.5, # 近3月變化 %
            'director_pledge_pct': 0.1,      # 質押率 %
        }
    """
    out = []
    for r in rows:
        merged = merge_with_defaults({
            "code": r["code"],
            "date": r.get("date", ""),
            "director_holding_change_3m": r.get("director_holding_change_3m", 0.0),
            "director_pledge": r.get("director_pledge_pct", 0.0),
        })
        out.append(merged)
    return out


def from_goodinfo_margin_short(rows: list[dict]) -> list[dict]:
    """
    Goodinfo 融資券 / 當沖比 → 覆寫 margin_pct 與 dt_ratio。

    rows 預期結構：
        {
            'code': '2330',
            'date': '2026-09-15',
            'margin_pct': 12.5,    # 融資使用率 %
            'short_ratio': 0.5,    # 融券使用率 %（暫存用）
            'dt_ratio': 18.0,      # 當沖比 %
        }
    """
    out = []
    for r in rows:
        merged = merge_with_defaults({
            "code": r["code"],
            "date": r.get("date", ""),
            "margin_pct": r.get("margin_pct", 0.0),
            "dt_ratio": r.get("dt_ratio", 0.0),
        })
        out.append(merged)
    return out


def from_finmind_prices(rows: list[dict]) -> dict[str, dict]:
    """
    FinMind TaiwanStockPrice → 計算 ret_60d 與 drawdown_120d。

    rows 預期結構：
        { 'stock_id': '2330', 'date': '2026-09-15', 'close': 2460.0, 'high': ..., 'low': ..., 'open': ... }

    回傳 { stock_id: { ret_60d, drawdown_120d, eps_q4, ... } } 以便 merge。
    """
    by_stock: dict[str, list[dict]] = {}
    for r in rows:
        sid = r.get("stock_id") or r.get("Code")
        if sid:
            by_stock.setdefault(sid, []).append(r)
    out = {}
    for sid, history in by_stock.items():
        history.sort(key=lambda x: x.get("date", ""))
        closes = [r.get("close") or r.get("Close") for r in history if r.get("close")]
        if not closes:
            continue
        current = closes[-1]
        ret_60d = (current / closes[-61] - 1) * 100 if len(closes) >= 61 else 0.0
        high_120d = max(closes[-121:]) if len(closes) >= 121 else max(closes)
        drawdown = (current / high_120d - 1) * 100 if high_120d else 0.0
        out[sid] = {
            "ret_60d": round(ret_60d, 2),
            "drawdown_120d": round(drawdown, 2),
            "is_60d_high": len(closes) >= 60 and current >= max(closes[-60:]),
        }
    return out


def from_finmind_month_revenue(rows: list[dict]) -> dict[str, dict]:
    """從 FinMind 月營收推算近四季累計營收（粗略 proxy）。"""
    by_stock: dict[str, list[dict]] = {}
    for r in rows:
        sid = r.get("stock_id") or r.get("stockId")
        if sid:
            by_stock.setdefault(sid, []).append(r)
    out = {}
    for sid, history in by_stock.items():
        history.sort(key=lambda x: x.get("revenue_month", ""), reverse=True)
        # 沒有 EPS 資料，僅標記有營收數據
        out[sid] = {
            "has_monthly_revenue": len(history) > 0,
        }
    return out


def merge_into(
    base_universe: list[dict],
    *chip_overlays: list[dict],
) -> list[dict]:
    """
    把多個來源的 chip overlay 合併進 base universe。

    base_universe: from_twse() / from_tpex() 產出的列表（含 price/avg_volume/date）
    chip_overlays: from_pyramid() / from_tdcc() / from_mops_director() / from_goodinfo_margin_short()
                   各自產出的列表

    合併規則：
    - 用 code 對齊
    - 後面的來源覆蓋前面的（依傳入順序決定優先級）
    """
    overlays_by_code: dict[str, list[dict]] = {}
    for overlay in chip_overlays:
        for entry in overlay:
            code = entry.get("code")
            if not code:
                continue
            overlays_by_code.setdefault(code, []).append(entry)

    out = []
    for stock in base_universe:
        code = stock.get("code")
        merged = dict(stock)
        for entry in overlays_by_code.get(code, []):
            for k, v in entry.items():
                if k == "code":
                    continue
                merged[k] = v
        out.append(merged)
    return out


# ============ 產業歸屬啟發式（用 stock code prefix 推 CID）============

# 簡化版：依股號首碼歸到常見產業
# 這只是 fallback；實際應該從 Goodinfo / TWSE 抓取正式 CID
CODE_TO_INDUSTRY_HINT = {
    # 半導體 — 23xx, 24xx, 30xx, 31xx, 37xx, 49xx, 52xx, 53xx, 64xx, 66xx, 80xx
    "23": "SEMI",
    "24": "SEMI",
    "30": "SEMI",
    "31": "SEMI",
    "37": "SEMI",  # 日月光投控
    "49": "SEMI",
    "52": "SEMI",
    "53": "SEMI",
    "64": "SEMI",  # 64xx 可為半導體或生技，預設半導體
    "66": "SEMI",
    "80": "SEMI",
    # 金融 — 28xx, 58xx, 60xx, 28xx
    "28": "FIN",
    "58": "FIN",
    "60": "FIN",
    "288": "FIN",
    "289": "FIN",
    "588": "FIN",
    # 生技 — 41xx, 17xx, 64xx (部分)
    "41": "BIO",
    "17": "BIO",
    # 航運 — 26xx
    "26": "SHIP",
    # 食品 — 12xx, 29xx
    "12": "FOOD",
    "29": "FOOD",  # 統一超
    # 塑化 — 13xx
    "130": "PLAS",
    "131": "PLAS",
    "132": "PLAS",
    "65": "PLAS",
    # PCB — 30xx 部分, 80xx 部分
    "303": "PCB",
    "318": "PCB",
}


def guess_industry(code: str) -> str:
    """用股號前 3 碼推 CID 產業。"""
    if not code:
        return "OTHER"
    for prefix_len in (3, 2, 1):
        prefix = code[:prefix_len]
        if prefix in CODE_TO_INDUSTRY_HINT:
            return CODE_TO_INDUSTRY_HINT[prefix]
    return "OTHER"