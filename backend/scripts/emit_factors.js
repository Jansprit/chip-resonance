#!/usr/bin/env node
/**
 * backend/scripts/emit_factors.js — 產生 point-in-time 因子庫
 *
 * 對應原始需求文件（tabbit_神秘金字塔網站_財富密碼揭密.md §七）：
 *     log_to_backtest_db(date, F, score)
 *
 * **為什麼用 Node 而不是 Python 重寫一份因子計算？**
 * 因為那會產生「兩份因子實作」，而本專案這三個月最大的浪費
 * 就是同一件事有兩個真相來源（評分引擎 vs 合併層）。
 * 這裡直接載入 data.js（唯一的因子實作），把每檔股票的
 * 因子原值 + 可用性 + 當時公布日寫成 data/latest/factors.json。
 *
 * 輸出格式：
 * {
 *   "as_of": "2026-10-24",
 *   "published_at": "2026-10-29",     // T+3 交易日（嚴守資料可得性）
 *   "mode": "point_in_time",
 *   "rows": [
 *     {"code": "2330", "price": 2385.0, "score": 61.2, "tier": "B",
 *      "factors": {"F1": 70, "F2": 65.3, ...},
 *      "available": {"F1": false, "F2": true, ...},
 *      "provenance": {...}}
 *   ]
 * }
 *
 * 用法：node backend/scripts/emit_factors.js [demo_subset路徑] [輸出路徑] [歷史檔路徑]
 *
 * 產出兩個檔案：
 *   data/latest/factors.json          — 當前這一份截面
 *   data/latest/factors_history.jsonl  — 逐週累積的 point-in-time 歷史（回測的唯一資料源）
 */
'use strict';

const fs = require('fs');
const path = require('path');
const vm = require('vm');

const REPO = path.resolve(__dirname, '..', '..');
const SRC = path.join(REPO, 'data.js');
const DEFAULT_INPUT = path.join(REPO, 'data', 'latest', 'demo_subset.json');
const DEFAULT_OUTPUT = path.join(REPO, 'data', 'latest', 'factors.json');
const DEFAULT_HISTORY = path.join(REPO, 'data', 'latest', 'factors_history.jsonl');

/** T+3 交易日：as_of 往後加 3 個工作天（跳過週六日）。 */
function addBusinessDays(isoDate, days) {
  const d = new Date(isoDate + 'T00:00:00+08:00');
  let added = 0;
  while (added < days) {
    d.setDate(d.getDate() + 1);
    const wd = d.getDay();
    if (wd !== 0 && wd !== 6) added += 1;
  }
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

/**
 * 把快照累積進 point-in-time 歷史檔（JSONL，一行一份快照）。
 *
 * 為什麼需要這個檔案？
 *   回測要的是「每一週當時可得」的因子值。
 *   單一 factors.json 只是「現在這一刻」的截面，
 *   拿它回測就是用未來資料回推過去 —— 嚴重的前視偏誤。
 *   因子庫必須**逐週累積**，累積夠 8~12 週才有意義。
 *
 * 去重規則：同一個 as_of 只保留最新一版（資料被修正時覆蓋舊的），
 *   否則同一週重跑會灌水樣本數，讓統計看起來比實際可靠。
 */
function appendHistory(historyPath, payload) {
  const byAsOf = new Map();
  if (fs.existsSync(historyPath)) {
    for (const line of fs.readFileSync(historyPath, 'utf8').split(/\r?\n/)) {
      const trimmed = line.trim();
      if (!trimmed) continue;
      try {
        const snap = JSON.parse(trimmed);
        if (snap && snap.as_of) byAsOf.set(snap.as_of, snap);
      } catch (err) {
        // 壞掉的行直接略過 —— 歷史檔只該讓流程往前跑，不該讓它整個爆掉
        console.warn(`[emit_factors] 略過一筆無法解析的歷史行：${trimmed.slice(0, 60)}`);
      }
    }
  }
  byAsOf.set(payload.as_of, payload);
  const sorted = [...byAsOf.values()].sort((a, b) => (a.as_of < b.as_of ? -1 : a.as_of > b.as_of ? 1 : 0));
  fs.mkdirSync(path.dirname(historyPath), { recursive: true });
  fs.writeFileSync(
    historyPath,
    sorted.map((s) => JSON.stringify(s)).join('\n') + '\n',
    'utf8'
  );
  return sorted.length;
}

function main() {
  const input = process.argv[2] || DEFAULT_INPUT;
  const output = process.argv[3] || DEFAULT_OUTPUT;
  const history = process.argv[4] || DEFAULT_HISTORY;

  if (!fs.existsSync(input)) {
    console.error(`[emit_factors] 找不到 ${input}，略過`);
    process.exit(0);
  }

  const sandbox = {
    console,
    window: {},
    document: { addEventListener: () => {} },
    fetch: () => Promise.reject(new Error('no network in emit_factors')),
    setTimeout, Math, JSON, Number, Object, Array, String, Boolean, Date,
  };
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(SRC, 'utf8'), sandbox, { filename: 'data.js' });

  const { computeScores, FACTOR_INPUTS, POSITIVE_FACTORS } = sandbox.window;
  if (!computeScores) {
    console.error('[emit_factors] data.js 沒有 export computeScores');
    process.exit(1);
  }

  const stocks = JSON.parse(fs.readFileSync(input, 'utf8'));
  const result = computeScores(stocks);

  // as_of：取資料中最新的日期欄位（date / date_chip / last_date）
  let asOf = null;
  for (const s of stocks) {
    for (const k of ['date', 'date_chip', 'last_date']) {
      if (s && s[k] && typeof s[k] === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(s[k])) {
        if (!asOf || s[k] > asOf) asOf = s[k];
      }
    }
  }
  const today = new Date(Date.now() + 8 * 3600 * 1000).toISOString().slice(0, 10);
  asOf = asOf || today;
  const publishedAt = addBusinessDays(asOf, 3);

  const rows = (result.survivors || []).concat(result.noData || []).map((s) => {
    const factors = {};
    const available = {};
    for (const fid of POSITIVE_FACTORS) {
      const inputs = FACTOR_INPUTS[fid] || [];
      const ok = inputs.length > 0 && inputs.every((k) => {
        const prov = (s._provenance || {})[k];
        return prov === 'real';
      });
      available[fid] = ok;
      factors[fid] = ok ? Number(s[fid]) : null;
    }
    return {
      code: s.code,
      name: s.name,
      price: s.price,
      score: s.score,
      tier: s.tier,
      factors,
      available,
      provenance: s._provenance || {},
    };
  });

  const payload = {
    as_of: asOf,
    published_at: publishedAt,
    mode: 'point_in_time',
    scoring_mode: result.mode,
    coverage: result.coverage || null,
    factor_count: POSITIVE_FACTORS.length,
    rows,
  };

  fs.mkdirSync(path.dirname(output), { recursive: true });
  fs.writeFileSync(output, JSON.stringify(payload, null, 2), 'utf8');
  const historyCount = appendHistory(history, payload);
  console.log(
    `[emit_factors] ${output}  as_of=${asOf} published_at=${publishedAt} ` +
    `rows=${rows.length} mode=${result.mode} history=${historyCount}`
  );
}

main();
