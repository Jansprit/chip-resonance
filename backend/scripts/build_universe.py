"""
scripts/build_universe.py — 合併各來源的真實資料到示範股票集，並標註每個欄位的資料來源

資料流：
    backend/seed/demo_universe.json   （43 檔示範個股 + 示意 chip 值）
        +
    data/latest/prices.json           （TWSE 真實收盤）
    data/latest/tpex_prices.json      （TPEx 真實收盤）
    data/latest/tdcc_chip.json        （集保開放資料：大戶持股分級 + 多週趨勢）
    data/latest/mops_director.json    （公開資訊觀測站：董監持股 / 質押）
    data/latest/pyramid_price.json    （MoneyDJ 週 K 線 → 價格衍生因子）
    data/latest/finmind_prices.json   （FinMind 歷史價 → 價格衍生因子，可選）
        ↓
    data/latest/demo_subset.json      （含 _provenance 欄位來源標記）

設計要點：
- **這是整個系統的關鍵橋接點**。
  v0.2.0 之前，本腳本只合併 TWSE / TPEx 價格，
  其他 6 個來源抓回來的資料全部停在各自的 JSON 檔裡，
  永遠進不了評分引擎 → 8/9 個因子永遠是示意值。
  現在每個來源都有對應的欄位映射與 provenance 標記。
- 每個欄位標明來源：_provenance 標記 real / illustrative，
  前端據此判斷哪些因子可計算（避免真實 now 混著示意 history 產生假 delta）。
- **原子覆寫**：多週欄位（w1/w2/w3）必須整組都有值才覆寫，
  否則保留示意值，避免「真實 now − 示意 history」的假 delta。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

# 統一 import 策略：把 repo root 加入 sys.path，
# 使 `python backend/scripts/x.py` 與 `python -m backend.scripts.x` 兩種呼叫都可用。
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.normalize import (  # noqa: E402
    FACTOR_INPUTS,
    attach_provenance,
    compute_industry_medians,
    compute_price_derived,
)


REPO = Path(__file__).resolve().parents[2]
SEED = REPO / "backend" / "seed" / "demo_universe.json"
LATEST = REPO / "data" / "latest"


# ============ 來源欄位映射 ============

# TDCC 開放資料欄位 → demo_subset 欄位
TDCC_FIELD_MAP = {
    "pct_1000up_now": "pct_1000up_now",
    "pct_1000up_w1": "pct_1000up_w1",
    "pct_1000up_w2": "pct_1000up_w2",
    "pct_1000up_w3": "pct_1000up_w3",
    "pct_1000up_trend": "pct_1000up_trend",
    "pct_400up_now": "pct_400up",
}

# 必須「整組都有值」才覆寫的多週欄位（避免真實 now 混著示意 history）
ATOMIC_GROUPS = [
    ["pct_1000up_w1", "pct_1000up_w2", "pct_1000up_w3"],
]

# MOPS 欄位 → demo_subset 欄位
MOPS_FIELD_MAP = {
    "director_holding_change_3m": "director_holding_change_3m",
    "pledge_pct": "director_pledge",
}

# 價格衍生欄位（由 K 線算出的）
PRICE_DERIVED_FIELDS = [
    "ret_60d",
    "drawdown_120d",
    "is_60d_high",
    "crash_60d",
]


def load_seed() -> list[dict]:
    if not SEED.exists():
        raise FileNotFoundError(
            f"Seed file missing: {SEED}\n"
            f"執行 python backend/scripts/make_seed.py 產生，或手動建立此檔。"
        )
    payload = json.loads(SEED.read_text(encoding="utf-8"))
    return payload["stocks"]


def load_latest(name: str) -> list[dict]:
    p = LATEST / name
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        print(f"  WARN: {name} 不是合法 JSON，略過")
        return []
    return data if isinstance(data, list) else []


def index_by_code(rows: list[dict]) -> dict[str, dict]:
    return {r["code"]: r for r in rows if isinstance(r, dict) and r.get("code")}


# ============ 合併 ============

def merge_prices(stock: dict, prices: dict[str, dict], real: set[str]) -> None:
    """TWSE / TPEx 真實收盤。"""
    p = prices.get(stock["code"])
    if not p:
        return
    if p.get("price") is not None:
        stock["price"] = p["price"]
        real.add("price")
    if p.get("volume_lots") is not None:
        stock["avg_volume"] = p["volume_lots"]
        real.add("avg_volume")
    if p.get("date"):
        stock["date"] = p["date"]
        real.add("date")
    if p.get("exchange"):
        stock["exchange"] = p["exchange"]
        real.add("exchange")
    if p.get("change") is not None:
        stock["_real_change"] = p["change"]


def merge_tdcc(stock: dict, chip: dict | None, real: set[str]) -> None:
    """集保開放資料：大戶持股分級 + 多週趨勢。"""
    if not chip:
        return
    staged: dict[str, Any] = {}
    for src, dst in TDCC_FIELD_MAP.items():
        value = chip.get(src)
        if value is None:
            continue
        staged[dst] = value

    # 原子覆寫：多週欄位要整組都有值
    for group in ATOMIC_GROUPS:
        if any(g not in staged for g in group):
            for g in group:
                staged.pop(g, None)

    # 趨勢本身也必須有多週資料才有意義：
    # 歷史不足時 compute_multi_week_trend 會回 "="，
    # 但那是「沒有資料」而不是「持平」，不能標成 real。
    if any(g not in staged for g in ATOMIC_GROUPS[0]):
        staged.pop("pct_1000up_trend", None)

    for field, value in staged.items():
        stock[field] = value
        real.add(field)


def merge_mops(stock: dict, director: dict | None, real: set[str]) -> None:
    """公開資訊觀測站：董監持股變化 + 董監質押率。"""
    if not director:
        return
    for src, dst in MOPS_FIELD_MAP.items():
        value = director.get(src)
        if value is None:
            continue
        stock[dst] = value
        real.add(dst)


def merge_price_derived(stock: dict, derived: dict | None, real: set[str]) -> None:
    """價格衍生欄位（ret_60d / drawdown_120d / is_60d_high / crash_60d）。"""
    if not derived:
        return
    for field in PRICE_DERIVED_FIELDS:
        value = derived.get(field)
        if value is None:
            continue
        stock[field] = value
        real.add(field)


def build(
    seed: list[dict],
    prices: list[dict],
    tpex: list[dict],
    tdcc: list[dict],
    mops: list[dict],
    pyramid_price: list[dict],
    finmind_prices: list[dict],
) -> tuple[list[dict], dict[str, int]]:
    """合併所有來源，回傳 (merged_stocks, stats)。"""
    price_map = index_by_code(prices)
    price_map.update(index_by_code(tpex))
    tdcc_map = index_by_code(tdcc)
    mops_map = index_by_code(mops)
    pyramid_map = index_by_code(pyramid_price)

    # FinMind 價格 → 價格衍生欄位（若無 token 會是空的，忽略）
    finmind_derived: dict[str, dict] = {}
    if finmind_prices:
        by_stock: dict[str, list[dict]] = {}
        for row in finmind_prices:
            sid = row.get("stock_id") or row.get("stockId") or row.get("code")
            if sid:
                by_stock.setdefault(str(sid), []).append(row)
        for sid, rows in by_stock.items():
            bars = []
            for r in rows:
                raw_date = r.get("date") or r.get("Date")
                close = r.get("close") or r.get("Close")
                if raw_date and close is not None:
                    bars.append({"date": str(raw_date), "close": float(close)})
            if bars:
                finmind_derived[sid] = compute_price_derived(bars, bar_days=1)

    merged: list[dict] = []
    stats = {
        "price": 0, "tdcc": 0, "mops": 0,
        "pyramid": 0, "finmind": 0,
    }

    for base in seed:
        stock = dict(base)
        stock.pop("_provenance", None)
        stock.pop("_real_change", None)
        real: set[str] = set()

        merge_prices(stock, price_map, real)
        if "price" in real:
            stats["price"] += 1

        merge_tdcc(stock, tdcc_map.get(stock["code"]), real)
        if "pct_1000up_now" in real:
            stats["tdcc"] += 1

        merge_mops(stock, mops_map.get(stock["code"]), real)
        if "director_holding_change_3m" in real or "director_pledge" in real:
            stats["mops"] += 1

        merge_price_derived(stock, pyramid_map.get(stock["code"]), real)
        if "ret_60d" in real:
            stats["pyramid"] += 1

        if stock["code"] in finmind_derived:
            before = len(real)
            merge_price_derived(stock, finmind_derived[stock["code"]], real)
            if len(real) > before:
                stats["finmind"] += 1

        attach_provenance(stock, real)
        merged.append(stock)

    # 產業中位數：必須在 provenance 標記之後算，
    # 因為 compute_industry_medians 只採用標記為 real 的 ret_60d。
    medians = compute_industry_medians(merged)
    for stock in merged:
        industry = stock.get("industry")
        median = medians.get(str(industry)) if industry else None
        if median is not None:
            stock["industry_ret_60d_med"] = median
            stock["_provenance"]["industry_ret_60d_med"] = "real"

    return merged, stats


# ============ 主流程 ============

def main() -> int:
    print("Loading seed ...")
    seed = load_seed()
    print(f"  seed stocks: {len(seed)}")

    print("Loading data/latest/*.json ...")
    prices = load_latest("prices.json")
    tpex = load_latest("tpex_prices.json")
    tdcc = load_latest("tdcc_chip.json")
    mops = load_latest("mops_director.json")
    pyramid_price = load_latest("pyramid_price.json")
    finmind_prices = load_latest("finmind_prices.json")
    print(f"  TWSE prices      : {len(prices)}")
    print(f"  TPEx prices      : {len(tpex)}")
    print(f"  TDCC chip        : {len(tdcc)}")
    print(f"  MOPS director    : {len(mops)}")
    print(f"  MoneyDJ price    : {len(pyramid_price)}")
    print(f"  FinMind prices   : {len(finmind_prices)}")

    merged, stats = build(
        seed, prices, tpex, tdcc, mops, pyramid_price, finmind_prices
    )
    print(f"  merged with real : {stats}")

    out = LATEST / "demo_subset.json"
    LATEST.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  Wrote {out} ({len(merged)} stocks)")

    # 摘要：哪些因子目前有真實資料
    prov0 = merged[0].get("_provenance", {}) if merged else {}
    real_factors = [
        f for f, inputs in FACTOR_INPUTS.items()
        if inputs and all(prov0.get(i) == "real" for i in inputs)
    ]
    print(f"  Factors with fully-real inputs (sample stock): {real_factors or 'none yet'}")

    # 全體統計：每個因子有多少檔股票可計算
    per_factor: dict[str, int] = {}
    for f, inputs in FACTOR_INPUTS.items():
        if not inputs:
            continue
        count = sum(
            1 for s in merged
            if all((s.get("_provenance") or {}).get(i) == "real" for i in inputs)
        )
        per_factor[f] = count
    print(f"  Factors computable per stock: {per_factor}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
