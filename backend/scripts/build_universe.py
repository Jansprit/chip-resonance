"""
scripts/build_universe.py — 合併 TWSE + TPEx 真實價格到 demo 股票集 + 全市場

產出：
- data/latest/demo_subset.json    43 檔示範個股的完整資料（real price + illustrative chip data）
- data/latest/universe.json       TWSE + TPEx 全市場即時報價
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


HELPER_PATH = Path(__file__).parent / "_load_js_universe.js"


def load_js_universe(data_js_path: Path) -> list[dict]:
    """用 Node.js 載入 data.js 並輸出 STOCK_UNIVERSE 為 JSON。"""
    tmp_json = Path(__file__).parent / "_tmp_universe.json"
    result = subprocess.run(
        ["node", str(HELPER_PATH), str(data_js_path), str(tmp_json)],
        capture_output=True,
        check=True,
    )
    data = json.loads(tmp_json.read_text(encoding="utf-8"))
    tmp_json.unlink(missing_ok=True)
    return data


def load_latest_json(repo: Path, name: str) -> list[dict]:
    """從 data/latest/ 讀 JSON。"""
    p = repo / "data" / "latest" / name
    if not p.exists():
        return []
    return json.loads(p.read_text(encoding="utf-8"))


def merge_demo_with_real_prices(
    demo: list[dict],
    twse_prices: list[dict],
    tpex_prices: list[dict],
) -> tuple[list[dict], list[str]]:
    """
    把 demo 陣列中每檔個股的 price 與 avg_volume 用 TWSE/TPEx 真實資料覆蓋。
    """
    real_by_code: dict[str, dict] = {}
    for p in twse_prices:
        real_by_code[p["code"]] = p
    for p in tpex_prices:
        real_by_code[p["code"]] = p

    missing = []
    updated = []
    for d in demo:
        code = d["code"]
        if code in real_by_code:
            r = real_by_code[code]
            new_d = dict(d)
            new_d["price"] = r["price"]
            new_d["avg_volume"] = r["volume_lots"]
            new_d["date"] = r.get("date", new_d.get("date"))
            new_d["exchange"] = r.get("exchange", new_d.get("exchange", "TWSE"))
            new_d["_real_change"] = r.get("change")
            updated.append(new_d)
        else:
            missing.append(code)
            updated.append(d)
    return updated, missing


def main():
    repo = Path(__file__).resolve().parents[2]
    data_js = repo / "data.js"

    print(f"Loading {data_js.name} ...")
    demo = load_js_universe(data_js)
    print(f"  demo subset: {len(demo)} stocks")

    print("Loading data/latest/prices.json ...")
    twse_prices = load_latest_json(repo, "prices.json")
    print(f"  TWSE prices: {len(twse_prices)} stocks")

    print("Loading data/latest/tpex_prices.json ...")
    tpex_prices = load_latest_json(repo, "tpex_prices.json")
    print(f"  TPEx prices: {len(tpex_prices)} stocks")

    updated, missing = merge_demo_with_real_prices(demo, twse_prices, tpex_prices)
    if missing:
        print(f"  WARNING: {len(missing)} demo stocks not in TWSE/TPEx (delisted/special): {missing[:5]}...")

    out = repo / "data" / "latest" / "demo_subset.json"
    out.write_text(
        json.dumps(updated, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"  Wrote {out} ({len(updated)} stocks)")

    # Universe = TWSE + TPEx，標記 exchange
    universe = []
    for p in twse_prices:
        universe.append({
            "code": p["code"], "name": p["name"], "exchange": "TWSE",
            "price": p["price"], "change": p.get("change", 0),
            "volume_lots": p.get("volume_lots", 0),
            "turnover": p.get("turnover", 0), "date": p.get("date", ""),
        })
    for p in tpex_prices:
        universe.append({
            "code": p["code"], "name": p["name"], "exchange": "TPEx",
            "price": p["price"], "change": p.get("change", 0),
            "volume_lots": p.get("volume_lots", 0),
            "turnover": p.get("turnover", 0), "date": p.get("date", ""),
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
        print(f"NOTE: {len(missing)} demo stocks not found in TWSE/TPEx: {missing}")