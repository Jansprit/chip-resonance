"""
test_scoring_provenance.py — 回歸測試：NaN 防護 + provenance 感知 + 權重重新分配

涵蓋 docs/2026-10-21-專案體檢報告.md 的 BUG-01 / BUG-14 / BUG-15。

測試方式：以 Node.js 執行 data.js 的實際邏輯（而非重寫一份 JS），
確保測的是「會被部署的那份程式碼」。

執行：python backend/tests/test_scoring_provenance.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# 測試用 JS：以 vm 載入 data.js 的實際函式
TEST_JS = r"""
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const repoRoot = process.argv[2];
const dataJs = fs.readFileSync(path.join(repoRoot, 'data.js'), 'utf8');

// 建立 sandbox，模擬瀏覽器全域
const sandbox = {
  console,
  window: {},
  document: { addEventListener: () => {} },
  fetch: () => Promise.reject(new Error('no network in test')),
  setTimeout,
  Math,
  JSON,
  Number,
  Object,
  Array,
  String,
  Boolean,
  Date,
};
sandbox.globalThis = sandbox;
vm.createContext(sandbox);

// 執行 data.js（其頂端有 window.X = ... 賦值，window 已在 sandbox 中）
vm.runInContext(dataJs, sandbox, { filename: 'data.js' });

const computeScores = sandbox.window.computeScores;
const FACTOR_INPUTS = sandbox.window.FACTOR_INPUTS;
const HARD_FILTERS = sandbox.window.HARD_FILTERS;

function mkStock(overrides) {
  const s = Object.assign({
    code: 'TEST', name: '測試', industry: 'SEMI', price: 100, avg_volume: 1000,
    director_pleast: 0, director_pledge: 0, eps_q4: 5, list_year: 10, warning: false,
    margin_pct: 10, dt_ratio: 15,
    pct_1000up_now: 50, pct_1000up_w1: 50, pct_1000up_w2: 50, pct_1000up_w3: 50,
    pct_400up: 50, pct_400up_52w_high: false,
    holder_cnt_change_8w: 0, avg_lot_change_8w: 0,
    drawdown_120d: 0, ret_60d: 0, industry_ret_60d_med: 0,
    director_holding_change_3m: 0,
    div_years: 10, yield_now: 3, yield_5y_avg: 3,
    crash_60d: false, pct_1000up_trend: '=', is_60d_high: false,
    _provenance: {},
  }, overrides);
  // 預設所有欄位為 illustrative
  if (!s._provenance || Object.keys(s._provenance).length === 0) {
    s._provenance = {};
    Object.keys(s).forEach(k => {
      if (!k.startsWith('_')) s._provenance[k] = 'illustrative';
    });
  }
  return s;
}

const results = {};

/* ---- Test 1: 缺少欄位時不得產生 NaN ---- */
{
  const s = mkStock({ code: 'NAN1' });
  delete s.pct_1000up_w3;          // 缺欄位
  s._provenance.pct_1000up_w3 = 'illustrative';
  const out = computeScores([s]);
  const r = out.survivors[0];
  results.t1_no_nan = Number.isFinite(r.score);
  results.t1_score = r.score;
  results.t1_f1 = r.F1;
}

/* ---- Test 2: 欄位值為 undefined 時不得產生 NaN ---- */
{
  const s = mkStock({ code: 'NAN2', pct_1000up_w3: undefined });
  const out = computeScores([s]);
  const r = out.survivors[0];
  results.t2_no_nan = Number.isFinite(r.score);
  results.t2_f1 = r.F1;
}

/* ---- Test 3: 混合真實 now 與示意 w3 → F1 必須判定為不可用 ---- */
{
  const s = mkStock({ code: 'MIX1', pct_1000up_now: 84.7, pct_1000up_w3: 66.8 });
  s._provenance.pct_1000up_now = 'real';
  s._provenance.pct_1000up_w3 = 'illustrative';
  const out = computeScores([s]);
  const r = out.survivors[0];
  results.t3_f1_not_available = r.data_quality.illustrative_factors.includes('F1');
  results.t3_f1_in_real = r.data_quality.real_factors.includes('F1');
}

