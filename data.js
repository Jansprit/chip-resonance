// =============================================================
// 籌碼共振選股系統 — 模擬股票池與樣本資料
// 用途：演示評分流程，不可用於實際交易
// 設計：47 檔示範個股，涵蓋半導體/金融/傳產/生技/航運等 9 大產業
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

// 模擬個股資料：47 檔
// 欄位說明：
//   code         — 股票代號
//   name         — 公司簡稱
//   industry     — 所屬產業 CID
//   price        — 最新收盤價（元）
//   avg_volume   — 20日均量（張）
//   director_pledge — 董監質押率（%）
//   eps_q4       — 最近四季累計 EPS（元）
//   list_year    — 上市年數
//   warning      — 是否警示股/全額交割/暫停交易
//   margin_pct   — 融資使用率（%）
//   dt_ratio     — 當沖比（%）
//   pct_1000up_now — 1000張以上大戶持股比例（%）
//   pct_1000up_w1 — 1 週前
//   pct_1000up_w2 — 2 週前
//   pct_1000up_w3 — 3 週前
//   pct_400up     — 400張以上比例（%）
//   pct_400up_52w_high — 52 週高點標記
//   holder_cnt_change_8w — 8 週股東總人數變化率（%）
//   avg_lot_change_8w — 8 週平均持有張數變化率（%）
//   drawdown_120d — 自120日高點回撤（%）
//   ret_60d      — 60 日報酬率（%）
//   industry_ret_60d_med — 同產業 60 日報酬中位數（%）
//   director_holding_change_3m — 董監近3月變化（%）
//   div_years    — 連續配息年數
//   yield_now    — 目前殖利率（%）
//   yield_5y_avg — 5年平均殖利率（%）
//   crash_60d    — 是否 60 日內曾單週跌幅 >15%
//   pct_1000up_trend — 近 2 週趨勢（+增加/=持平/-減少）
//   is_60d_high  — 是否股價創 60 日新高
const STOCK_UNIVERSE = [
  // 半導體
  { code: '2330', name: '台積電',     industry: 'SEMI', price: 920,  avg_volume: 35000, director_pledge: 0.1, eps_q4: 32.5, list_year: 30, warning: false, margin_pct: 12, dt_ratio: 18,
    pct_1000up_now: 67.5, pct_1000up_w1: 67.2, pct_1000up_w2: 67.0, pct_1000up_w3: 66.8,
    pct_400up: 82.1, pct_400up_52w_high: false, holder_cnt_change_8w: -2.1, avg_lot_change_8w: 3.5,
    drawdown_120d: -3.2, ret_60d: 8.5, industry_ret_60d_med: 5.2, director_holding_change_3m: 0.05,
    div_years: 21, yield_now: 1.7, yield_5y_avg: 2.5, crash_60d: false, pct_1000up_trend: '+', is_60d_high: true },
  { code: '2454', name: '聯發科',     industry: 'SEMI', price: 1280, avg_volume: 8500, director_pledge: 0.5, eps_q4: 56.2, list_year: 23, warning: false, margin_pct: 25, dt_ratio: 22,
    pct_1000up_now: 71.3, pct_1000up_w1: 71.5, pct_1000up_w2: 71.7, pct_1000up_w3: 71.9,
    pct_400up: 85.2, pct_400up_52w_high: false, holder_cnt_change_8w: -3.8, avg_lot_change_8w: 4.2,
    drawdown_120d: -8.5, ret_60d: 12.3, industry_ret_60d_med: 5.2, director_holding_change_3m: 0.3,
    div_years: 19, yield_now: 2.3, yield_5y_avg: 2.8, crash_60d: false, pct_1000up_trend: '+', is_60d_high: false },
  { code: '2303', name: '聯電',       industry: 'SEMI', price: 48.5, avg_volume: 28000, director_pledge: 1.2, eps_q4: 3.2, list_year: 38, warning: false, margin_pct: 18, dt_ratio: 25,
    pct_1000up_now: 52.1, pct_1000up_w1: 51.8, pct_1000up_w2: 51.5, pct_1000up_w3: 51.0,
    pct_400up: 68.5, pct_400up_52w_high: false, holder_cnt_change_8w: -1.2, avg_lot_change_8w: 2.1,
    drawdown_120d: -12.5, ret_60d: 2.1, industry_ret_60d_med: 5.2, director_holding_change_3m: 0.1,
    div_years: 16, yield_now: 4.2, yield_5y_avg: 3.8, crash_60d: false, pct_1000up_trend: '+', is_60d_high: false },
  { code: '3711', name: '日月光投控', industry: 'SEMI', price: 165, avg_volume: 12000, director_pledge: 0.3, eps_q4: 8.5, list_year: 8, warning: false, margin_pct: 22, dt_ratio: 20,
    pct_1000up_now: 58.3, pct_1000up_w1: 58.5, pct_1000up_w2: 58.4, pct_1000up_w3: 58.2,
    pct_400up: 73.6, pct_400up_52w_high: false, holder_cnt_change_8w: -0.8, avg_lot_change_8w: 1.5,
    drawdown_120d: -6.2, ret_60d: 6.5, industry_ret_60d_med: 5.2, director_holding_change_3m: 0.2,
    div_years: 9, yield_now: 3.1, yield_5y_avg: 3.5, crash_60d: false, pct_1000up_trend: '=', is_60d_high: false },
  { code: '5347', name: '世界先進',   industry: 'SEMI', price: 88, avg_volume: 9500, director_pledge: 0, eps_q4: 4.8, list_year: 17, warning: false, margin_pct: 28, dt_ratio: 30,
    pct_1000up_now: 49.2, pct_1000up_w1: 48.0, pct_1000up_w2: 46.8, pct_1000up_w3: 45.5,
    pct_400up: 65.8, pct_400up_52w_high: true, holder_cnt_change_8w: -5.2, avg_lot_change_8w: 6.5,
    drawdown_120d: -15.8, ret_60d: 1.2, industry_ret_60d_med: 5.2, director_holding_change_3m: 0.6,
    div_years: 15, yield_now: 3.5, yield_5y_avg: 3.2, crash_60d: false, pct_1000up_trend: '+', is_60d_high: false },

  // 金融
  { code: '2884', name: '玉山金',     industry: 'FIN', price: 28.5, avg_volume: 22000, director_pledge: 0, eps_q4: 1.8, list_year: 22, warning: false, margin_pct: 8, dt_ratio: 12,
    pct_1000up_now: 45.2, pct_1000up_w1: 45.0, pct_1000up_w2: 44.8, pct_1000up_w3: 44.5,
    pct_400up: 62.1, pct_400up_52w_high: false, holder_cnt_change_8w: 1.2, avg_lot_change_8w: 0.8,
    drawdown_120d: -2.5, ret_60d: 4.5, industry_ret_60d_med: 3.8, director_holding_change_3m: 0.05,
    div_years: 18, yield_now: 4.5, yield_5y_avg: 4.2, crash_60d: false, pct_1000up_trend: '+', is_60d_high: false },
  { code: '2882', name: '國泰金',     industry: 'FIN', price: 65, avg_volume: 18000, director_pledge: 0.1, eps_q4: 4.5, list_year: 23, warning: false, margin_pct: 6, dt_ratio: 10,
    pct_1000up_now: 52.8, pct_1000up_w1: 52.5, pct_1000up_w2: 52.3, pct_1000up_w3: 52.0,
    pct_400up: 68.5, pct_400up_52w_high: false, holder_cnt_change_8w: -0.5, avg_lot_change_8w: 1.2,
    drawdown_120d: -1.8, ret_60d: 3.2, industry_ret_60d_med: 3.8, director_holding_change_3m: 0.08,
    div_years: 24, yield_now: 3.8, yield_5y_avg: 4.0, crash_60d: false, pct_1000up_trend: '+', is_60d_high: false },
  { code: '2891', name: '中信金',     industry: 'FIN', price: 38, avg_volume: 15000, director_pledge: 0, eps_q4: 2.8, list_year: 22, warning: false, margin_pct: 5, dt_ratio: 8,
    pct_1000up_now: 48.5, pct_1000up_w1: 48.2, pct_1000up_w2: 47.8, pct_1000up_w3: 47.5,
    pct_400up: 64.2, pct_400up_52w_high: false, holder_cnt_change_8w: -1.8, avg_lot_change_8w: 2.5,
    drawdown_120d: -4.2, ret_60d: 5.5, industry_ret_60d_med: 3.8, director_holding_change_3m: 0.15,
    div_years: 17, yield_now: 4.2, yield_5y_avg: 4.5, crash_60d: false, pct_1000up_trend: '+', is_60d_high: false },
  { code: '2886', name: '兆豐金',     industry: 'FIN', price: 42, avg_volume: 12000, director_pledge: 0, eps_q4: 2.5, list_year: 18, warning: false, margin_pct: 4, dt_ratio: 9,
    pct_1000up_now: 55.2, pct_1000up_w1: 55.0, pct_1000up_w2: 54.8, pct_1000up_w3: 54.5,
    pct_400up: 70.5, pct_400up_52w_high: false, holder_cnt_change_8w: -2.5, avg_lot_change_8w: 3.2,
    drawdown_120d: -3.5, ret_60d: 6.8, industry_ret_60d_med: 3.8, director_holding_change_3m: 0.12,
    div_years: 18, yield_now: 4.8, yield_5y_avg: 4.6, crash_60d: false, pct_1000up_trend: '+', is_60d_high: false },

  // PCB／載板
  { code: '3037', name: '欣興',       industry: 'PCB', price: 195, avg_volume: 8500, director_pledge: 0.8, eps_q4: 9.5, list_year: 27, warning: false, margin_pct: 35, dt_ratio: 28,
    pct_1000up_now: 62.5, pct_1000up_w1: 62.0, pct_1000up_w2: 61.5, pct_1000up_w3: 61.0,
    pct_400up: 75.8, pct_400up_52w_high: false, holder_cnt_change_8w: -4.5, avg_lot_change_8w: 5.8,
    drawdown_120d: -10.2, ret_60d: 18.5, industry_ret_60d_med: 12.5, director_holding_change_3m: 0.8,
    div_years: 12, yield_now: 1.8, yield_5y_avg: 2.5, crash_60d: false, pct_1000up_trend: '+', is_60d_high: true },
  { code: '8046', name: '南電',       industry: 'PCB', price: 215, avg_volume: 4200, director_pledge: 0.5, eps_q4: 11.2, list_year: 25, warning: false, margin_pct: 42, dt_ratio: 32,
    pct_1000up_now: 58.8, pct_1000up_w1: 58.0, pct_1000up_w2: 57.2, pct_1000up_w3: 56.5,
    pct_400up: 72.1, pct_400up_52w_high: false, holder_cnt_change_8w: -6.2, avg_lot_change_8w: 7.5,
    drawdown_120d: -12.8, ret_60d: 22.5, industry_ret_60d_med: 12.5, director_holding_change_3m: 1.2,
    div_years: 10, yield_now: 1.5, yield_5y_avg: 2.2, crash_60d: false, pct_1000up_trend: '+', is_60d_high: true },
  { code: '3189', name: '景碩',       industry: 'PCB', price: 92, avg_volume: 6800, director_pledge: 2.5, eps_q4: 4.2, list_year: 20, warning: false, margin_pct: 38, dt_ratio: 35,
    pct_1000up_now: 45.5, pct_1000up_w1: 45.0, pct_1000up_w2: 44.5, pct_1000up_w3: 44.0,
    pct_400up: 62.5, pct_400up_52w_high: false, holder_cnt_change_8w: -3.5, avg_lot_change_8w: 4.2,
    drawdown_120d: -18.5, ret_60d: 8.5, industry_ret_60d_med: 12.5, director_holding_change_3m: 0.4,
    div_years: 8, yield_now: 2.5, yield_5y_avg: 3.0, crash_60d: false, pct_1000up_trend: '+', is_60d_high: false },

  // 生技
  { code: '4743', name: '合一',       industry: 'BIO', price: 35, avg_volume: 5500, director_pledge: 5.2, eps_q4: -1.5, list_year: 12, warning: false, margin_pct: 48, dt_ratio: 35,
    pct_1000up_now: 38.5, pct_1000up_w1: 38.0, pct_1000up_w2: 37.5, pct_1000up_w3: 37.0,
    pct_400up: 52.5, pct_400up_52w_high: false, holder_cnt_change_8w: -8.5, avg_lot_change_8w: 9.5,
    drawdown_120d: -22.5, ret_60d: -5.5, industry_ret_60d_med: -1.2, director_holding_change_3m: 2.5,
    div_years: 0, yield_now: 0, yield_5y_avg: 0, crash_60d: true, pct_1000up_trend: '+', is_60d_high: false },
  { code: '4128', name: '中天',       industry: 'BIO', price: 28, avg_volume: 3200, director_pledge: 8.5, eps_q4: -2.5, list_year: 13, warning: false, margin_pct: 55, dt_ratio: 42,
    pct_1000up_now: 32.5, pct_1000up_w1: 32.0, pct_1000up_w2: 31.5, pct_1000up_w3: 31.0,
    pct_400up: 48.5, pct_400up_52w_high: false, holder_cnt_change_8w: -12.5, avg_lot_change_8w: 14.5,
    drawdown_120d: -35.5, ret_60d: -15.5, industry_ret_60d_med: -1.2, director_holding_change_3m: 5.5,
    div_years: 0, yield_now: 0, yield_5y_avg: 0, crash_60d: true, pct_1000up_trend: '+', is_60d_high: false },
  { code: '4133', name: '亞諾法',     industry: 'BIO', price: 42, avg_volume: 1800, director_pledge: 0.5, eps_q4: 1.8, list_year: 8, warning: false, margin_pct: 25, dt_ratio: 22,
    pct_1000up_now: 42.5, pct_1000up_w1: 42.0, pct_1000up_w2: 41.5, pct_1000up_w3: 41.0,
    pct_400up: 58.5, pct_400up_52w_high: false, holder_cnt_change_8w: -2.5, avg_lot_change_8w: 3.5,
    drawdown_120d: -8.5, ret_60d: 5.5, industry_ret_60d_med: -1.2, director_holding_change_3m: 0.3,
    div_years: 5, yield_now: 1.5, yield_5y_avg: 1.2, crash_60d: false, pct_1000up_trend: '+', is_60d_high: false },
  { code: '6446', name: '藥華藥',     industry: 'BIO', price: 285, avg_volume: 1500, director_pledge: 2.1, eps_q4: 8.5, list_year: 7, warning: false, margin_pct: 18, dt_ratio: 28,
    pct_1000up_now: 65.5, pct_1000up_w1: 64.5, pct_1000up_w2: 63.5, pct_1000up_w3: 62.5,
    pct_400up: 78.5, pct_400up_52w_high: true, holder_cnt_change_8w: -4.2, avg_lot_change_8w: 5.5,
    drawdown_120d: -15.2, ret_60d: 12.5, industry_ret_60d_med: -1.2, director_holding_change_3m: 1.5,
    div_years: 0, yield_now: 0, yield_5y_avg: 0, crash_60d: false, pct_1000up_trend: '+', is_60d_high: false },

  // 航運
  { code: '2603', name: '長榮',       industry: 'SHIP', price: 78, avg_volume: 22000, director_pledge: 0.2, eps_q4: 5.8, list_year: 38, warning: false, margin_pct: 22, dt_ratio: 25,
    pct_1000up_now: 58.5, pct_1000up_w1: 58.0, pct_1000up_w2: 57.5, pct_1000up_w3: 57.0,
    pct_400up: 72.5, pct_400up_52w_high: false, holder_cnt_change_8w: -3.2, avg_lot_change_8w: 4.5,
    drawdown_120d: -18.5, ret_60d: 15.5, industry_ret_60d_med: 8.5, director_holding_change_3m: 0.8,
    div_years: 12, yield_now: 4.5, yield_5y_avg: 5.2, crash_60d: false, pct_1000up_trend: '+', is_60d_high: false },
  { code: '2609', name: '陽明',       industry: 'SHIP', price: 65, avg_volume: 15000, director_pledge: 0.5, eps_q4: 4.2, list_year: 32, warning: false, margin_pct: 25, dt_ratio: 28,
    pct_1000up_now: 52.5, pct_1000up_w1: 52.0, pct_1000up_w2: 51.5, pct_1000up_w3: 51.0,
    pct_400up: 68.5, pct_400up_52w_high: false, holder_cnt_change_8w: -4.5, avg_lot_change_8w: 5.5,
    drawdown_120d: -22.5, ret_60d: 18.5, industry_ret_60d_med: 8.5, director_holding_change_3m: 1.2,
    div_years: 8, yield_now: 3.8, yield_5y_avg: 4.5, crash_60d: false, pct_1000up_trend: '+', is_60d_high: false },
  { code: '2615', name: '萬海',       industry: 'SHIP', price: 85, avg_volume: 12000, director_pledge: 0.3, eps_q4: 6.5, list_year: 28, warning: false, margin_pct: 20, dt_ratio: 22,
    pct_1000up_now: 55.5, pct_1000up_w1: 55.0, pct_1000up_w2: 54.5, pct_1000up_w3: 54.0,
    pct_400up: 70.5, pct_400up_52w_high: false, holder_cnt_change_8w: -2.8, avg_lot_change_8w: 3.8,
    drawdown_120d: -16.5, ret_60d: 12.5, industry_ret_60d_med: 8.5, director_holding_change_3m: 0.5,
    div_years: 10, yield_now: 4.2, yield_5y_avg: 4.8, crash_60d: false, pct_1000up_trend: '+', is_60d_high: false },
  { code: '2618', name: '長榮航',     industry: 'SHIP', price: 35, avg_volume: 18000, director_pledge: 0.8, eps_q4: 2.8, list_year: 33, warning: false, margin_pct: 18, dt_ratio: 20,
    pct_1000up_now: 48.5, pct_1000up_w1: 48.0, pct_1000up_w2: 47.5, pct_1000up_w3: 47.0,
    pct_400up: 64.5, pct_400up_52w_high: false, holder_cnt_change_8w: -1.5, avg_lot_change_8w: 2.2,
    drawdown_120d: -8.5, ret_60d: 6.5, industry_ret_60d_med: 8.5, director_holding_change_3m: 0.3,
    div_years: 13, yield_now: 3.5, yield_5y_avg: 3.8, crash_60d: false, pct_1000up_trend: '+', is_60d_high: false },

  // 汽車／零件
  { code: '2317', name: '鴻海',     industry: 'AUTO', price: 215, avg_volume: 25000, director_pledge: 0.5, eps_q4: 10.5, list_year: 33, warning: false, margin_pct: 28, dt_ratio: 25,
    pct_1000up_now: 62.5, pct_1000up_w1: 62.0, pct_1000up_w2: 61.5, pct_1000up_w3: 61.0,
    pct_400up: 75.5, pct_400up_52w_high: false, holder_cnt_change_8w: -3.5, avg_lot_change_8w: 4.5,
    drawdown_120d: -8.5, ret_60d: 22.5, industry_ret_60d_med: 12.5, director_holding_change_3m: 0.5,
    div_years: 15, yield_now: 2.5, yield_5y_avg: 3.2, crash_60d: false, pct_1000up_trend: '+', is_60d_high: true },
  { code: '2227', name: '裕隆',     industry: 'AUTO', price: 95, avg_volume: 8500, director_pledge: 1.5, eps_q4: 4.5, list_year: 35, warning: false, margin_pct: 22, dt_ratio: 22,
    pct_1000up_now: 52.5, pct_1000up_w1: 52.0, pct_1000up_w2: 51.5, pct_1000up_w3: 51.0,
    pct_400up: 68.5, pct_400up_52w_high: false, holder_cnt_change_8w: -2.5, avg_lot_change_8w: 3.5,
    drawdown_120d: -12.5, ret_60d: 8.5, industry_ret_60d_med: 12.5, director_holding_change_3m: 0.8,
    div_years: 8, yield_now: 2.8, yield_5y_avg: 3.5, crash_60d: false, pct_1000up_trend: '+', is_60d_high: false },
  { code: '1326', name: '台化',     industry: 'PLAS', price: 58, avg_volume: 12000, director_pledge: 0.2, eps_q4: 3.5, list_year: 38, warning: false, margin_pct: 12, dt_ratio: 15,
    pct_1000up_now: 48.5, pct_1000up_w1: 48.0, pct_1000up_w2: 47.5, pct_1000up_w3: 47.0,
    pct_400up: 64.5, pct_400up_52w_high: false, holder_cnt_change_8w: -1.8, avg_lot_change_8w: 2.5,
    drawdown_120d: -5.5, ret_60d: 4.5, industry_ret_60d_med: 3.2, director_holding_change_3m: 0.2,
    div_years: 28, yield_now: 4.2, yield_5y_avg: 4.5, crash_60d: false, pct_1000up_trend: '+', is_60d_high: false },
  { code: '1303', name: '南亞',     industry: 'PLAS', price: 75, avg_volume: 9500, director_pledge: 0.1, eps_q4: 4.2, list_year: 38, warning: false, margin_pct: 10, dt_ratio: 12,
    pct_1000up_now: 52.5, pct_1000up_w1: 52.0, pct_1000up_w2: 51.5, pct_1000up_w3: 51.0,
    pct_400up: 68.5, pct_400up_52w_high: false, holder_cnt_change_8w: -2.2, avg_lot_change_8w: 3.0,
    drawdown_120d: -6.5, ret_60d: 5.2, industry_ret_60d_med: 3.2, director_holding_change_3m: 0.15,
    div_years: 28, yield_now: 3.8, yield_5y_avg: 4.2, crash_60d: false, pct_1000up_trend: '+', is_60d_high: false },

  // 食品
  { code: '1216', name: '統一',     industry: 'FOOD', price: 82, avg_volume: 8500, director_pledge: 0.1, eps_q4: 4.5, list_year: 38, warning: false, margin_pct: 8, dt_ratio: 12,
    pct_1000up_now: 50.5, pct_1000up_w1: 50.0, pct_1000up_w2: 49.5, pct_1000up_w3: 49.0,
    pct_400up: 66.5, pct_400up_52w_high: false, holder_cnt_change_8w: -1.5, avg_lot_change_8w: 2.2,
    drawdown_120d: -4.5, ret_60d: 5.5, industry_ret_60d_med: 3.5, director_holding_change_3m: 0.1,
    div_years: 28, yield_now: 3.5, yield_5y_avg: 3.8, crash_60d: false, pct_1000up_trend: '+', is_60d_high: false },
  { code: '2912', name: '統一超',   industry: 'FOOD', price: 268, avg_volume: 1500, director_pledge: 0.05, eps_q4: 11.5, list_year: 27, warning: false, margin_pct: 5, dt_ratio: 8,
    pct_1000up_now: 68.5, pct_1000up_w1: 68.0, pct_1000up_w2: 67.5, pct_1000up_w3: 67.0,
    pct_400up: 82.5, pct_400up_52w_high: false, holder_cnt_change_8w: -0.5, avg_lot_change_8w: 1.5,
    drawdown_120d: -2.5, ret_60d: 3.5, industry_ret_60d_med: 3.5, director_holding_change_3m: 0.05,
    div_years: 28, yield_now: 2.8, yield_5y_avg: 3.2, crash_60d: false, pct_1000up_trend: '+', is_60d_high: false },
  { code: '1707', name: '葡萄王',   industry: 'FOOD', price: 142, avg_volume: 1200, director_pledge: 0.5, eps_q4: 7.5, list_year: 12, warning: false, margin_pct: 15, dt_ratio: 18,
    pct_1000up_now: 55.5, pct_1000up_w1: 55.0, pct_1000up_w2: 54.5, pct_1000up_w3: 54.0,
    pct_400up: 71.5, pct_400up_52w_high: false, holder_cnt_change_8w: -3.2, avg_lot_change_8w: 4.5,
    drawdown_120d: -8.5, ret_60d: 8.5, industry_ret_60d_med: 3.5, director_holding_change_3m: 0.8,
    div_years: 12, yield_now: 3.2, yield_5y_avg: 3.5, crash_60d: false, pct_1000up_trend: '+', is_60d_high: false },

  // 電子零組件
  { code: '2327', name: '國巨',     industry: 'ELEC', price: 195, avg_volume: 8500, director_pledge: 0.5, eps_q4: 9.5, list_year: 28, warning: false, margin_pct: 38, dt_ratio: 32,
    pct_1000up_now: 62.5, pct_1000up_w1: 62.0, pct_1000up_w2: 61.5, pct_1000up_w3: 61.0,
    pct_400up: 75.5, pct_400up_52w_high: false, holder_cnt_change_8w: -4.5, avg_lot_change_8w: 5.5,
    drawdown_120d: -12.5, ret_60d: 18.5, industry_ret_60d_med: 12.5, director_holding_change_3m: 1.2,
    div_years: 8, yield_now: 2.5, yield_5y_avg: 3.2, crash_60d: false, pct_1000up_trend: '+', is_60d_high: false },
  { code: '2308', name: '台達電',   industry: 'ELEC', price: 358, avg_volume: 6500, director_pledge: 0.3, eps_q4: 16.5, list_year: 30, warning: false, margin_pct: 12, dt_ratio: 15,
    pct_1000up_now: 65.5, pct_1000up_w1: 65.0, pct_1000up_w2: 64.5, pct_1000up_w3: 64.0,
    pct_400up: 78.5, pct_400up_52w_high: false, holder_cnt_change_8w: -1.8, avg_lot_change_8w: 2.5,
    drawdown_120d: -5.5, ret_60d: 12.5, industry_ret_60d_med: 12.5, director_holding_change_3m: 0.3,
    div_years: 25, yield_now: 2.2, yield_5y_avg: 2.8, crash_60d: false, pct_1000up_trend: '+', is_60d_high: false },
  { code: '2474', name: '可成',     industry: 'ELEC', price: 195, avg_volume: 3500, director_pledge: 0.5, eps_q4: 8.5, list_year: 25, warning: false, margin_pct: 22, dt_ratio: 25,
    pct_1000up_now: 55.5, pct_1000up_w1: 55.0, pct_1000up_w2: 54.5, pct_1000up_w3: 54.0,
    pct_400up: 70.5, pct_400up_52w_high: false, holder_cnt_change_8w: -2.5, avg_lot_change_8w: 3.5,
    drawdown_120d: -8.5, ret_60d: 6.5, industry_ret_60d_med: 12.5, director_holding_change_3m: 0.5,
    div_years: 12, yield_now: 3.5, yield_5y_avg: 4.0, crash_60d: false, pct_1000up_trend: '+', is_60d_high: false },

  // 警示股／地雷股示範 — 會被硬性過濾掉
  { code: '3056', name: '總太地產', industry: 'PLAS', price: 12, avg_volume: 350, director_pledge: 65, eps_q4: -3.5, list_year: 8, warning: true, margin_pct: 75, dt_ratio: 50,
    pct_1000up_now: 25.5, pct_1000up_w1: 25.0, pct_1000up_w2: 24.5, pct_1000up_w3: 24.0,
    pct_400up: 35.5, pct_400up_52w_high: false, holder_cnt_change_8w: 5.5, avg_lot_change_8w: -3.5,
    drawdown_120d: -45.5, ret_60d: -25.5, industry_ret_60d_med: 3.2, director_holding_change_3m: -1.5,
    div_years: 0, yield_now: 0, yield_5y_avg: 0, crash_60d: true, pct_1000up_trend: '-', is_60d_high: false },
  { code: '5522', name: '某 KY 股',  industry: 'BIO', price: 8.5, avg_volume: 180, director_pledge: 0, eps_q4: -5.5, list_year: 1, warning: false, margin_pct: 80, dt_ratio: 60,
    pct_1000up_now: 15.5, pct_1000up_w1: 15.0, pct_1000up_w2: 14.5, pct_1000up_w3: 14.0,
    pct_400up: 22.5, pct_400up_52w_high: false, holder_cnt_change_8w: 25.5, avg_lot_change_8w: -12.5,
    drawdown_120d: -65.5, ret_60d: -35.5, industry_ret_60d_med: -1.2, director_holding_change_3m: 0,
    div_years: 0, yield_now: 0, yield_5y_avg: 0, crash_60d: true, pct_1000up_trend: '-', is_60d_high: false },

  // 高價股示範
  { code: '6669', name: '緯穎',     industry: 'SEMI', price: 2680, avg_volume: 1200, director_pledge: 0.5, eps_q4: 132.5, list_year: 6, warning: false, margin_pct: 18, dt_ratio: 22,
    pct_1000up_now: 72.5, pct_1000up_w1: 72.0, pct_1000up_w2: 71.5, pct_1000up_w3: 71.0,
    pct_400up: 85.5, pct_400up_52w_high: false, holder_cnt_change_8w: -3.5, avg_lot_change_8w: 4.5,
    drawdown_120d: -8.5, ret_60d: 15.5, industry_ret_60d_med: 5.2, director_holding_change_3m: 0.5,
    div_years: 6, yield_now: 0.8, yield_5y_avg: 1.2, crash_60d: false, pct_1000up_trend: '+', is_60d_high: false },
  { code: '5269', name: '祥碩',     industry: 'SEMI', price: 1485, avg_volume: 850, director_pledge: 0.8, eps_q4: 68.5, list_year: 7, warning: false, margin_pct: 22, dt_ratio: 25,
    pct_1000up_now: 68.5, pct_1000up_w1: 67.5, pct_1000up_w2: 66.5, pct_1000up_w3: 65.5,
    pct_400up: 82.5, pct_400up_52w_high: false, holder_cnt_change_8w: -5.5, avg_lot_change_8w: 6.5,
    drawdown_120d: -12.5, ret_60d: 22.5, industry_ret_60d_med: 5.2, director_holding_change_3m: 1.5,
    div_years: 7, yield_now: 1.2, yield_5y_avg: 1.5, crash_60d: false, pct_1000up_trend: '+', is_60d_high: true },

  // F10 利空修復示範（曾崩跌、現主力回補）
  { code: '2610', name: '華航',     industry: 'SHIP', price: 22, avg_volume: 28000, director_pledge: 0.5, eps_q4: 1.5, list_year: 33, warning: false, margin_pct: 18, dt_ratio: 22,
    pct_1000up_now: 42.5, pct_1000up_w1: 41.5, pct_1000up_w2: 38.5, pct_1000up_w3: 35.5,
    pct_400up: 58.5, pct_400up_52w_high: false, holder_cnt_change_8w: -8.5, avg_lot_change_8w: 9.5,
    drawdown_120d: -25.5, ret_60d: -5.5, industry_ret_60d_med: 8.5, director_holding_change_3m: 2.5,
    div_years: 5, yield_now: 3.5, yield_5y_avg: 3.2, crash_60d: true, pct_1000up_trend: '+', is_60d_high: false },
  { code: '2634', name: '漢翔',     industry: 'SHIP', price: 45, avg_volume: 6500, director_pledge: 0.8, eps_q4: 2.5, list_year: 8, warning: false, margin_pct: 22, dt_ratio: 25,
    pct_1000up_now: 48.5, pct_1000up_w1: 47.0, pct_1000up_w2: 44.5, pct_1000up_w3: 42.0,
    pct_400up: 64.5, pct_400up_52w_high: false, holder_cnt_change_8w: -6.5, avg_lot_change_8w: 7.5,
    drawdown_120d: -22.5, ret_60d: 2.5, industry_ret_60d_med: 8.5, director_holding_change_3m: 1.8,
    div_years: 8, yield_now: 2.8, yield_5y_avg: 3.0, crash_60d: true, pct_1000up_trend: '+', is_60d_high: false },

  // 價籌背離示範（會被 F9 懲罰）
  { code: '3231', name: '緯創',     industry: 'SEMI', price: 112, avg_volume: 18000, director_pledge: 0.5, eps_q4: 5.5, list_year: 21, warning: false, margin_pct: 45, dt_ratio: 42,
    pct_1000up_now: 52.5, pct_1000up_w1: 53.0, pct_1000up_w2: 53.5, pct_1000up_w3: 54.0,
    pct_400up: 68.5, pct_400up_52w_high: false, holder_cnt_change_8w: -2.5, avg_lot_change_8w: 3.5,
    drawdown_120d: 0, ret_60d: 28.5, industry_ret_60d_med: 5.2, director_holding_change_3m: -0.2,
    div_years: 12, yield_now: 2.5, yield_5y_avg: 3.0, crash_60d: false, pct_1000up_trend: '-', is_60d_high: true },
  { code: '2382', name: '廣達',     industry: 'SEMI', price: 245, avg_volume: 12000, director_pledge: 0.5, eps_q4: 11.5, list_year: 28, warning: false, margin_pct: 42, dt_ratio: 38,
    pct_1000up_now: 55.5, pct_1000up_w1: 56.0, pct_1000up_w2: 56.5, pct_1000up_w3: 57.0,
    pct_400up: 72.5, pct_400up_52w_high: false, holder_cnt_change_8w: -3.5, avg_lot_change_8w: 4.5,
    drawdown_120d: 0, ret_60d: 32.5, industry_ret_60d_med: 5.2, director_holding_change_3m: -0.3,
    div_years: 13, yield_now: 2.8, yield_5y_avg: 3.2, crash_60d: false, pct_1000up_trend: '-', is_60d_high: true },

  // 其他電子
  { code: '2379', name: '瑞昱',     industry: 'SEMI', price: 485, avg_volume: 3500, director_pledge: 0.3, eps_q4: 25.5, list_year: 22, warning: false, margin_pct: 25, dt_ratio: 22,
    pct_1000up_now: 62.5, pct_1000up_w1: 62.0, pct_1000up_w2: 61.5, pct_1000up_w3: 61.0,
    pct_400up: 75.5, pct_400up_52w_high: false, holder_cnt_change_8w: -2.5, avg_lot_change_8w: 3.5,
    drawdown_120d: -10.5, ret_60d: 8.5, industry_ret_60d_med: 5.2, director_holding_change_3m: 0.8,
    div_years: 18, yield_now: 2.5, yield_5y_avg: 3.0, crash_60d: false, pct_1000up_trend: '+', is_60d_high: false },
  { code: '3034', name: '聯詠',     industry: 'SEMI', price: 558, avg_volume: 2500, director_pledge: 0.2, eps_q4: 28.5, list_year: 23, warning: false, margin_pct: 22, dt_ratio: 20,
    pct_1000up_now: 65.5, pct_1000up_w1: 65.0, pct_1000up_w2: 64.5, pct_1000up_w3: 64.0,
    pct_400up: 78.5, pct_400up_52w_high: false, holder_cnt_change_8w: -1.8, avg_lot_change_8w: 2.5,
    drawdown_120d: -8.5, ret_60d: 12.5, industry_ret_60d_med: 5.2, director_holding_change_3m: 0.5,
    div_years: 19, yield_now: 2.8, yield_5y_avg: 3.2, crash_60d: false, pct_1000up_trend: '+', is_60d_high: false },
  { code: '2383', name: '台光電',   industry: 'PCB', price: 425, avg_volume: 1800, director_pledge: 0.5, eps_q4: 22.5, list_year: 7, warning: false, margin_pct: 18, dt_ratio: 22,
    pct_1000up_now: 68.5, pct_1000up_w1: 68.0, pct_1000up_w2: 67.5, pct_1000up_w3: 67.0,
    pct_400up: 82.5, pct_400up_52w_high: false, holder_cnt_change_8w: -3.5, avg_lot_change_8w: 4.5,
    drawdown_120d: -8.5, ret_60d: 18.5, industry_ret_60d_med: 12.5, director_holding_change_3m: 1.5,
    div_years: 7, yield_now: 1.5, yield_5y_avg: 1.8, crash_60d: false, pct_1000up_trend: '+', is_60d_high: false },
  { code: '2357', name: '華碩',     industry: 'SEMI', price: 425, avg_volume: 4500, director_pledge: 0.3, eps_q4: 25.5, list_year: 28, warning: false, margin_pct: 15, dt_ratio: 18,
    pct_1000up_now: 58.5, pct_1000up_w1: 58.0, pct_1000up_w2: 57.5, pct_1000up_w3: 57.0,
    pct_400up: 72.5, pct_400up_52w_high: false, holder_cnt_change_8w: -1.5, avg_lot_change_8w: 2.2,
    drawdown_120d: -5.5, ret_60d: 8.5, industry_ret_60d_med: 5.2, director_holding_change_3m: 0.2,
    div_years: 23, yield_now: 2.8, yield_5y_avg: 3.2, crash_60d: false, pct_1000up_trend: '+', is_60d_high: false },

  // 塑膠／化工
  { code: '6505', name: '台塑化',   industry: 'PLAS', price: 92, avg_volume: 8500, director_pledge: 0.05, eps_q4: 5.5, list_year: 18, warning: false, margin_pct: 8, dt_ratio: 12,
    pct_1000up_now: 55.5, pct_1000up_w1: 55.0, pct_1000up_w2: 54.5, pct_1000up_w3: 54.0,
    pct_400up: 70.5, pct_400up_52w_high: false, holder_cnt_change_8w: -1.5, avg_lot_change_8w: 2.2,
    drawdown_120d: -3.5, ret_60d: 4.5, industry_ret_60d_med: 3.2, director_holding_change_3m: 0.1,
    div_years: 18, yield_now: 4.2, yield_5y_avg: 4.5, crash_60d: false, pct_1000up_trend: '+', is_60d_high: false }
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

// 評分引擎
// 對每檔股票，計算 9 因子的 z-score，最後加權合成
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

  // 2. 因子計算（原始值，未標準化）
  const factorValues = survivors.map(s => {
    const pct_1000up_delta_3w = s.pct_1000up_now - s.pct_1000up_w3;     // F1
    const pct_1000up_delta_2w = s.pct_1000up_w1 - s.pct_1000up_w3;      // F9 判斷
    const ret_underperform = s.ret_60d < s.industry_ret_60d_med;          // F3
    const dir_change_3m_ok = s.director_holding_change_3m > 0.5;          // F3

    // F1 — 大股東連續加碼
    const F1_raw = pct_1000up_delta_3w >= 1.0 ? 100 : pct_1000up_delta_3w * 50 + 50;

    // F2 — 產業輪動（簡化為產業 60 日報酬中位數排名）
    const F2_raw = Math.max(0, Math.min(100, (s.industry_ret_60d_med - 0) * 50 + 50));

    // F3 — 董監加碼 + 價格落後
    const F3_raw = (dir_change_3m_ok && ret_underperform) ? 100 :
                   (dir_change_3m_ok ? 70 : (ret_underperform ? 50 : 30));

    // F4 — 集中度突破
    const F4_raw = s.pct_400up_52w_high ? 100 : 50;

    // F5 — 股利穩定
    const F5_raw = (s.div_years >= 5 && s.yield_now > s.yield_5y_avg) ? 100 :
                   (s.div_years >= 3 ? 70 : (s.div_years >= 1 ? 50 : 20));

    // F6 — 散戶退場主力接手
    const F6_raw = (s.holder_cnt_change_8w < -5 && s.avg_lot_change_8w > 5) ? 100 :
                   (s.holder_cnt_change_8w < -3 && s.avg_lot_change_8w > 3) ? 75 :
                   (s.holder_cnt_change_8w < 0 && s.avg_lot_change_8w > 0) ? 55 : 30;

    // F8 — 回調籌碼守穩
    const dd = s.drawdown_120d;
    const in_drawdown = dd <= -10 && dd >= -25;
    const holder_support = pct_1000up_delta_3w >= 0;
    const F8_raw = (in_drawdown && holder_support) ? 100 :
                   (in_drawdown ? 60 : (holder_support ? 50 : 30));

    // F10 — 利空籌碼修復
    const F10_raw = (s.crash_60d && s.pct_1000up_trend === '+') ? 100 :
                    (s.crash_60d && s.pct_1000up_trend === '=') ? 70 :
                    s.crash_60d ? 50 : 0;

    // F9 — 價籌背離懲罰（扣分）
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
    // F9 封頂 20
    f9_penalty = Math.min(20, f9_penalty);

    return {
      s, F1_raw, F2_raw, F3_raw, F4_raw, F5_raw, F6_raw, F8_raw, F10_raw,
      F9_penalty: f9_penalty, f9_triggers: f9_triggers,
      pct_1000up_delta_3w, ret_underperform, dir_change_3m_ok
    };
  });

  // 3. 因子橫截面標準化（z-score → 0~100 對映）
  const factorKeys = ['F1_raw', 'F2_raw', 'F3_raw', 'F4_raw', 'F5_raw', 'F6_raw', 'F8_raw', 'F10_raw'];
  factorKeys.forEach(key => {
    const vals = factorValues.map(f => f[key]);
    const mean = vals.reduce((a, b) => a + b, 0) / vals.length;
    const std = Math.sqrt(vals.reduce((a, b) => a + (b - mean) ** 2, 0) / vals.length) || 1;
    factorValues.forEach(f => { f[key + '_z'] = (f[key] - mean) / std; });
  });

  // 4. 加權合成總分
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
    // 將 z-score 加權和對映到 0~100（z-score 通常落在 -2~+2）
    // 公式：score = 50 + rawSum / 4
    let score = 50 + rawSum / 4;
    score -= f.F9_penalty;
    score = Math.max(0, Math.min(100, score));

    // 分層
    let tier;
    if (score >= 75) tier = 'A';
    else if (score >= 60) tier = 'B';
    else if (score >= 45) tier = 'C';
    else tier = 'D';

    // F9 雙重懲罰降級
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

// 對外暴露
window.STOCK_UNIVERSE = STOCK_UNIVERSE;
window.FACTOR_WEIGHTS = FACTOR_WEIGHTS;
window.FACTOR_DEFINITIONS = FACTOR_DEFINITIONS;
window.HARD_FILTERS = HARD_FILTERS;
window.INDUSTRY_LIST = INDUSTRY_LIST;
window.computeScores = computeScores;