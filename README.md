# 籌碼共振選股系統 (Chip-Resonance Selection System)

> 「籌碼面為主軸、基本面為濾網、產業面為權重、背離訊號為懲罰」的多因子選股模型
> 從神秘金字塔、集保中心、Goodinfo、TWSE 等多源抓取真實台股籌碼資料，產出可實際操作的選股清單

---

## 目錄

1. [系統簡介](#系統簡介)
2. [如何使用本專案](#如何使用本專案)
   - [快速開始（瀏覽器版）](#快速開始瀏覽器版)
   - [取得真實股票數據](#取得真實股票數據)
   - [用真實數據進行篩選](#用真實數據進行篩選)
3. [9 大因子](#9-大因子)
4. [核心架構](#核心架構)
5. [檔案結構](#檔案結構)
6. [驗證框架](#驗證框架)
7. [授權](#授權)

---

## 系統簡介

本系統整合 8 個資料源（TWSE 上市、TPEx 上櫃、FinMind、MOPS、玩股網、集保、神秘金字塔、Goodinfo），抓取真實的台股籌碼與行情資料，以 **9 大因子 + 6 條硬性過濾層** 組成可量化、可回測驗證的台股選股模型。**其中 5 個來源完全免登入**（TWSE / TPEx / 集保 / 玩股網 / 神秘金字塔），僅 Goodinfo 進階資料與 FinMind 大戶分級需登入。

### 三大核心原則

1. **籌碼共振** — 當大戶連續加碼、董監同步進場、散戶退場三者同向時，視為「籌碼集中」訊號。
2. **背離懲罰** — 當股價創新高但大戶退場、或當沖比過熱時，主動扣分，避免追高陷阱。
3. **可驗證** — 所有資料標記 T+3 公布時點，Walk-Forward 滾動驗證，因子 IC 自我淘汰。

---

## 如何使用本專案

### 🚀 快速開始（瀏覽器版）

最快的方式：直接打開網站，所有操作在瀏覽器完成。

#### A. 線上版（GitHub Pages）

開啟 **https://jansprit.github.io/chip-resonance/**，直接使用。

#### B. 本機版（Windows）

1. 下載或 clone 此專案：
   ```powershell
   git clone https://github.com/Jansprit/chip-resonance.git
   cd chip_resonance
   ```

2. 用瀏覽器開啟 `index.html`（雙擊即可）

3. 切換到「評分模擬器」分頁，畫面會自動載入 `data/latest/` 的真實資料
   - 若 `data/latest/` 沒有資料，會載入示意資料（仍可操作但分數僅供參考）

> **注意**：本機版若用 `file://` 開啟，部分瀏覽器對 fetch 的同源政策可能阻擋，建議：
> ```powershell
> # Python 啟動本機 server
> python -m http.server 8000
> # 然後瀏覽器開 http://localhost:8000/
> ```

---

### 📊 取得真實股票數據

> **為什麼需要這步？** `data/latest/` 預設只有示意資料。要拿真實的 TWSE/TPEx 行情與 1082+891 檔個股，必須跑一次後端 pipeline。

#### 步驟 1：安裝 Python 環境（推薦 3.10+）

```powershell
# 確認 Python 已安裝
python --version
# 若未安裝，到 https://www.python.org/downloads/ 下載

# 建立虛擬環境
cd E:\MiniMax_Desktop\Work01\chip_resonance
python -m venv .venv
.venv\Scripts\activate

# 安裝依賴
pip install -r backend\requirements.txt
playwright install chromium
```

#### 步驟 2：（可選）設定可選憑證

複製範本：
```powershell
copy backend\.env.example backend\.env
notepad backend\.env
```

| 變數 | 來源 | 影響 | 是否必填 |
|---|---|---|---|
| `FINMIND_TOKEN` | [FinMind 官網](https://finmindtrade.com/) 申請 | 提升 rate limit（600/hr）| 否（沒 token 也能跑，但速率較低）|
| `FINMIND_PAID` | FinMind 付費訂閱 | 解鎖 `TaiwanStockShareholding` 大戶持股分級 | 否（付費才有 F1/F4/F6 真實值）|
| `PYRAMID_USERNAME/PASSWORD` | ~~神秘金字塔~~ | **2026-09 修正：不需登入**，基本資料免登入可看 | 否 |
| `GOODINFO_USERNAME/PASSWORD` | Goodinfo 免費會員 | 登入後能看到董監加碼明細等進階資料 | 否（基本免登入）|
| `GOODINFO_PROXY_URL` | 住宅代理 | 避免本機 IP 被擋 | 否（看您網路環境）|

### 哪些來源不必登入？

> ⚠️ **2026-09 重要修正**：先前以為「神秘金字塔必須登入」其實是錯的。

| 來源 | 登入需求 | 備註 |
|---|---|---|
| **TWSE OpenAPI** | ❌ | 全部公開 |
| **TPEx OpenAPI** | ❌ | 全部公開 |
| **集保中心 (TDCC)** | ❌ | 週資料公開可下載 |
| **FinMind 免費層** | ❌ | 價格、月營收、財報、股利、三大法人 |
| **神秘金字塔 (Pyramid)** | ⚠️ **修正：免登入** | 400/600/800/1000 張大戶分級、董監持股都可免登入瀏覽器查看；只是有 Cloudflare 防護需用 Playwright |
| **玩股網 (Wantgoo)** | ❌ | 融資券、當沖比、法人買賣超都免登入；同樣需 Playwright 過 Cloudflare |
| **Goodinfo** | ❌（基本免登入）| 基本個股資料免登入；登入後能看到董監加碼、融資券、當沖比明細 |
| **FinMind `TaiwanStockShareholding`** | ❌ 登入，但 ✅ **付費訂閱**才能看 | 真正的大戶 400/600/800/1000 張歷史分級 |
| **MOPS 董監事申報** | ⚠️ 需「公司內部人」自然人憑證 / 工商憑證 | 一般投資人拿不到 |

**沒設定也沒關係**——pipeline 會自動 skip 沒憑證的來源，繼續抓其他公開源。

#### 步驟 3：跑 pipeline

```powershell
# 只跑公開源（TWSE + TPEx + FinMind + MOPS），約 3 分鐘
python -m backend.scripts.run_local --source public

# 跑全部源（含 Playwright 來源，需先登入），約 30-60 分鐘
python -m backend.scripts.run_local --source all

# 只跑單一來源
python -m backend.scripts.run_local --source twse
python -m backend.scripts.run_local --source pyramid
```

跑完會看到類似：
```
[1/7] TWSE OpenAPI ...
    {'status': 'ok', 'stocks_count': 1082, 'indices_count': 135, ...}
[2/7] TPEx OpenAPI ...
    {'status': 'ok', 'stocks_count': 891, ...}
[3/7] FinMind ...
    {'status': 'skipped', 'reason': 'FINMIND_TOKEN not set'}
[4/7] MOPS ...
    {'status': 'skipped', 'reason': 'MOPS endpoint migrated in 2024'}
=== done (2026-09-22T...) ===
```

#### 步驟 4：（可選）登入需登入的網站

> ⚠️ **2026-09 修正**：神秘金字塔與玩股網**免登入**就能用 Playwright 抓。只有**部分** Goodinfo 進階功能才需登入。

Goodinfo 進階資料需要登入時，**首次跑需要手動登入一次**：

```powershell
python -m backend.scripts.auth_setup --site goodinfo
# 開啟瀏覽器 → 手動登入 → session 自動存到 backend/.sessions/
```

> 第一次執行會開啟 headed browser 視窗（不是無頭），讓您手動輸入帳密。完成後 session cookie 會加密存到 `backend/.sessions/<site>.json`，下次跑就自動登入。

#### 步驟 5：把結果 commit + push

```powershell
git add data/latest/
git commit -m "data: refresh real snapshot"
git push origin main
```

> GitHub Actions 也會在每個交易日 13:30 自動跑（`scrape.yml` 排程）。

#### 步驟 6：排程自動化

**Windows Task Scheduler**：
```powershell
.\backend\scripts\windows_task.ps1 -Register
```
會建立兩個排程：
- 週一至週五 13:35 → 公開子集
- 週五 14:35 → 完整 pipeline

**Linux / Synology NAS**（Docker）：
```bash
docker compose up -d
# 容器會依 cron 自動跑
```

---

### 🎯 用真實數據進行篩選

數據更新後（`data/latest/` 已有最新 JSON），打開 `scoring.html`：

1. **頁面自動載入最新資料**
   - 底部橫幅會顯示「📊 真實資料來源：TWSE OpenAPI / 最後更新時間」
   - 7 個來源的狀態（✓ TWSE / ✓ TPEx / ⏭ FinMind / ⏭ MOPS / ⏭ TDCC / ⏭ Pyramid / ⏭ Goodinfo）

2. **看 Tier 總覽**
   - A 級（≥75 分）：核心候選，股價站上 20 日均線可進場
   - B 級（60-75）：觀察倉，等因子強化
   - C/D 級：暫不考慮

3. **用篩選器深入挖掘**
   - 「產業」下拉：只看好半導體、金融、航運等
   - 「顯示被過濾個股」打勾：看到被 6 條硬性過濾淘汰的個股（流動性差、質押過高、累計虧損等）

4. **看個股評分明細**
   - 表格列出每檔個股的 9 個因子分數（F1/F2/F3/F4/F5/F6/F8/F10 為加分；F9 為扣分）
   - F9 觸發 ≥2 項會自動降級（即使總分高）

5. **看圖表分析**
   - 「產業 × Tier 分布」：各產業的 A/B/C/D 個股數
   - 「分數區間分布」：所有個股的分數分布
   - 「因子權重分配」：各因子的權重占比

#### 篩選 → 進場 → 出場流程

```
Step 1: 看 A 級個股
   ↓
Step 2: 確認個股站上 20 日均線（圖表上看 drawdown 接近 0）
   ↓
Step 3: 檢查 F9 觸發（融資券、當沖比過熱 = 不要追）
   ↓
Step 4: 分兩批建倉（單檔部位上限 15%、單一產業 30%）
   ↓
Step 5: 持有期間監控：F1 連續加碼中斷 + F9 觸發 → 強制出場
   ↓
Step 6: 停損 -12% 或 ATR(14)*2.5（取較近者）
```

---

## 9 大因子

| 代號 | 因子 | 方向 | 權重 | 真實資料源 |
|---|---|---|---|---|
| F1 | 大股東連續加碼 | 加分 | 20% | 神秘金字塔 / 集保 |
| F2 | 產業輪動 | 加分 | 10% | TWSE + 集保 |
| F3 | 董監加碼價格落後 | 加分 | 15% | Goodinfo / MOPS |
| F4 | 集中度突破 | 加分 | 10% | 集保 / 神秘金字塔 |
| F5 | 股利穩定 | 加分 | 10% | FinMind / Goodinfo |
| F6 | 散戶退場主力接手 | 加分 | 15% | 集保 |
| F8 | 回調籌碼守穩 | 加分 | 10% | TWSE + 集保 |
| F10 | 利空籌碼修復 | 加分 | 5% | 集保 + 神秘金字塔 |
| F9 | 價籌背離懲罰 | **扣分** | -20% 封頂 | TWSE + Goodinfo |

### 評分公式

```
Score = Σ wi·zi - Penalty_F9
```

- `zi` 為各因子經過橫截面標準化（z-score）後的數值
- 輸出四層：
  - **A 級**（≥75）：核心候選，進入買進評估
  - **B 級**（60-75）：觀察倉，等因子強化或股價確認
  - **C 級**（45-60）：中性池
  - **D 級**（<45 或 F9 觸發 ≥2 項）：剔除

### 硬性過濾（先排除，不評分）

任一觸發即剔除，不進入評分：

1. 日均成交量 20 日 < 500 張（流動性不足）
2. 董監質押率 > 50%（護盤假象）
3. 最近四季累計 EPS < 0（策略 #10 除外）
4. 屬於警示股、全額交割股、暫停交易
5. 上市未滿 2 年（無足夠籌碼歷史）
6. 股價 < 10 元（雞蛋水餃股的假集中）

---

## 核心架構

```
┌─────────────────────────────────────────────────────────────┐
│  Python Pipeline (backend/pipeline.py)                      │
│                                                             │
│  公開 API (無認證)        Playwright 源 (需登入)              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐                 │
│  │twse.py   │  │tpex.py   │  │tdcc.py   │ 神秘金字塔         │
│  │1082 檔   │  │891 檔    │  │集保中心  │ pyramid.py         │
│  └──────────┘  └──────────┘  └──────────┘                 │
│  ┌──────────┐  ┌──────────┐                                │
│  │finmind.py│  │mops.py   │  Goodinfo (goodinfo.py)         │
│  └──────────┘  └──────────┘                                │
│         ▼                                                  │
│  ┌─────────────────────────────────┐                     │
│  │ normalize.py (欄位統一)         │                     │
│  │ schema.py (pydantic 驗證)        │                     │
│  └────────────────┬────────────────┘                     │
│                   ▼                                        │
│  data/                                                     │
│  ├── latest/         ← GitHub Pages 讀此處               │
│  │   ├── prices.json (TWSE 1082 檔)                      │
│  │   ├── tpex_prices.json (TPEx 891 檔)                  │
│  │   ├── market_index.json (135 指數)                    │
│  │   ├── demo_subset.json (43 示範股)                     │
│  │   ├── universe.json (1973 全市場)                     │
│  │   └── meta.json (各源狀態)                            │
│  └── YYYY-MM-DD/     ← 每日快照（90 天後歸檔）           │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│  Frontend (GitHub Pages)                                     │
│  - index.html      系統總覽                                  │
│  - factors.html    9 因子詳解                                │
│  - scoring.html    ★ 互動評分模擬器（用真實資料）            │
│  - backtest.html   回測 QA 閘門                              │
└─────────────────────────────────────────────────────────────┘
```

---

## 檔案結構

```
chip-resonance/
├── index.html                  系統總覽（架構圖、9 因子速覽）
├── factors.html                9 因子詳解頁
├── scoring.html                ★ 互動評分模擬器
├── backtest.html               回測 QA 閘門
├── data.js                     async loader（從 data/latest/ 載入）
├── app.js                      圖表 + Tier 渲染 + meta banner
├── styles.css                  神秘金字塔主題
├── .nojekyll                   禁用 GitHub Pages Jekyll 處理
│
├── backend/                    ★ Python pipeline
│   ├── scrapers/
│   │   ├── base.py             RateLimiter / RetryPolicy / SourceHealth
│   │   │                       BrowserSession (Playwright + stealth)
│   │   │                       CredentialManager / SessionStore
│   │   ├── twse.py             證交所 OpenAPI（1082 檔）
│   │   ├── tpex.py             櫃買中心 OpenAPI（891 檔）
│   │   ├── finmind.py          FinMind REST（可選 token）
│   │   ├── mops.py             公開資訊觀測站（2024 graceful skip）
│   │   ├── wantgoo.py          玩股網（融資券/當沖比/法人買賣超，**免登入**）
│   │   ├── tdcc.py             集保中心（Playwright，**免登入**）
│   │   ├── pyramid.py          神秘金字塔（Playwright，**免登入**）
│   │   ├── goodinfo.py         Goodinfo（Playwright + 可選代理）
│   │   └── us_markets.py       美股 hook（FINNHUB/AV/FRED）
│   ├── normalize.py            欄位對齊 + 行業歸類
│   ├── schema.py               pydantic models
│   ├── pipeline.py             8 源 orchestrator
│   ├── scripts/
│   │   ├── run_local.py        CLI 入口
│   │   ├── build_universe.py   合併 TWSE + TPEx
│   │   ├── auth_setup.py       Playwright 互動登入
│   │   ├── rotate_snapshots.py 90 天快照歸檔
│   │   └── windows_task.ps1    Windows Task Scheduler 註冊
│   ├── tests/                  28 個單元測試
│   ├── .env.example            所有可選憑證範本
│   ├── requirements.txt
│   └── README.md
│
├── data/                       GitHub Pages 用的公開 JSON
│   ├── latest/                 當前最新（前端讀這）
│   └── YYYY-MM-DD/              每日快照
│
├── .github/
│   ├── workflows/ci.yml        CI（28 個測試 + schema 驗證）
│   ├── workflows/scrape.yml    公開子集排程
│   └── ISSUE_TEMPLATE/
│
├── Dockerfile                  Synology NAS / Linux
├── docker-compose.yml           cron 容器
├── pyproject.toml               現代 Python 封裝
├── CHANGELOG.md                v0.1.0 → v0.2.0 演進
├── LICENSE                     MIT
└── README.md                   本檔
```

---

## 驗證框架

本專案參考另一份 `tabbit_交易策略回測驗證系統分析與優化建議.md` 的方法論，內建四大里程碑：

- **M1** 最小無偏差管線（黃金測試、前視偏差探針）
- **M2** 統計驗證工具箱（IC / PSR / DSR / CSCV-PBO）
- **M3** 流程基礎設施（預註冊、可重現性三元組、紅隊清單）
- **M4** 事件驅動覆核（容量曲線、模擬盤）

詳見 `backtest.html`。

---

## 常見問題

### Q: 跑 pipeline 後 meta.json 顯示某個來源是「skipped」？

正常現象。沒有該來源憑證就會自動跳過，不影響其他源。

### Q: 集保 / 神秘金字塔抓取失敗（429 / 403）？

被來源站暫時擋 IP。請：
1. 確認已跑 `auth_setup.py` 完成登入
2. 確認 `.env` 設了 `GOODINFO_PROXY_URL`（住宅代理）
3. 隔天再跑（每日配額會 reset）

### Q: MOPS 2024 改版後抓不到？

MOPS 改用 ajax 端點 `/mops/web/ajax_*`，本系統目前 `mops.py` 標 graceful skip。等日後確認新端點後更新即可。

### Q: 怎麼切換到 Private repo？

在 GitHub repo Settings → Danger Zone → Change visibility。但 Private repo 在 free plan 會**失去 GitHub Pages**（須 GitHub Pro 才能保留）。建議用 Vercel / Cloudflare Pages 替代。

### Q: FinMind token 怎麼拿？

到 [FinMind 官網](https://finmindtrade.com/) 註冊即可。**免費 token** 即可大幅提升 rate limit（每小時 600+ 次）。但若想要 `TaiwanStockShareholding`（大戶 400/600/800/1000 張持股分級）來填 F1/F4/F6 三個關鍵因子，則需**付費訂閱**（約 NTD $1,200/月）。

### Q: 三個來源（神秘金字塔 / Goodinfo / FinMind 大戶分級）真的都要付費嗎？

不一定。詳情：

| 來源 | 免費層 | 付費層 |
|---|---|---|
| **TWSE + TPEx OpenAPI** | ✅ 全部資料 | — |
| **集保中心 週資料** | ✅ 全市場週分布 | — |
| **FinMind 價格/營收/財報/股利** | ✅ 免費 token 即可 | — |
| **FinMind 大戶持股分級** | ❌ 需付費 | NTD ~$1,200/月 |
| **神秘金字塔** | ⚠️ 免費會員（需登入，額度有限）| 付費會員（無限額度）|
| **Goodinfo** | ⚠️ 免費會員（需登入）| 付費會員（更多資料）|
| **MOPS 董監事申報** | ❌ 需公司內部人憑證（一般投資人無權）| — |

**最低配置就能跑**：TWSE + TPEx + 集保（公開）+ FinMind 免費 token = F1/F4/F6 之外的 5 個因子都有真實值，F1/F4/F6 暫用集保的 400 張以上分布近似。

---

## 免責聲明

*本系統為研究與教學示範工具，**非投資建議**。所有資料來自台灣公開資訊源，已盡力確保節流與禮貌抓取。但使用本系統進行實際交易決策前，請務必：*

- *完成樣本外驗證（至少 6 個月）*
- *建立個人停損紀律*
- *了解所有資料源可能延遲或缺失*
- *對自己的投資決策負全責*

*內容由 AI 生成僅供參考。*

---

## 授權

本專案以 [MIT License](./LICENSE) 授權釋出。

## 貢獻

歡迎透過 [Issue](https://github.com/Jansprit/chip-resonance/issues) 回報 Bug 或提出新功能建議。
提交前請使用對應的 Issue 模板（🐛 Bug Report 或 ✨ Feature Request）。

開發流程：
1. Fork 此專案
2. 建立 feature branch（`git checkout -b feature/amazing-feature`）
3. 提交修改（`git commit -m 'Add some amazing feature'`）
4. Push 到分支（`git push origin feature/amazing-feature`）
5. 開啟 Pull Request

CI 將自動檢查 HTML、JavaScript、Python 與 28 個單元測試。