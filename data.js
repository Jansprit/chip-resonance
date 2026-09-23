// =============================================================
// 籌碼共振選股系統 — 資料載入 + 評分引擎
//
// 設計：
// - 預設載入 /data/latest/demo_subset.json（GitHub Pages 服務的真實快照）
// - 若 fetch 失敗（例如本地無 server），fallback 到 MINIMAL_FALLBACK 內建資料
// - 評分引擎 computeScores() 維持向後相容（不論 STOCK_UNIVERSE 來自哪裡都跑同一套）
//
// 升級歷程：
// - v1 (2026-09-20) — 純示意 43 檔硬編碼
// - v2 (2026-09-21) — 改為 async loader + 真實 TWSE 價格覆寫
// =============================================================

const INDUSTRY_LIST = [
  { code: 'SEMI',   name: '半導體',         emoji: '🔌' },
  { code: 'FIN',    name: '金融保險',       emoji: '🏦' },
  { code: 'PCB',    name: 'PCB／載板',      emoji: '🧩' },
  { code: 'BIO',    name: '生技醫療',       emoji: '💊' },
  { code: 'SHIP',   name: '航運／物流',     emoji: '🚢' },
  { code: 'AUTO',   name: '汽車／零件',     emoji: '🚗' },
  { code: 'PLAS',   name: '塑膠／化工',     emoji: '🛢️' },
  { code: 'FOOD',   name: '食品／農林',     emoji: '🌾' },
  { code: 'ELEC',   name: '電子零組件',     emoji: '⚙️' }
];

// 9 因子權重（依需求文件）
const FACTOR_WEIGHTS = {
  F1:  20,  // 大股東連續加碼
  F2:  10,  // 產業輪動
  F3:  15,  // 董監加碼價格落後
  F4:  10,  // 集中度突破
  F5:  10,  // 股利穩定
  F6:  15,  // 散戶退場主力接手
  F8:  10,  // 回調籌碼守穩
  F10:  5,  // 利空籌碼修復
  F9: -20   // 價籌背離懲罰（封頂）
};

// 9 因子定義（給前端展示）
const FACTOR_DEFINITIONS = [
  {
    code: 'F1', name: '大股東連續加碼', weight: 20, direction: 'plus',
    desc: '1000 張以上大戶持股比例連續 ≥3 週增加，且累計增幅 ≥1%。',
    formula: 'consecutive_increase(pct_1000up, weeks=3) ≥ 1.0',
    dataSource: '神秘金字塔 + 集保中心',
    frequency: '週'
  },
  {
    code: 'F2', name: '產業輪動', weight: 10, direction: 'plus',
    desc: '個股所屬 CID 的全體成分股「大戶淨增持家數 − 淨減持家數」之 4 週均值，取全市場前 30% 的產業。',
    formula: 'industry_flow_rank(holders, by="CID", window=4) in top 30%',
    dataSource: '金字塔 CID 參數 + 集保',
    frequency: '週'
  },
  {
    code: 'F3', name: '董監加碼價格落後', weight: 15, direction: 'plus',
    desc: '董監持股近 3 個月增加 >0.5%，且個股 60 日報酬率落後同產業中位數。',
    formula: 'director_change_3m > 0.5% AND ret_60d < industry_median',
    dataSource: 'Goodinfo / 公開資訊觀測站',
    frequency: '月'
  },
  {
    code: 'F4', name: '集中度突破', weight: 10, direction: 'plus',
    desc: '400 張以上比例創 52 週新高，且首次突破（非連續第 N 週新高，避免追高）。',
    formula: 'pct_400up >= 52w_high AND is_first_breakout',
    dataSource: '集保中心',
    frequency: '週'
  },
  {
    code: 'F5', name: '股利穩定', weight: 10, direction: 'plus',
    desc: '連續配息 ≥5 年，目前殖利率高於自身 5 年均值。',
    formula: 'div_years >= 5 AND yield_now > yield_5y_avg',
    dataSource: '神秘金字塔股利模組 + Goodinfo',
    frequency: '季/年'
  },
  {
    code: 'F6', name: '散戶退場主力接手', weight: 15, direction: 'plus',
    desc: '股東總人數 8 週變化率 <-5%，且平均持有張數 8 週變化率 >+5%，兩者同向才給分。',
    formula: 'holder_cnt_8w < -5% AND avg_lot_8w > +5%',
    dataSource: '集保分散表',
    frequency: '週'
  },
  {
    code: 'F8', name: '回調籌碼守穩', weight: 10, direction: 'plus',
    desc: '股價自 120 日高點回撤 10%~25%，但期間大戶持股比例變化 ≥0。',
    formula: '-25% <= drawdown_120d <= -10% AND Δpct_1000up >= 0',
    dataSource: 'TWSE/TPEx + 集保',
    frequency: '日'
  },
  {
    code: 'F10', name: '利空籌碼修復', weight: 5, direction: 'plus',
    desc: '60 日內曾單週跌幅 >15%，且最近 2 週大戶比例由減轉平/增。',
    formula: 'crash_60d AND pct_1000up_trend in {=, +}',
    dataSource: 'TWSE/TPEx + 集保',
    frequency: '事件驅動'
  },
  {
    code: 'F9', name: '價籌背離懲罰', weight: -20, direction: 'minus',
    desc: '股價創 60 日新高但大戶比例連 2 週下降，或當沖比 >40%、融資使用率 >70%（觸發任一即扣分，多重觸發累計封頂 -20）。',
    formula: '(is_60d_high AND Δpct_1000up_2w < 0) OR dt_ratio > 40% OR margin_pct > 70%',
    dataSource: '證交所 + Goodinfo + 集保',
    frequency: '日'
  }
];

