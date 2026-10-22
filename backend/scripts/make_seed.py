"""
scripts/make_seed.py — 從現有 demo_subset.json 產生正式的 seed 檔（含 provenance）

用途：
- data.js 在 v0.2.0 移除了硬編碼 STOCK_UNIVERSE，導致 build_universe.py
  變成「讀自己的輸出再寫回去」，示意值淪為無來源孤兒。
- 本腳本把目前 demo_subset.json 的 43 檔固化成 backend/seed/demo_universe.json，
  明確標示每個欄位的來源（real=可由 pipeline 覆寫 / illustrative=示意值）。

一次性遷移用。產出後 seed 檔就是唯一真實來源。
"""

from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "data" / "latest" / "demo_subset.json"
DST = REPO / "backend" / "seed" / "demo_universe.json"

# 欄位 → 是否可由真實資料覆寫
REAL_OVERWRITABLE = {
    "price", "avg_volume", "date", "exchange",
    "pct_1000up_now", "pct_400up_now", "pct_600up_now", "pct_800up_now",
    "pct_1000up_w1", "pct_1000up_w2", "pct_1000up_w3", "pct_1000up_trend",
    "people_1000up_now", "people_400up_now", "date_chip",
    "margin_pct", "dt_ratio", "ret_60d", "drawdown_120d",
    "is_60d_high", "industry_ret_60d_med",
    "director_holding_change_3m", "director_pledge", "eps_q4",
    "div_years", "yield_now", "yield_5y_avg",
    "holder_cnt_change_8w", "avg_lot_change_8w",
    "pct_400up_52w_high", "crash_60d",
}

# 每個因子的必要輸入欄位（用於判斷該因子是否可計算）
FACTOR_INPUTS = {
    "F1":  ["pct_1000up_now", "pct_1000up_w3"],
    "F2":  ["industry_ret_60d_med"],
    "F3":  ["director_holding_change_3m", "ret_60d", "industry_ret_60d_med"],
    "F4":  ["pct_400up_52w_high"],
    "F5":  ["div_years", "yield_now", "yield_5y_avg"],
    "F6":  ["holder_cnt_change_8w", "avg_lot_change_8w"],
    "F8":  ["drawdown_120d", "pct_1000up_now"],
    "F9":  ["is_60d_high", "pct_1000up_now", "pct_1000up_w1", "pct_1000up_w3",
             "margin_pct", "dt_ratio"],
    "F10": ["crash_60d", "pct_1000up_trend"],
}


def main() -> None:
    data = json.loads(SRC.read_text(encoding="utf-8"))
    out = []
    for stock in data:
        s = dict(stock)
        s.pop("_provenance", None)
        s.pop("_real_change", None)
        out.append(s)

    payload = {
        "_comment": (
            "Demo universe seed — 43 檔示範個股。"
            "chip 相關欄位為示意值（illustrative），僅供 UI 與評分流程測試；"
            "pipeline 會以真實資料覆寫標記為 real 的欄位。"
            "欄位來源定義見 backend/normalize.py 的 FIELD_PROVENANCE。"
        ),
        "_field_policy": {
            "real_overwritable": sorted(REAL_OVERWRITABLE),
            "factor_inputs": FACTOR_INPUTS,
        },
        "stocks": out,
    }

    DST.parent.mkdir(parents=True, exist_ok=True)
    DST.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Wrote {DST} ({len(out)} stocks, {DST.stat().st_size} bytes)")


if __name__ == "__main__":
    main()