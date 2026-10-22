"""
scripts/build_universe.py — 合併真實行情到示範股票集，並標註每個欄位的資料來源

資料流：
    backend/seed/demo_universe.json   （唯一真實來源：43 檔示範個股 + 示意 chip 值）
        +
    data/latest/prices.json            （TWSE 真實收盤）
    data/latest/tpex_prices.json       （TPEx 真實收盤）
        ↓
    data/latest/demo_subset.json       （含 _provenance 欄位來源標記）

設計要點（對應 docs/2026-10-21-專案體檢報告.md BUG-14 / BUG-17）：
- **不再讀自己的輸出**：v0.2.0 時 data.js 移除了 STOCK_UNIVERSE，
  導致本腳本變成「讀 demo_subset.json 再寫回 demo_subset.json」，
  示意值淪為無來源孤��。現已改為讀 backend/seed/。
- **每個欄位標明來源**：_provenance 標記 real / illustrative，
  前端據此判斷哪些因子可計算（避免真實 now 混著示意 history 產生假 delta）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# 統一 import 策略：把 repo root 加入 sys.path，
# 使 `python backend/scripts/x.py` 與 `python -m backend.scripts.x` 兩種呼叫都可用。
# （見 docs/2026-10-21-專案體檢報告.md BUG-12）
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.normalize import attach_provenance  # noqa: E402


REPO = Path(__file__).resolve().parents[2]
SEED = REPO / "backend" / "seed" / "demo_universe.json"
LATEST = REPO / "data" / "latest"


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
    return json.loads(p.read_text(encoding="utf-8"))


def merge_real_prices(
    seed_stocks: list[dict],
    twse_prices: list[dict],
    tpex_prices: list[dict],
) -> tuple[list[dict], list[str]]:
    """
    以真實收盤價覆寫示範股票。

    回傳 (merged_stocks, missing_codes)
    """
    real_by_code: dict[str, dict] = {}
    for p in twse_prices:
        real_by_code[p["code"]] = p
    for p in tpex_prices:
        real_by_code[p["code"]] = p

    merged = []
    missing = []
    for base in seed_stocks:
        s = dict(base)
        s.pop("_provenance", None)
        s.pop("_real_change", None)

        code = s["code"]
        if code in real_by_code:
            r = real_by_code[code]
            s["price"] = r["price"]
            s["avg_volume"] = r["volume_lots"]
            s["date"] = r.get("date", s.get("date"))
            s["exchange"] = r.get("exchange", s.get("exchange", "TWSE"))
            s["_real_change"] = r.get("change")
        else:
            missing.append(code)

        merged.append(s)
    return merged, missing


def main() -> int:
    print("Loading seed ...")
    seed = load_seed()
    print(f"  seed stocks: {len(seed)}")

    print("Loading data/latest/prices.json (TWSE) ...")
    twse = load_latest("prices.json")
    print(f"  TWSE prices: {len(twse)}")

    print("Loading data/latest/tpex_prices.json (TPEx) ...")
    tpex = load_latest("tpex_prices.json")
    print(f"  TPEx prices: {len(tpex)}")

    merged, missing = merge_real_prices(seed, twse, tpex)
    if missing:
        print(f"  WARNING: {len(missing)} stocks without real price (TPEx-only / delisted): {missing[:5]}")

    # 標註欄位來源：只有實際被真實資料覆寫的欄位才是 real
    real_fields = {"price", "avg_volume", "date", "exchange"}
    for s in merged:
        if s["code"] in {p["code"] for p in twse} | {p["code"] for p in tpex}:
            real_fields |= {"price", "avg_volume", "date", "exchange"}
    for s in merged:
        attach_provenance(s, real_fields)

    out = LATEST / "demo_subset.json"
    LATEST.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  Wrote {out} ({len(merged)} stocks)")

    # 摘要：哪些因子目前有真實資料
    from backend.normalize import FACTOR_INPUTS
    prov0 = merged[0].get("_provenance", {}) if merged else {}
    real_factors = [
        f for f, inputs in FACTOR_INPUTS.items()
        if inputs and all(prov0.get(i) == "real" for i in inputs)
    ]
    print(f"  Factors with fully-real inputs (sample stock): {real_factors or 'none yet'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())