// 硬性過濾條件
const HARD_FILTERS = [
  { id: 'volume', name: '日均成交量不足', desc: '20 日均量 < 500 張', check: s => s.avg_volume < 500 },
  { id: 'pledge', name: '董監質押過高',     desc: '董監質押率 > 50%',   check: s => s.director_pledge > 50 },
  { id: 'eps',    name: '累計虧損',         desc: '近四季累計 EPS < 0', check: s => s.eps_q4 < 0 },
  { id: 'warn',   name: '警示／全額交割／暫停', desc: '屬於警示股系列', check: s => s.warning === true },
  { id: 'list',   name: '上市未滿 2 年',     desc: 'list_year < 2',       check: s => s.list_year < 2 },
  { id: 'price',  name: '雞蛋水餃股',       desc: '股價 < 10 元',        check: s => s.price < 10 }
];

// =============================================================
// Async loader：優先從 /data/latest/demo_subset.json 載入真實資料
// =============================================================

let DATA_META = null;
let DATA_LOADED = false;
let DATA_LOAD_ERROR = null;

async function fetchJSON(url) {
  const resp = await fetch(url, { cache: 'no-store' });
  if (!resp.ok) throw new Error(`HTTP ${resp.status} fetching ${url}`);
  return await resp.json();
}

async function loadRealData() {
  // 並行抓 meta + demo_subset + tdcc_chip，timeout 15s
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 15000);
  try {
    const [meta, demo, tdcc] = await Promise.all([
      fetchJSON('data/latest/meta.json'),
      fetchJSON('data/latest/demo_subset.json'),
      fetchJSON('data/latest/tdcc_chip.json').catch(() => null),
    ]);
    DATA_META = meta;
    DATA_LOADED = true;
    // 如果 tdcc_chip 有資料，合併進 demo_subset
    if (tdcc && Array.isArray(tdcc)) {
      const tdcc_by_code = {};
      for (const r of tdcc) tdcc_by_code[r.code] = r;
      for (const s of demo) {
        const t = tdcc_by_code[s.code];
        if (t) {
          s.pct_1000up_now = t.pct_1000up_now ?? s.pct_1000up_now;
          s.pct_400up_now = t.pct_400up_now ?? s.pct_400up_now;
          s.pct_600up_now = t.pct_600up_now;
          s.pct_800up_now = t.pct_800up_now;
          s.pct_1000up_trend = t.pct_1000up_trend ?? s.pct_1000up_trend;
          s.pct_1000up_w1 = t.pct_1000up_w1;
          s.pct_1000up_w2 = t.pct_1000up_w2;
          s.pct_1000up_w3 = t.pct_1000up_w3;
          s.people_1000up_now = t.people_1000up_now;
          s.people_400up_now = t.people_400up_now;
          s.date_chip = t.date;
        }
      }
    }
    return demo;
  } catch (err) {
    DATA_LOAD_ERROR = err.message || String(err);
    return null;
  } finally {
    clearTimeout(timeout);
  }
}

