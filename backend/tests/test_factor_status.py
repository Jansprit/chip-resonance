"""
test_factor_status.py — FACTOR_STATUS 必須與「實際可算的因子」一致

**為什麼需要這份測試？**
`data.js` 的 `FACTOR_STATUS` 是給使用者看的「哪些因子真的在跑真實資料」，
`factors.html` 直接把它畫出來。

v0.3.x 的這張表停留在 2026-10 的假設：
接上 Yahoo/TWSE 價格、FinMind 免費層、TWSE 融資券與殖利率之後，
它完全沒有更新 → **文件說 A、程式做 B**。

而且這類漂移很難靠眼睛發現：表格看起來合理，
只有拿實際可算性去比對才看得出來。

**等級的定義（快照無關）**：不能用「這次快照有幾檔算得出來」判定 ——
CI 每次抓的檔數不同，等級就會跟著跳動。
所以等級由「欄位供應狀態」推導（backend/scripts/build_universe.py 的
FIELD_SUPPLY 是單一真相來源）：

    ok      所有輸入都已接通
    partial 沒有「無來源」的缺口，但有尚未接上 / 需時間累積的輸入
    none    有輸入完全找不到來源 → 該因子在可預見的未來都算不了
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.scripts.build_universe import FIELD_SUPPLY, factor_supply_level

REPO = Path(__file__).resolve().parents[2]
DEMO = REPO / "data" / "latest" / "demo_subset.json"

NODE_JS = r"""
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const repoRoot = process.argv[2];
const dataJs = fs.readFileSync(path.join(repoRoot, 'data.js'), 'utf8');
const demo = JSON.parse(fs.readFileSync(path.join(repoRoot, 'data/latest/demo_subset.json'), 'utf8'));

const sandbox = {
  console: { log: () => {}, warn: () => {}, error: () => {} },
  window: {},
  document: { addEventListener: () => {} },
  fetch: () => Promise.reject(new Error('no network')),
  setTimeout, Math, JSON, Number, Object, Array, String, Boolean, Date,
};
sandbox.globalThis = sandbox;
const ctx = vm.createContext(sandbox);
vm.runInContext(dataJs, ctx, { filename: 'data.js' });

const out = sandbox.window.computeScores(demo);
const all = out.survivors.concat(out.noData);

const counts = {};
for (const fid of ['F1','F2','F3','F4','F5','F6','F8','F10']) {
  counts[fid] = all.filter(s => s.data_quality.real_factors.includes(fid)).length;
}
counts.F9 = all.filter(s => s.data_quality.f9_real === true).length;

console.log(JSON.stringify({
  counts,
  total: all.length,
  status: sandbox.window.FACTOR_STATUS,
  factorInputs: sandbox.window.FACTOR_INPUTS,
}));
"""


def _compute() -> dict:
    if not DEMO.exists():
        raise AssertionError(f"缺少 {DEMO}，無法驗證因子可用性")
    with tempfile.TemporaryDirectory() as tmp:
        script = Path(tmp) / "check.js"
        script.write_text(NODE_JS, encoding="utf-8")
        proc = subprocess.run(
            ["node", str(script), str(REPO)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
    assert proc.returncode == 0, f"node 執行失敗：{proc.stderr[:2000]}"
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_factor_status_levels_match_field_supply():
    """FACTOR_STATUS 的等級必須等於 FIELD_SUPPLY 推導出來的等級。"""
    info = _compute()
    status = info["status"]
    factor_inputs = info["factorInputs"]
    mismatches = []
    for fid, inputs in factor_inputs.items():
        expected = factor_supply_level({fid: inputs})
        actual = (status.get(fid) or {}).get("level")
        if actual != expected:
            mismatches.append(
                f"{fid}: FACTOR_STATUS 寫 {actual}，"
                f"但依欄位供應狀態應為 {expected}"
                f"（{[FIELD_SUPPLY.get(f, '?') for f in inputs]}）"
            )
    assert not mismatches, (
        "FACTOR_STATUS 與 FIELD_SUPPLY 不同步：\n" + "\n".join(mismatches)
    )


def test_no_factor_claims_ok_while_computing_zero_stocks():
    """
    宣稱 'ok' 卻一檔都算不出來 → 那是說謊。

    這個斷言穩定：只要宣稱 ok，就必須真的算得出來。
    """
    info = _compute()
    counts = info["counts"]
    status = info["status"]
    bad = []
    for fid, available in counts.items():
        level = (status.get(fid) or {}).get("level")
        if level == "ok" and available == 0:
            bad.append(f"{fid}: 宣稱 ok，但 0/{info['total']} 檔算得出來")
    assert not bad, "\n".join(bad)


def test_never_supply_fields_are_never_real_in_snapshot():
    """FIELD_SUPPLY 標成 'never' 的欄位，在實際資料裡不可出現為真實值。"""
    info = _compute()
    never_fields = [f for f, s in FIELD_SUPPLY.items() if s == "never"]
    assert never_fields, "FIELD_SUPPLY 應該要有 never 的欄位（F6 / F9 的缺口）"
    demo = json.loads(DEMO.read_text(encoding="utf-8"))
    offenders = []
    for stock in demo:
        prov = stock.get("_provenance") or {}
        for f in never_fields:
            if prov.get(f) == "real":
                offenders.append(f"{stock.get('code')}.{f}")
    assert not offenders, (
        f"這些欄位被標成 never 卻有真實值：{offenders[:10]}"
    )


def test_factor_status_covers_all_defined_factors():
    """每個有定義的因子都必須有狀態。"""
    info = _compute()
    for fid in info["factorInputs"]:
        assert fid in info["status"], f"FACTOR_STATUS 缺少 {fid}"


def test_factor_status_text_is_not_empty():
    """狀態說明不可是空白（使用者要靠它理解現況）。"""
    info = _compute()
    for fid, st in info["status"].items():
        assert st.get("text", "").strip(), f"{fid} 的狀態說明是空的"


def test_factor_status_does_not_claim_unconnected_sources():
    """
    狀態說明不可聲稱使用「其實沒在用」的來源。

    v0.3.x 說「已接通：玩股網日 K 線」，但 v0.4.0 的價格來源
    已經改成 Yahoo / TWSE（玩股網退為本機備援）。
    """
    info = _compute()
    for fid, st in info["status"].items():
        text = st.get("text", "")
        if st.get("level") == "ok":
            assert "玩股網日 K 線" not in text, (
                f"{fid} 宣稱使用玩股網日 K 線，但價格來源已改成 Yahoo / TWSE"
            )


def test_f2_status_discloses_the_proxy():
    """
    F2 目前用的是「產業 60 日報酬中位數」代理值，
    不是原始定義的「產業成分股大戶淨增持家數」——
    這一點必須在狀態說明裡揭露，否則使用者會以為原始定義已經實作。
    """
    info = _compute()
    text = info["status"]["F2"].get("text", "")
    assert "代理" in text or "原始定義" in text, (
        "F2 的狀態說明必須揭露「目前是代理值、原始定義待第二期」"
    )


if __name__ == "__main__":
    import sys as _sys
    from pathlib import Path as _Path

    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
    from backend.tests._runner import run_tests

    run_tests(globals(), "factor_status")