/* ---- Test 4: 全部輸入皆真實 → F1 可用 ----
   F1 的輸入集合 2026-10 起改為 4 個欄位（now/w1/w2/w3），
   因為原始定義要求判斷「連續 3 週增加」。 */
{
  const s = mkStock({ code: 'REAL1', pct_1000up_now: 84.7, pct_1000up_w1: 80, pct_1000up_w2: 74, pct_1000up_w3: 66.8 });
  s._provenance.pct_1000up_now = 'real';
  s._provenance.pct_1000up_w1 = 'real';
  s._provenance.pct_1000up_w2 = 'real';
  s._provenance.pct_1000up_w3 = 'real';
  const out = computeScores([s]);
  const r = out.survivors[0];
  results.t4_f1_available = r.data_quality.real_factors.includes('F1');
  results.t4_f1_value = r.F1;
}

/* ---- Test 5: 部分真實 → partial 模式，沒有真實因子的股票不參與排名 ----
   A 的 F1 輸入全真實，B 的 F1 混合真實+示意（因此 B 完全沒有真實因子）。
   2026-10 語意修正：舊版只要「有一檔」有真實因子就宣稱 strict，
   會讓 43 檔裡只有 1 檔有真實資料時整個版面仍顯示「實戰模式」。 */
{
  const a = mkStock({ code: 'A', pct_1000up_now: 90, pct_1000up_w1: 84, pct_1000up_w2: 78, pct_1000up_w3: 70 });
  ['pct_1000up_now', 'pct_1000up_w1', 'pct_1000up_w2', 'pct_1000up_w3']
    .forEach(k => { a._provenance[k] = 'real'; });
  const b = mkStock({ code: 'B', pct_1000up_now: 20, pct_1000up_w1: 20, pct_1000up_w2: 20, pct_1000up_w3: 60 });
  b._provenance.pct_1000up_now = 'real';
  b._provenance.pct_1000up_w3 = 'illustrative';
  const out = computeScores([a, b]);
  const ra = out.survivors.find(x => x.code === 'A');
  const rb = (out.noData || []).find(x => x.code === 'B');
  results.t5_mode = out.mode;
  results.t5_a_score = ra ? ra.score : null;
  results.t5_b_score = rb ? rb.score : null;
  results.t5_a_weight = ra ? ra.usedWeight : null;
  results.t5_b_weight = rb ? rb.usedWeight : null;
  results.t5_a_f1_real = ra ? ra.data_quality.real_factors.includes('F1') : null;
  results.t5_b_f1_real = rb ? rb.data_quality.real_factors.includes('F1') : null;
  results.t5_b_excluded = !out.survivors.some(x => x.code === 'B');
  results.t5_coverage = out.coverage;
  results.t5_all_finite = out.survivors.every(x => Number.isFinite(x.score));
}

/* ---- Test 5c: 每檔都有真實因子 → strict 模式 ---- */
{
  const a = mkStock({ code: 'SA', pct_1000up_now: 90, pct_1000up_w1: 84, pct_1000up_w2: 78, pct_1000up_w3: 70 });
  ['pct_1000up_now', 'pct_1000up_w1', 'pct_1000up_w2', 'pct_1000up_w3']
    .forEach(k => { a._provenance[k] = 'real'; });
  const b = mkStock({ code: 'SB', pct_1000up_now: 20, pct_1000up_w1: 20, pct_1000up_w2: 20, pct_1000up_w3: 60 });
  ['pct_1000up_now', 'pct_1000up_w1', 'pct_1000up_w2', 'pct_1000up_w3']
    .forEach(k => { b._provenance[k] = 'real'; });
  const out = computeScores([a, b]);
  results.t5c_mode = out.mode;
  results.t5c_count = out.survivors.length;
  results.t5c_no_data = (out.noData || []).length;
  results.t5c_all_finite = out.survivors.every(x => Number.isFinite(x.score));
}

/* ---- Test 5b: demo 模式（無任何真實因子）→ 全部因子照算，但標記 mode=demo ---- */
{
  const s = mkStock({ code: 'D1', pct_1000up_now: 90, pct_1000up_w3: 70 });
  const out = computeScores([s]);
  const r = out.survivors[0];
  results.t5b_mode = out.mode;
  results.t5b_f1_in_real = r.data_quality.real_factors.includes('F1');
  results.t5b_reliable = r.data_quality.reliable;
  results.t5b_finite = Number.isFinite(r.score);
}