// =============================================================
// 評分引擎（純函式，接受任何 universe）
// =============================================================

function computeScores(universe) {
  // 1. 硬性過濾
  const survivors = [];
  const rejected = [];
  universe.forEach(s => {
    const reasons = [];
    HARD_FILTERS.forEach(f => {
      if (f.check(s)) reasons.push(f.name);
    });
    if (reasons.length === 0) {
      survivors.push({ ...s, _filtered: false, _reasons: [] });
    } else {
      rejected.push({ ...s, _filtered: true, _reasons: reasons });
    }
  });

  // 2. 因子計算
  const factorValues = survivors.map(s => {
    const pct_1000up_delta_3w = s.pct_1000up_now - s.pct_1000up_w3;
    const pct_1000up_delta_2w = s.pct_1000up_w1 - s.pct_1000up_w3;
    const ret_underperform = s.ret_60d < s.industry_ret_60d_med;
    const dir_change_3m_ok = s.director_holding_change_3m > 0.5;

    const F1_raw = pct_1000up_delta_3w >= 1.0 ? 100 : pct_1000up_delta_3w * 50 + 50;
    const F2_raw = Math.max(0, Math.min(100, (s.industry_ret_60d_med - 0) * 50 + 50));
    const F3_raw = (dir_change_3m_ok && ret_underperform) ? 100 :
                   (dir_change_3m_ok ? 70 : (ret_underperform ? 50 : 30));
    const F4_raw = s.pct_400up_52w_high ? 100 : 50;
    const F5_raw = (s.div_years >= 5 && s.yield_now > s.yield_5y_avg) ? 100 :
                   (s.div_years >= 3 ? 70 : (s.div_years >= 1 ? 50 : 20));
    const F6_raw = (s.holder_cnt_change_8w < -5 && s.avg_lot_change_8w > 5) ? 100 :
                   (s.holder_cnt_change_8w < -3 && s.avg_lot_change_8w > 3) ? 75 :
                   (s.holder_cnt_change_8w < 0 && s.avg_lot_change_8w > 0) ? 55 : 30;
    const dd = s.drawdown_120d;
    const in_drawdown = dd <= -10 && dd >= -25;
    const holder_support = pct_1000up_delta_3w >= 0;
    const F8_raw = (in_drawdown && holder_support) ? 100 :
                   (in_drawdown ? 60 : (holder_support ? 50 : 30));
    const F10_raw = (s.crash_60d && s.pct_1000up_trend === '+') ? 100 :
                    (s.crash_60d && s.pct_1000up_trend === '=') ? 70 :
                    s.crash_60d ? 50 : 0;

    let f9_penalty = 0;
    let f9_triggers = [];
    if (s.is_60d_high && pct_1000up_delta_2w < 0) {
      f9_penalty += 15;
      f9_triggers.push('價創 60 日新高但大戶連 2 週減少');
    }
    if (s.dt_ratio > 40) {
      f9_penalty += 10;
      f9_triggers.push(`當沖比 ${s.dt_ratio.toFixed(1)}% > 40%`);
    }
    if (s.margin_pct > 70) {
      f9_penalty += 10;
      f9_triggers.push(`融資使用率 ${s.margin_pct.toFixed(1)}% > 70%`);
    }
    if (s.margin_pct > 85) {
      f9_penalty += 5;
    }
    f9_penalty = Math.min(20, f9_penalty);

    return {
      s, F1_raw, F2_raw, F3_raw, F4_raw, F5_raw, F6_raw, F8_raw, F10_raw,
      F9_penalty: f9_penalty, f9_triggers: f9_triggers,
      pct_1000up_delta_3w, ret_underperform, dir_change_3m_ok
    };
  });

  // 3. 因子橫截面標準化
  const factorKeys = ['F1_raw', 'F2_raw', 'F3_raw', 'F4_raw', 'F5_raw', 'F6_raw', 'F8_raw', 'F10_raw'];
  factorKeys.forEach(key => {
    const vals = factorValues.map(f => f[key]);
    const mean = vals.reduce((a, b) => a + b, 0) / vals.length;
    const std = Math.sqrt(vals.reduce((a, b) => a + (b - mean) ** 2, 0) / vals.length) || 1;
    factorValues.forEach(f => { f[key + '_z'] = (f[key] - mean) / std; });
  });

  // 4. 加權合成
  const out = factorValues.map(f => {
    const weights = { F1: 20, F2: 10, F3: 15, F4: 10, F5: 10, F6: 15, F8: 10, F10: 5 };
    const rawSum = (
      f.F1_raw_z * weights.F1 +
      f.F2_raw_z * weights.F2 +
      f.F3_raw_z * weights.F3 +
      f.F4_raw_z * weights.F4 +
      f.F5_raw_z * weights.F5 +
      f.F6_raw_z * weights.F6 +
      f.F8_raw_z * weights.F8 +
      f.F10_raw_z * weights.F10
    );
    let score = 50 + rawSum / 4;
    score -= f.F9_penalty;
    score = Math.max(0, Math.min(100, score));

    let tier;
    if (score >= 75) tier = 'A';
    else if (score >= 60) tier = 'B';
    else if (score >= 45) tier = 'C';
    else tier = 'D';

    if (f.f9_triggers.length >= 2 && (tier === 'A' || tier === 'B')) {
      tier = tier === 'A' ? 'B' : 'C';
    }

    return {
      ...f.s,
      _filtered: false,
      _reasons: [],
      score: Math.round(score * 10) / 10,
      tier: tier,
      F1: Math.round(f.F1_raw),
      F2: Math.round(f.F2_raw),
      F3: Math.round(f.F3_raw),
      F4: Math.round(f.F4_raw),
      F5: Math.round(f.F5_raw),
      F6: Math.round(f.F6_raw),
      F8: Math.round(f.F8_raw),
      F10: Math.round(f.F10_raw),
      F9_penalty: f.F9_penalty,
      f9_triggers: f.f9_triggers,
      rawSum: rawSum
    };
  });

  return { survivors: out, rejected: rejected };
}

