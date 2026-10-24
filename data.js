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

// 各因子的「資料接通狀態」（2026-10 實測結果，不是設計藍圖）
//
// level:
//   ok       — 所有輸入欄位都已由真實來源供應
//   partial  — 部分輸入已接通，缺的部分仍是示意值
//   none     — 尚未接通，該因子目前一律是示意值
//
// 這張表的存在，是為了不讓「9 大因子」看起來像全部都已經在跑真實資料。
const FACTOR_STATUS = {
  F1:  { level: 'partial', text: '集保當週已通；需累積 4 週歷史才有 w3' },
  F2:  { level: 'ok',       text: '已接通：玩股網日 K 線 → 產業 60 日報酬中位數' },
  F3:  { level: 'ok',       text: '已接通：MOPS 董監持股 + 玩股網日 K 線' },
  F4:  { level: 'none',    text: '尚未接通：需要 52 週高點基準' },
  F5:  { level: 'none',    text: '尚未接通：需要 FinMind 股利資料' },
  F6:  { level: 'none',    text: '尚未接通：需要集保股東人數資料' },
  F8:  { level: 'ok',       text: '已接通：玩股網日 K 線 + 集保分級' },
  F9:  { level: 'partial', text: '價格與分級已通；融資券/當沖比需玩股網登入' },
  F10: { level: 'partial', text: '價格已通；需集保多週歷史才有趨勢' }
};

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
    // cache-busting：GitHub Pages 對靜態檔設了 max-age，
    // 就算 fetch 帶 cache:'no-store'，瀏覽器仍可能回傳記憶體快取，
    // 導致 banner 顯示舊的來源狀態。加上時間戳確保每次都是最新。
    const bust = `?t=${Date.now()}`;
    const [meta, demo, tdcc] = await Promise.all([
      fetchJSON(`data/latest/meta.json${bust}`),
      fetchJSON(`data/latest/demo_subset.json${bust}`),
      fetchJSON(`data/latest/tdcc_chip.json${bust}`).catch(() => null),
    ]);
    DATA_META = meta;
    DATA_LOADED = true;
    // 合併 TDCC 資料（免費、免登入，權威來源）
    //
    // 關鍵設計（BUG-01 / BUG-14）：
    // TDCC 開放資料只提供「當週」快照，沒有 w1/w2/w3。
    // 若只覆寫 pct_1000up_now 而保留示意的 w3，會得到
    //   84.7(真實) - 66.8(示意) = 17.9 → F1 恆為 100
    // 這比 NaN 更危險，因為它「看起來合理」。
    // 因此採用**原子式覆寫**：多週歷史不完整時，整組保持一致（不混用）。
    if (tdcc && Array.isArray(tdcc)) {
      const tdcc_by_code = {};
      for (const r of tdcc) tdcc_by_code[r.code] = r;
      for (const s of demo) {
        const t = tdcc_by_code[s.code];
        if (!t) continue;
        s._provenance = s._provenance || {};

        const hasFullHistory =
          t.pct_1000up_w1 != null && t.pct_1000up_w2 != null && t.pct_1000up_w3 != null;

        if (hasFullHistory) {
          // 完整多週歷史 → 整組覆寫並標記為真實
          s.pct_1000up_now = t.pct_1000up_now;
          s.pct_400up_now = t.pct_400up_now;
          s.pct_600up_now = t.pct_600up_now;
          s.pct_800up_now = t.pct_800up_now;
          s.pct_1000up_w1 = t.pct_1000up_w1;
          s.pct_1000up_w2 = t.pct_1000up_w2;
          s.pct_1000up_w3 = t.pct_1000up_w3;
          s.pct_1000up_trend = t.pct_1000up_trend;
          s.people_1000up_now = t.people_1000up_now;
          s.people_400up_now = t.people_400up_now;
          s.date_chip = t.date;
          ['pct_1000up_now', 'pct_400up_now', 'pct_600up_now', 'pct_800up_now',
           'pct_1000up_w1', 'pct_1000up_w2', 'pct_1000up_w3', 'pct_1000up_trend',
           'people_1000up_now', 'people_400up_now', 'date_chip'].forEach(k => {
            s._provenance[k] = 'real';
          });
        } else {
          // 只有當週：只覆寫「當週」欄位，**不動** w1/w2/w3（避免真假混用）
          s.pct_1000up_now = t.pct_1000up_now;
          s.pct_400up_now = t.pct_400up_now;
          s.pct_600up_now = t.pct_600up_now;
          s.pct_800up_now = t.pct_800up_now;
          s.people_1000up_now = t.people_1000up_now;
          s.people_400up_now = t.people_400up_now;
          s.date_chip = t.date;
          ['pct_1000up_now', 'pct_400up_now', 'pct_600up_now', 'pct_800up_now',
           'people_1000up_now', 'people_400up_now', 'date_chip'].forEach(k => {
            s._provenance[k] = 'real';
          });
          // w1/w2/w3 維持 illustrative → F1 因輸入混合而被判定不可用
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
// 資料來源感知（Provenance-aware）評分引擎
// =============================================================
// 對應 docs/2026-10-21-專案體檢報告.md BUG-01 / BUG-14 / BUG-15
//
// 設計原則：
// 1. 每個因子需要一組輸入欄位（見 FACTOR_INPUTS）。
// 2. 只有當**所有**輸入欄位的來源都是 real 時，該因子才可計算。
//    混合「真實 now」與「示意 history」會產生假 delta（例如 84.7 - 66.8 = 17.9
//    → F1 恆為 100），比 NaN 更危險，因為它看起來合理。
// 3. 不可用的因子，其權重按比例重新分配給該股可用的因子。
// 4. 全程 NaN 防護：任何非有限值一律退化为中性 50，不讓污染擴散。
// 5. 每檔股票輸出 data_quality，供 UI 誠實呈現「這個分數有多可信」。

const FACTOR_INPUTS = {
  F1:  ['pct_1000up_now', 'pct_1000up_w1', 'pct_1000up_w2', 'pct_1000up_w3'],
  F2:  ['industry_ret_60d_med'],
  F3:  ['director_holding_change_3m', 'ret_60d', 'industry_ret_60d_med'],
  F4:  ['pct_400up_52w_high'],
  F5:  ['div_years', 'yield_now', 'yield_5y_avg'],
  F6:  ['holder_cnt_change_8w', 'avg_lot_change_8w'],
  F8:  ['drawdown_120d', 'pct_1000up_now'],
  F9:  ['is_60d_high', 'pct_1000up_now', 'pct_1000up_w1', 'pct_1000up_w3', 'margin_pct', 'dt_ratio'],
  F10: ['crash_60d', 'pct_1000up_trend'],
};

// 正分因子的權重（沿用檔案頂部 FACTOR_WEIGHTS，排除 F9 扣分項）
const POSITIVE_FACTORS = ['F1', 'F2', 'F3', 'F4', 'F5', 'F6', 'F8', 'F10'];

// F9 為扣分項，權重 −20（封頂）
const F9_MAX_PENALTY = 20;

// 正分因子的權重總和（用於權重重新分配後的尺度換算）
const TOTAL_POSITIVE_WEIGHT = POSITIVE_FACTORS.reduce(
  (sum, fid) => sum + Math.abs(FACTOR_WEIGHTS[fid] || 0), 0); // 95
// 原始公式 50 + rawSum/4 → 尺度係數
const SCORE_SCALE = TOTAL_POSITIVE_WEIGHT / 4; // 23.75

// 判斷某欄位對某股是否為真實資料
function isRealField(stock, field) {
  const prov = stock._provenance;
  if (!prov) return false;           // 沒有 provenance → 一律視為非真實（保守）
  return prov[field] === 'real';
}

// 判斷某因子對某股是否可用（所有輸入皆真實）
function factorAvailable(stock, factor) {
  const inputs = FACTOR_INPUTS[factor];
  if (!inputs || inputs.length === 0) return false;
  return inputs.every(f => isRealField(stock, f));
}

// 安全數值：非有限值一律退化为 fallback
function safeNum(v, fallback = 0) {
  const n = Number(v);
  return Number.isFinite(n) ? n : fallback;
}

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

  // 2. 因子計算（值一律安全化；可用性另行判定）
  const factorValues = survivors.map(s => {
    const pct_1000up_now = safeNum(s.pct_1000up_now, 50);
    const pct_1000up_w1 = safeNum(s.pct_1000up_w1, pct_1000up_now);
    const pct_1000up_w2 = safeNum(s.pct_1000up_w2, pct_1000up_w1);
    const pct_1000up_w3 = safeNum(s.pct_1000up_w3, pct_1000up_now);
    const pct_1000up_delta_3w = pct_1000up_now - pct_1000up_w3;
    const pct_1000up_delta_2w = pct_1000up_w1 - pct_1000up_w3;
    const ret_60d = safeNum(s.ret_60d, 0);
    const industry_ret_60d_med = safeNum(s.industry_ret_60d_med, 0);
    const ret_underperform = ret_60d < industry_ret_60d_med;
    const dir_change_3m_ok = safeNum(s.director_holding_change_3m, 0) > 0.5;

    const F1_raw = (() => {
      // 原始需求文件 §四：「1000 張以上大戶持股比例**連續 ≥3 週增加**，
      // 且**累計增幅 ≥1%**」。
      // 舊版只算 now - w3 的淨差，完全沒有判斷「連續」——那是另一個因子。
      const consecutiveUp3w =
        pct_1000up_w3 < pct_1000up_w2 &&
        pct_1000up_w2 < pct_1000up_w1 &&
        pct_1000up_w1 < pct_1000up_now;
      const cumGain3w = pct_1000up_delta_3w;
      if (consecutiveUp3w) {
        return cumGain3w >= 1.0 ? 100 : 60 + cumGain3w * 20;
      }
      // 不是連續增加：即使淨值為正也只給低分（避免把「一週大漲一週回吐」
      // 誤判成「大戶連續加碼」）
      return cumGain3w > 0 ? 45 : 20;
    })();
    const F2_raw = Math.max(0, Math.min(100, industry_ret_60d_med * 50 + 50));
    const F3_raw = (dir_change_3m_ok && ret_underperform) ? 100 :
                   (dir_change_3m_ok ? 70 : (ret_underperform ? 50 : 30));
    const F4_raw = s.pct_400up_52w_high ? 100 : 50;
    const F5_raw = (safeNum(s.div_years, 0) >= 5 && safeNum(s.yield_now, 0) > safeNum(s.yield_5y_avg, 0)) ? 100 :
                   (safeNum(s.div_years, 0) >= 3 ? 70 : (safeNum(s.div_years, 0) >= 1 ? 50 : 20));
    const F6_raw = (safeNum(s.holder_cnt_change_8w, 0) < -5 && safeNum(s.avg_lot_change_8w, 0) > 5) ? 100 :
                   (safeNum(s.holder_cnt_change_8w, 0) < -3 && safeNum(s.avg_lot_change_8w, 0) > 3) ? 75 :
                   (safeNum(s.holder_cnt_change_8w, 0) < 0 && safeNum(s.avg_lot_change_8w, 0) > 0) ? 55 : 30;
    const dd = safeNum(s.drawdown_120d, 0);
    const in_drawdown = dd <= -10 && dd >= -25;
    const holder_support = pct_1000up_delta_3w >= 0;
    const F8_raw = (in_drawdown && holder_support) ? 100 :
                   (in_drawdown ? 60 : (holder_support ? 50 : 30));
    const F10_raw = (s.crash_60d && s.pct_1000up_trend === '+') ? 100 :
                    (s.crash_60d && s.pct_1000up_trend === '=') ? 70 :
                    s.crash_60d ? 50 : 0;

    // F9 扣分（同樣安全化）
    let f9_penalty = 0;
    let f9_triggers = [];
    if (s.is_60d_high && pct_1000up_delta_2w < 0) {
      f9_penalty += 15;
      f9_triggers.push('價創 60 日新高但大戶連 2 週減少');
    }
    if (safeNum(s.dt_ratio, 0) > 40) {
      f9_penalty += 10;
      f9_triggers.push(`當沖比 ${safeNum(s.dt_ratio, 0).toFixed(1)}% > 40%`);
    }
    if (safeNum(s.margin_pct, 0) > 70) {
      f9_penalty += 10;
      f9_triggers.push(`融資使用率 ${safeNum(s.margin_pct, 0).toFixed(1)}% > 70%`);
    }
    if (safeNum(s.margin_pct, 0) > 85) {
      f9_penalty += 5;
    }
    f9_penalty = Math.min(F9_MAX_PENALTY, f9_penalty);

    // 可用因子（輸入皆為真實資料）
    const available = {};
    Object.keys(FACTOR_WEIGHTS).forEach(f => { available[f] = factorAvailable(s, f); });
    const f9_available = factorAvailable(s, 'F9');

    return {
      s, F1_raw, F2_raw, F3_raw, F4_raw, F5_raw, F6_raw, F8_raw, F10_raw,
      F9_penalty: f9_penalty, f9_triggers: f9_triggers,
      pct_1000up_delta_3w, ret_underperform, dir_change_3m_ok,
      available, f9_available,
    };
  });

  // 3. 因子橫截面標準化（僅使用該因子可用的股票計算 mean/std）
  const factorKeys = ['F1_raw', 'F2_raw', 'F3_raw', 'F4_raw', 'F5_raw', 'F6_raw', 'F8_raw', 'F10_raw'];
  const factorIdMap = { F1_raw: 'F1', F2_raw: 'F2', F3_raw: 'F3', F4_raw: 'F4', F5_raw: 'F5', F6_raw: 'F6', F8_raw: 'F8', F10_raw: 'F10' };
  factorKeys.forEach(key => {
    const fid = factorIdMap[key];
    const usable = factorValues.filter(f => f.available[fid]);
    const pool = usable.length > 0 ? usable : factorValues; // 全不可用時退回全體（避免空集合）
    const vals = pool.map(f => safeNum(f[key], 50));
    const mean = vals.reduce((a, b) => a + b, 0) / vals.length;
    const variance = vals.reduce((a, b) => a + Math.pow(b - mean, 2), 0) / vals.length;
    const std = Math.sqrt(variance) || 1;
    factorValues.forEach(f => { f[key + '_z'] = safeNum((safeNum(f[key], 50) - mean) / std, 0); });
  });

  // 3.5 模式判定
  //
  // 三種模式（依「有多少股票具備真實因子」決定）：
  //   strict  — 每檔股票都至少有一個全真實輸入的因子 → 分數可互相比較
  //   partial — 部分股票有、部分沒有 → 沒有真實因子的股票不參與排名
  //   demo    — 全場都沒有任何因子具備完整真實輸入 → 以全部因子計分
  //             （維持示範教學效果），但明確標記 mode='demo'
  //
  // 舊版只有 strict / demo 兩種，且 strict 的門檻是「至少一檔有」——
  // 導致 43 檔裡只有 1 檔有真實資料時，整個版面仍宣稱「實戰模式」，
  // 使用者會誤以為所有分數都是真的。
  const realFactorCountPerStock = factorValues.map(
    f => POSITIVE_FACTORS.filter(fid => f.available[fid]).length
  );
  const anyRealFactor = realFactorCountPerStock.some(c => c > 0);
  const allRealFactor = realFactorCountPerStock.length > 0
    && realFactorCountPerStock.every(c => c > 0);
  const SCORING_MODE = allRealFactor ? 'strict' : (anyRealFactor ? 'partial' : 'demo');
  // strict / partial 模式下，沒有任何真實因子的股票不該混在排名裡
  const EXCLUDE_NO_DATA = SCORING_MODE !== 'demo';

  // 4. 加權合成（strict / partial 模式下不可用因子的權重按比例重新分配）
  const noData = [];
  const out = factorValues.map(f => {
    let rawSum = 0;
    let usedWeight = 0;
    POSITIVE_FACTORS.forEach(fid => {
      if (SCORING_MODE !== 'demo' && !f.available[fid]) return;
      const z = safeNum(f[fid + '_raw_z'], 0);
      rawSum += z * Math.abs(FACTOR_WEIGHTS[fid] || 0);
      usedWeight += Math.abs(FACTOR_WEIGHTS[fid] || 0);
    });

    let score;
    if (usedWeight > 0) {
      score = 50 + (rawSum / usedWeight) * SCORE_SCALE;
    } else {
      score = 50; // 完全無可用因子 → 中性分
    }
    if (f.f9_available || SCORING_MODE === 'demo') {
      score -= f.F9_penalty;
    } else {
      f.F9_penalty = 0;
      f.f9_triggers = [];
    }
    score = Math.max(0, Math.min(100, safeNum(score, 50)));

    let tier;
    if (score >= 75) tier = 'A';
    else if (score >= 60) tier = 'B';
    else if (score >= 45) tier = 'C';
    else tier = 'D';

    if (f.f9_triggers.length >= 2 && (tier === 'A' || tier === 'B')) {
      tier = tier === 'A' ? 'B' : 'C';
    }

    // 資料品質
    const realFactors = POSITIVE_FACTORS.filter(fid => f.available[fid]);
    const illustrativeFactors = POSITIVE_FACTORS.filter(fid => !f.available[fid]);
    const dataQuality = {
      mode: SCORING_MODE,
      real_factors: realFactors,
      illustrative_factors: illustrativeFactors,
      f9_real: f.f9_available,
      total_factors: POSITIVE_FACTORS.length,
      // 「這個分數可不可信」＝這檔股票有沒有真實因子（與全域模式無關）
      reliable: realFactors.length > 0,
      score_basis: realFactors.length > 0 ? 'real' : 'illustrative',
    };

    const row = {
      ...f.s,
      _filtered: false,
      _reasons: [],
      score: Math.round(score * 10) / 10,
      tier: tier,
      F1: Math.round(safeNum(f.F1_raw, 50)),
      F2: Math.round(safeNum(f.F2_raw, 50)),
      F3: Math.round(safeNum(f.F3_raw, 50)),
      F4: Math.round(safeNum(f.F4_raw, 50)),
      F5: Math.round(safeNum(f.F5_raw, 50)),
      F6: Math.round(safeNum(f.F6_raw, 50)),
      F8: Math.round(safeNum(f.F8_raw, 50)),
      F10: Math.round(safeNum(f.F10_raw, 50)),
      F9_penalty: f.F9_penalty,
      f9_triggers: f.f9_triggers,
      rawSum: rawSum,
      usedWeight: usedWeight,
      data_quality: dataQuality,
    };

    // strict / partial 模式下，沒有任何真實因子的股票不參與排名
    if (EXCLUDE_NO_DATA && realFactors.length === 0) {
      noData.push({ ...row, tier: 'D', _no_data: true });
      return null;
    }
    return row;
  }).filter(Boolean);

  return {
    survivors: out,
    rejected: rejected,
    noData: noData,
    mode: SCORING_MODE,
    coverage: {
      total: factorValues.length,
      with_real_factors: factorValues.length - noData.length,
      without_real_factors: noData.length,
    },
  };
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
window.FACTOR_INPUTS = FACTOR_INPUTS;
window.FACTOR_STATUS = FACTOR_STATUS;
window.HARD_FILTERS = HARD_FILTERS;
window.computeScores = computeScores;
window.initializeData = initializeData;
window.getDataMeta = () => DATA_META;
window.getDataLoadError = () => DATA_LOAD_ERROR;
window.isDataLoaded = () => DATA_LOADED;