/* ---- Test 5d: F1 必須符合原始定義「連續 ≥3 週增加，且累計增幅 ≥1%」 ----
   原始需求文件（tabbit_神秘金字塔網站_財富密碼揭密.md §四）：
   「1000 張以上大戶持股比例連續 ≥3 週增加，且累計增幅 ≥1%」
   舊版只算 now - w3 的淨差，完全沒有判斷「連續」——
   那是不同的因子。 */
{
  function realF1(over) {
    const s = mkStock(Object.assign({
      code: 'F1X', pct_1000up_w3: 60, pct_1000up_w2: 61,
      pct_1000up_w1: 62, pct_1000up_now: 63,
    }, over));
    ['pct_1000up_now', 'pct_1000up_w1', 'pct_1000up_w2', 'pct_1000up_w3']
      .forEach(k => { s._provenance[k] = 'real'; });
    return s;
  }
  // 連續 3 週增加、累計增幅 3% → 滿分
  const up = computeScores([realF1({ code: 'F1UP' })]).survivors[0];
  // 連續 3 週增加但累計增幅只有 0.3% → 不到滿分
  const small = computeScores([realF1({
    code: 'F1SM', pct_1000up_w3: 60, pct_1000up_w2: 60.1,
    pct_1000up_w1: 60.2, pct_1000up_now: 60.3,
  })]).survivors[0];
  // 中間一週下降（非連續）→ 明顯較低
  const broken = computeScores([realF1({
    code: 'F1BR', pct_1000up_w3: 60, pct_1000up_w2: 61,
    pct_1000up_w1: 59, pct_1000up_now: 63,
  })]).survivors[0];
  results.t5d_consecutive_full = up.F1;
  results.t5d_small_gain = small.F1;
  results.t5d_broken = broken.F1;
  results.t5d_f1_inputs = FACTOR_INPUTS.F1.slice();
  results.t5d_up_finite = Number.isFinite(up.F1);
}

/* ---- Test 6: 全部個股都無可用因子 → 分數為中性 50，不 NaN ---- */
{
  const stocks = [mkStock({ code: 'N1' }), mkStock({ code: 'N2' })];
  const out = computeScores(stocks);
  results.t6_all_finite = out.survivors.every(x => Number.isFinite(x.score));
  results.t6_all_50 = out.survivors.every(x => x.score === 50);
  results.t6_none_reliable = out.survivors.every(x => x.data_quality.reliable === false);
}

/* ---- Test 7: 帶真實 _provenance 的完整 demo_subset 不產生 NaN ---- */
{
  const demoPath = path.join(repoRoot, 'data', 'latest', 'demo_subset.json');
  if (fs.existsSync(demoPath)) {
    const demo = JSON.parse(fs.readFileSync(demoPath, 'utf8'));
    const out = computeScores(demo);
    results.t7_count = out.survivors.length;
    results.t7_all_finite = out.survivors.every(x => Number.isFinite(x.score));
    results.t7_tier_a = out.survivors.filter(x => x.tier === 'A').length;
    results.t7_rejected = out.rejected.length;
    results.t7_has_provenance = demo[0] && !!demo[0]._provenance;
    results.t7_mode = out.mode;
    results.t7_real_factor_counts = out.survivors.map(x => x.data_quality.real_factors.length);
  } else {
    results.t7_skipped = true;
  }
}