// =============================================================
// Bootstrapping：頁面載入時呼叫 loadRealData() 並設到 window.STOCK_UNIVERSE
// =============================================================

async function initializeData() {
  const real = await loadRealData();
  if (real && Array.isArray(real) && real.length > 0) {
    window.STOCK_UNIVERSE = real;
    return { source: 'real', count: real.length, meta: DATA_META };
  }
  // Fallback：若 /data/latest/demo_subset.json 不存在（例如本地無 server），
  // 給一個非常小的 STOCK_UNIVERSE 讓 UI 仍能 render 並顯示「資料載入失敗」。
  console.warn('[data.js] Failed to load real data:', DATA_LOAD_ERROR);
  window.STOCK_UNIVERSE = [];
  return { source: 'empty', count: 0, error: DATA_LOAD_ERROR };
}

// 對外暴露
window.INDUSTRY_LIST = INDUSTRY_LIST;
window.FACTOR_WEIGHTS = FACTOR_WEIGHTS;
window.FACTOR_DEFINITIONS = FACTOR_DEFINITIONS;
window.HARD_FILTERS = HARD_FILTERS;
window.computeScores = computeScores;
window.initializeData = initializeData;
window.getDataMeta = () => DATA_META;
window.getDataLoadError = () => DATA_LOAD_ERROR;
window.isDataLoaded = () => DATA_LOADED;