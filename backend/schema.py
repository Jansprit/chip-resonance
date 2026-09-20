"""
schema.py — pydantic models + JSON Schema

用 pydantic 驗證抓回來的資料結構正確；用 JSON Schema 給前端 CI 驗證檔案格式。
"""

from __future__ import annotations

from typing import Optional
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

    if len(sys.argv) < 2:
        print("Usage: python -m backend.schema <file.json>")
        sys.exit(1)

    target = sys.argv[1]
    with open(target, encoding="utf-8") as f:
        data = _json.load(f)

    if isinstance(data, list) and data:
        # Pick model based on first item keys
        keys = set(data[0].keys())
        # demo_subset: has 'industry' and 'avg_volume' AND 'pct_1000up_now'
        if {"industry", "avg_volume", "pct_1000up_now"} & keys or (
            "industry" in keys and "avg_volume" in keys
        ):
            DemoStockSubsetEntry.model_validate(data[0])
            print(f"OK: demo_subset entry shape valid")
        # prices.json: has 'volume_lots' AND 'turnover' AND 'transactions' (TWSE raw format)
        elif {"volume_lots", "turnover", "transactions"} & keys:
            StockPrice.model_validate(data[0])
            print(f"OK: stock price entry shape valid")
        # universe.json: has 'volume_lots' but NOT 'turnover'/'transactions'
        elif "volume_lots" in keys:
            print(f"OK: universe entry shape valid (subset of stock price)")
        # market_index.json: has 'value' and 'change_pct'
        elif {"value", "change_pct"} & keys:
            MarketIndex.model_validate(data[0])
            print(f"OK: market index entry shape valid")
        else:
            print(f"WARN: unknown list element keys: {list(data[0].keys())}")
    elif isinstance(data, dict):
        MetaFile.model_validate(data)
        print(f"OK: meta shape valid")
    else:
        print(f"WARN: unexpected top-level type: {type(data)}")