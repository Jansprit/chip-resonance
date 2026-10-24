"""
schema.py — pydantic models + JSON Schema

用 pydantic 驗證抓回來的資料結構正確；用 JSON Schema 給前端 CI 驗證檔案格式。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator


class StockPrice(BaseModel):
    """TWSE 個股收盤行情單筆。"""

    code: str = Field(..., min_length=4, max_length=4)
    name: str
    exchange: str = "TWSE"
    date: str  # ISO YYYY-MM-DD
    price: float
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    change: float = 0.0
    volume_lots: int = 0
    turnover: int = 0
    transactions: int = 0

    @field_validator("code")
    @classmethod
    def _code_is_digits(cls, v: str) -> str:
        if not v.isdigit():
            raise ValueError(f"code must be all digits, got {v!r}")
        return v


class MarketIndex(BaseModel):
    date: str
    name: str
    value: float
    change_pct: float = 0.0


class DemoStockSubsetEntry(BaseModel):
    """
    demo_subset.json 內的個股：保留所有 scoring engine 需要的欄位。
    其中 chip 相關欄位 (pct_1000up_now, pct_400up, holder_cnt_change_8w 等)
    目前仍為示意值，未來 P2/P3 會從集保 / MOPS 替換為真實值。
    """

    code: str
    name: str
    industry: str
    price: float
    avg_volume: int
    director_pledge: float = 0.0
    eps_q4: float = 0.0
    list_year: int = 0
    warning: bool = False
    margin_pct: float = 0.0
    dt_ratio: float = 0.0
    pct_1000up_now: float = 0.0
    pct_1000up_w1: float = 0.0
    pct_1000up_w2: float = 0.0
    pct_1000up_w3: float = 0.0
    pct_400up: float = 0.0
    pct_400up_52w_high: bool = False
    holder_cnt_change_8w: float = 0.0
    avg_lot_change_8w: float = 0.0
    drawdown_120d: float = 0.0
    ret_60d: float = 0.0
    industry_ret_60d_med: float = 0.0
    director_holding_change_3m: float = 0.0
    div_years: int = 0
    yield_now: float = 0.0
    yield_5y_avg: float = 0.0
    crash_60d: bool = False
    pct_1000up_trend: str = "="
    is_60d_high: bool = False
    # Real-time fields (added by build_universe.py):
    exchange: Optional[str] = None
    date: Optional[str] = None
    _real_change: Optional[float] = None


class MetaFile(BaseModel):
    last_update_taipei: str
    snapshot_date: str
    sources: dict
    data_freshness_hours: int = 0
    notes: str = ""


class TdccChipEntry(BaseModel):
    """集保開放資料：持股分級（單一股票一列）。"""

    date: str
    code: str
    pct_400up_now: Optional[float] = None
    pct_600up_now: Optional[float] = None
    pct_800up_now: Optional[float] = None
    pct_1000up_now: Optional[float] = None
    people_400up_now: Optional[int] = None
    people_1000up_now: Optional[int] = None
    # 多週趨勢（由 pipeline 計算後併入）
    pct_1000up_w1: Optional[float] = None
    pct_1000up_w2: Optional[float] = None
    pct_1000up_w3: Optional[float] = None
    pct_1000up_trend: Optional[str] = None


class MopsDirectorEntry(BaseModel):
    """公開資訊觀測站：董監事持股餘額明細彙總。"""

    code: str
    period: Optional[str] = None
    rows: int = 0
    holding_total: float = 0.0
    pledged_total: float = 0.0
    pledge_pct: Optional[float] = None
    director_holding_change_3m: Optional[float] = None


class MopsPledgeEntry(BaseModel):
    """公開資訊觀測站：內部人設質解質異動彙總。"""

    code: str
    events: int = 0
    pledged_total: float = 0.0
    released_total: float = 0.0
    cumulative_max: float = 0.0
    no_data: bool = False


class PyramidPriceEntry(BaseModel):
    """MoneyDJ 週 K 線算出的價格衍生因子。"""

    code: str
    ret_60d: Optional[float] = None
    drawdown_120d: Optional[float] = None
    is_60d_high: Optional[bool] = None
    crash_60d: Optional[bool] = None
    bars: int = 0
    last_date: Optional[str] = None


class WantgooPriceEntry(BaseModel):
    """玩股網日 K 線算出的價格衍生因子（目前的主要價格歷史來源）。"""

    code: str
    ret_60d: Optional[float] = None
    drawdown_120d: Optional[float] = None
    is_60d_high: Optional[bool] = None
    crash_60d: Optional[bool] = None
    bars: int = 0
    last_date: Optional[str] = None


class PriceHistoryEntry(BaseModel):
    """Yahoo Finance 歷史 K 線（原始 bars，交由合併層現算衍生因子）。"""

    code: str
    bars: List[Dict[str, Any]] = Field(default_factory=list)


class MarginBalanceEntry(BaseModel):
    """TWSE MI_MARGN 融資融券餘額（F9 的 margin_pct / short_ratio）。"""

    margin_balance: Optional[float] = None
    margin_limit: Optional[float] = None
    margin_pct: Optional[float] = None
    short_balance: Optional[float] = None
    short_limit: Optional[float] = None
    short_pct: Optional[float] = None


class ValuationEntry(BaseModel):
    """TWSE BWIBBU_d 個股基本資料（F5 的 yield_now）。"""

    close_price: Optional[float] = None
    yield_now: Optional[float] = None
    dividend_year: Optional[int] = None
    pe_ratio: Optional[float] = None
    pb_ratio: Optional[float] = None


# ============ JSON Schema (給前端 CI 使用) ============

JSON_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "chip-resonance data file",
    "oneOf": [
        {
            "title": "prices.json — TWSE daily OHLCV",
            "type": "array",
            "items": {
                "type": "object",
                "required": ["code", "name", "exchange", "date", "price"],
                "properties": {
                    "code": {"type": "string", "pattern": "^[0-9]{4}$"},
                    "name": {"type": "string"},
                    "exchange": {"type": "string", "enum": ["TWSE"]},
                    "date": {"type": "string", "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}$"},
                    "price": {"type": "number", "minimum": 0},
                    "open": {"type": "number"},
                    "high": {"type": "number"},
                    "low": {"type": "number"},
                    "change": {"type": "number"},
                    "volume_lots": {"type": "integer", "minimum": 0},
                    "turnover": {"type": "integer", "minimum": 0},
                    "transactions": {"type": "integer", "minimum": 0},
                },
            },
        },
        {
            "title": "market_index.json — TWSE main indices",
            "type": "array",
            "items": {
                "type": "object",
                "required": ["date", "name", "value"],
                "properties": {
                    "date": {"type": "string", "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}$"},
                    "name": {"type": "string"},
                    "value": {"type": "number"},
                    "change_pct": {"type": "number"},
                },
            },
        },
        {
            "title": "universe.json — full market list",
            "type": "array",
            "items": {
                "type": "object",
                "required": ["code", "name", "exchange", "price"],
                "properties": {
                    "code": {"type": "string"},
                    "name": {"type": "string"},
                    "exchange": {"type": "string"},
                    "price": {"type": "number"},
                    "change": {"type": "number"},
                    "volume_lots": {"type": "integer"},
                    "turnover": {"type": "integer"},
                    "date": {"type": "string"},
                },
            },
        },
        {
            "title": "demo_subset.json — 43 demo stocks with full chip data",
            "type": "array",
            "items": {
                "type": "object",
                "required": ["code", "name", "industry", "price"],
                "properties": {
                    "code": {"type": "string"},
                    "name": {"type": "string"},
                    "industry": {"type": "string"},
                    "price": {"type": "number"},
                    "avg_volume": {"type": "integer"},
                    "director_pledge": {"type": "number"},
                    "eps_q4": {"type": "number"},
                    "list_year": {"type": "integer"},
                    "warning": {"type": "boolean"},
                    "margin_pct": {"type": "number"},
                    "dt_ratio": {"type": "number"},
                    "pct_1000up_now": {"type": "number"},
                    "pct_400up": {"type": "number"},
                    "pct_400up_52w_high": {"type": "boolean"},
                    "holder_cnt_change_8w": {"type": "number"},
                    "avg_lot_change_8w": {"type": "number"},
                    "drawdown_120d": {"type": "number"},
                    "ret_60d": {"type": "number"},
                    "industry_ret_60d_med": {"type": "number"},
                    "director_holding_change_3m": {"type": "number"},
                    "div_years": {"type": "integer"},
                    "yield_now": {"type": "number"},
                    "yield_5y_avg": {"type": "number"},
                    "crash_60d": {"type": "boolean"},
                    "pct_1000up_trend": {"type": "string"},
                    "is_60d_high": {"type": "boolean"},
                    "exchange": {"type": "string"},
                    "date": {"type": "string"},
                    "_real_change": {"type": "number"},
                },
            },
        },
        {
            "title": "_meta.json",
            "type": "object",
            "required": ["last_update_taipei", "snapshot_date", "sources"],
            "properties": {
                "last_update_taipei": {"type": "string"},
                "snapshot_date": {"type": "string"},
                "sources": {"type": "object"},
                "data_freshness_hours": {"type": "integer"},
                "notes": {"type": "string"},
            },
        },
    ],
}


if __name__ == "__main__":
    import json as _json
    import sys
    from pathlib import Path as _Path

    # --optional：檔案不存在時跳過（而非失敗）。
    # 有些資料檔是 pipeline 的中間產物，不會進版控（見 .gitignore），
    # CI 在沒有跑 pipeline 的情況下不應該因為它們不存在而失敗。
    args = [a for a in sys.argv[1:] if a != "--optional"]
    optional = "--optional" in sys.argv[1:]

    if len(args) < 1:
        print("Usage: python -m backend.schema [--optional] <file.json>")
        sys.exit(2)

    target = args[0]
    path = _Path(target)
    if not path.exists():
        if optional:
            print(f"SKIP: {target} 不存在（選用檔案）")
            sys.exit(0)
        print(f"FAIL: 檔案不存在：{target}")
        sys.exit(1)

    with open(path, encoding="utf-8") as f:
        data = _json.load(f)

    # 依「檔名」決定模型，而不是猜欄位。
    # 舊版靠第一筆的 key 猜，且多數分支只印 WARN 就 exit 0 ——
    # 等於 schema 驗證從來沒有真的擋下過壞資料（BUG-07 的深層問題）。
    name = path.name

    def _validate_all(model, rows, label):
        errors = []
        for i, row in enumerate(rows):
            try:
                model.model_validate(row)
            except Exception as e:  # pydantic ValidationError
                errors.append(f"  [{i}] {e}")
                if len(errors) >= 5:
                    break
        if errors:
            print(f"FAIL: {label} 驗證失敗（至少 {len(errors)} 筆）：")
            for e in errors:
                print(e)
            return 1
        print(f"OK: {label}（{len(rows)} 筆全部通過）")
        return 0

    if name == "meta.json":
        try:
            MetaFile.model_validate(data)
        except Exception as e:
            print(f"FAIL: meta.json 驗證失敗：{e}")
            sys.exit(1)
        print("OK: meta shape valid")
        sys.exit(0)

    if name == "tdcc_history_public.json":
        if not isinstance(data, dict):
            print("FAIL: tdcc_history_public.json 應為 object")
            sys.exit(1)
        bad = [
            k for k, v in data.items()
            if not isinstance(v, dict)
            or any(not isinstance(x, (int, float)) for x in v.values())
        ]
        if bad:
            print(f"FAIL: tdcc_history_public.json 結構錯誤：{bad[:5]}")
            sys.exit(1)
        print(f"OK: tdcc_history_public.json（{len(data)} 週）")
        sys.exit(0)

    if not isinstance(data, list):
        print(f"FAIL: {name} 最外層應為 array，實際是 {type(data).__name__}")
        sys.exit(1)

    if name == "demo_subset.json":
        if not data:
            print("FAIL: demo_subset.json 是空陣列")
            sys.exit(1)
        sys.exit(_validate_all(DemoStockSubsetEntry, data, name))

    if name in ("prices.json", "tpex_prices.json", "universe.json"):
        if not data:
            print(f"FAIL: {name} 是空陣列")
            sys.exit(1)
        sys.exit(_validate_all(StockPrice, data, name))

    if name == "market_index.json":
        if not data:
            print("FAIL: market_index.json 是空陣列")
            sys.exit(1)
        sys.exit(_validate_all(MarketIndex, data, name))

    if name == "tdcc_chip.json":
        if not data:
            print("FAIL: tdcc_chip.json 是空陣列")
            sys.exit(1)
        sys.exit(_validate_all(TdccChipEntry, data, name))

    if name == "mops_director.json":
        sys.exit(_validate_all(MopsDirectorEntry, data, name))

    if name == "mops_pledge.json":
        sys.exit(_validate_all(MopsPledgeEntry, data, name))

    if name == "pyramid_price.json":
        sys.exit(_validate_all(PyramidPriceEntry, data, name))

    if name == "wantgoo_price.json":
        sys.exit(_validate_all(WantgooPriceEntry, data, name))

    if name == "price_history.json":
        sys.exit(_validate_all(PriceHistoryEntry, data, name))

    if name == "margin_balance.json":
        # 以 code 為 key 的物件
        for code, entry in data.items():
            try:
                MarginBalanceEntry.model_validate(entry)
            except Exception as e:
                print(f"FAIL: margin_balance.json[{code}] 驗證失敗：{e}")
                sys.exit(1)
        print(f"OK: margin_balance.json（{len(data)} 檔全部通過）")
        sys.exit(0)

    if name == "valuation.json":
        for code, entry in data.items():
            try:
                ValuationEntry.model_validate(entry)
            except Exception as e:
                print(f"FAIL: valuation.json[{code}] 驗證失敗：{e}")
                sys.exit(1)
        print(f"OK: valuation.json（{len(data)} 檔全部通過）")
        sys.exit(0)

    if name == "industry.json":
        bad = [k for k, v in data.items() if not isinstance(v, str) or not v.strip()]
        if bad:
            print(f"FAIL: industry.json 結構錯誤：{bad[:5]}")
            sys.exit(1)
        print(f"OK: industry.json（{len(data)} 檔全部通過）")
        sys.exit(0)

    print(f"FAIL: 未知檔案類型 {name}，無法驗證")
    print("      請在 backend/schema.py 的 __main__ 補上對應的模型。")
    sys.exit(1)