console.log(JSON.stringify(results));
"""


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        script = Path(tmp) / "test.js"
        script.write_text(TEST_JS, encoding="utf-8")

        result = subprocess.run(
            ["node", str(script), str(REPO)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print("Node execution FAILED:")
            print(result.stderr[:3000])
            return 1

        try:
            r = json.loads(result.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            print("Could not parse result:")
            print(result.stdout[:3000])
            print(result.stderr[:2000])
            return 1

    failures: list[str] = []

    def check(name: str, cond: bool, detail: str = "") -> None:
        if cond:
            print(f"PASS: {name}")
        else:
            print(f"FAIL: {name}  {detail}")
            failures.append(name)

    # T1
    check("t1_no_nan", r.get("t1_no_nan") is True,
          f"score={r.get('t1_score')}")
    check("t1_f1_finite", isinstance(r.get("t1_f1"), (int, float))
          and r["t1_f1"] == r["t1_f1"], f"F1={r.get('t1_f1')}")

    # T2
    check("t2_no_nan", r.get("t2_no_nan") is True,
          f"score={r.get('t2_score')}")

    # T3 — 混合來源 → F1 不可用
    check("t3_f1_not_available", r.get("t3_f1_not_available") is True,
          f"real={r.get('t3_f1_in_real')}")
    check("t3_f1_not_in_real", r.get("t3_f1_in_real") is False)

    # T4 — 全真實 → F1 可用
    check("t4_f1_available", r.get("t4_f1_available") is True,
          f"F1={r.get('t4_f1_value')}")

    # T5 — 部分真實 → partial 模式，沒有真實因子的股票被排除
    check("t5_mode_partial", r.get("t5_mode") == "partial",
          f"mode={r.get('t5_mode')}")
    check("t5_a_f1_real", r.get("t5_a_f1_real") is True)
    check("t5_b_f1_not_real", r.get("t5_b_f1_real") is False,
          f"b_f1_real={r.get('t5_b_f1_real')}")
    check("t5_b_excluded_from_ranking", r.get("t5_b_excluded") is True)
    check("t5_all_finite", r.get("t5_all_finite") is True)
    check("t5_scores_in_range",
          0 <= (r.get("t5_a_score") or -1) <= 100 and 0 <= (r.get("t5_b_score") or -1) <= 100,
          f"a={r.get('t5_a_score')} b={r.get('t5_b_score')}")
    cov = r.get("t5_coverage") or {}
    check("t5_coverage_counted",
          cov.get("without_real_factors") == 1 and cov.get("with_real_factors") == 1,
          f"coverage={cov}")

    # T5c — 每檔都有真實因子 → strict
    check("t5c_mode_strict", r.get("t5c_mode") == "strict",
          f"mode={r.get('t5c_mode')}")
    check("t5c_count", r.get("t5c_count") == 2, f"count={r.get('t5c_count')}")
    check("t5c_no_data_zero", r.get("t5c_no_data") == 0)
    check("t5c_all_finite", r.get("t5c_all_finite") is True)

    # T5d — F1 對齊原始定義（連續 ≥3 週增加 + 累計增幅 ≥1%）
    check("t5d_finite", r.get("t5d_up_finite") is True)
    check("t5d_requires_w1_w2",
          r.get("t5d_f1_inputs") == ["pct_1000up_now", "pct_1000up_w1",
                                     "pct_1000up_w2", "pct_1000up_w3"],
          f"inputs={r.get('t5d_f1_inputs')}")
    check("t5d_consecutive_full_score",
          (r.get("t5d_consecutive_full") or 0) >= 95,
          f"F1={r.get('t5d_consecutive_full')}")
    check("t5d_broken_lower_than_consecutive",
          (r.get("t5d_broken") or 0) < (r.get("t5d_consecutive_full") or 0),
          f"broken={r.get('t5d_broken')} full={r.get('t5d_consecutive_full')}")
    check("t5d_small_gain_below_full",
          (r.get("t5d_small_gain") or 0) < (r.get("t5d_consecutive_full") or 0),
          f"small={r.get('t5d_small_gain')} full={r.get('t5d_consecutive_full')}")

    # T5b — demo 模式
    check("t5b_mode_demo", r.get("t5b_mode") == "demo",
          f"mode={r.get('t5b_mode')}")
    check("t5b_f1_not_in_real", r.get("t5b_f1_in_real") is False)
    check("t5b_not_reliable", r.get("t5b_reliable") is False)
    check("t5b_finite", r.get("t5b_finite") is True)

    # T6 — 全無可用因子
    check("t6_all_finite", r.get("t6_all_finite") is True)
    check("t6_all_50", r.get("t6_all_50") is True)
    check("t6_none_reliable", r.get("t6_none_reliable") is True)

    # T7 — 真實 demo_subset
    if not r.get("t7_skipped"):
        check("t7_has_provenance", r.get("t7_has_provenance") is True)
        check("t7_all_finite", r.get("t7_all_finite") is True,
              f"tier_a={r.get('t7_tier_a')} rejected={r.get('t7_rejected')}")
        check("t7_mode_known", r.get("t7_mode") in ("demo", "strict", "partial"),
              f"mode={r.get('t7_mode')}")
        # 至少要能產生分層（demo 模式下應有 A 級示範股）
        if r.get("t7_mode") == "demo":
            check("t7_tier_a_positive", (r.get("t7_tier_a") or 0) > 0,
                  f"tier_a={r.get('t7_tier_a')}")

    print()
    if failures:
        print(f"{len(failures)} test(s) FAILED: {failures}")
        return 1
    print("All scoring provenance tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())