"""
scripts/build_universe.py — 合併 TWSE 真實價格到 demo 股票集

產出：
- data/latest/demo_subset.json    43 檔示範個股的完整資料（real price + illustrative chip data）
- data/latest/universe.json       1082 檔真實 TWSE 個股的即時報價（不含 chip data）

設計：
- demo_subset.json 保留所有 chip 因子欄位，讓 scoring engine 仍可運作
- universe.json 用於「全市場即時報價」面板與 TAIEX 比對
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def load_js_universe(data_js_path: Path) -> list[dict]:
    """用 Node.js 載入 data.js 並輸出 STOCK_UNIVERSE 為 JSON。"""
    helper_path = Path(__file__).parent / "_load_js_universe.js"
    tmp_json = Path(__file__).parent / "_tmp_universe.json"
    result = subprocess.run(
        ["node", str(helper_path), str(data_js_path), str(tmp_json)],
        capture_output=True,
        check=True,
    )
    data = json.loads(tmp_json.read_text(encoding="utf-8"))
    tmp_json.unlink(missing_ok=True)
    return data


def merge_demo_with_real_prices(
    demo: list[dict],
    real_prices: list[dict],
) -> tuple[list[dict], list[str]]:
    """
    把 demo 陣列中每檔個股的 price 與 avg_volume 用 TWSE 真實資料覆蓋。
    回傳 (updated_demo, missing_codes)。
    """
    real_by_code = {p["code"]: p for p in real_prices}
    missing = []
    updated = []
    for d in demo:
        code = d["code"]
        if code in real_by_code:
            r = real_by_code[code]
            new_d = dict(d)
            new_d["price"] = r["price"]
            new_d["avg_volume"] = r["volume_lots"]
            new_d["date"] = r["date"]
            new_d["exchange"] = r["exchange"]
            new_d["_real_change"] = r["change"]
            updated.append(new_d)
        else:
            missing.append(code)
            updated.append(d)
    return updated, missing


def main():
    repo = Path(__file__).resolve().parents[2]
    data_js = repo / "data.js"
    prices_json = repo / "data" / "latest" / "prices.json"

    print(f"Loading {data_js.name} ...")
    demo = load_js_universe(data_js)
    print(f"  demo subset: {len(demo)} stocks")

    print(f"Loading {prices_json.name} ...")
    real_prices = json.loads(prices_json.read_text(encoding="utf-8"))
    print(f"  real prices: {len(real_prices)} stocks")

    updated, missing = merge_demo_with_real_prices(demo, real_prices)
    if missing:
        print(f"  WARNING: {len(missing)} demo stocks not in TWSE (likely TPEx / delisted): {missing[:5]}...")

    out = repo / "data" / "latest" / "demo_subset.json"
    out.write_text(
        json.dumps(updated, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"  Wrote {out} ({len(updated)} stocks)")

    universe = []
    for p in real_prices:
        universe.append({
            "code": p["code"],
            "name": p["name"],
            "exchange": p["exchange"],
            "price": p["price"],
            "change": p["change"],
            "volume_lots": p["volume_lots"],
            "turnover": p["turnover"],
            "date": p["date"],
        })
    out2 = repo / "data" / "latest" / "universe.json"
    out2.write_text(
        json.dumps(universe, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"  Wrote {out2} ({len(universe)} stocks)")

    return len(updated), missing


if __name__ == "__main__":
    n, missing = main()
    if missing:
        print()
        print(f"NOTE: {len(missing)} demo stocks not found in TWSE: {missing}")