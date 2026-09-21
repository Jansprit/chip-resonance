# Backend — 籌碼共振選股系統爬蟲管線

> ⚠️ **重要**：本目錄包含真實從台灣公開財經網站抓取資料的爬蟲。
> 每個資料源都有**嚴格的節流與退避設定**，目的是保護來源站點的可用性並避免 IP 被封鎖。
> **禁止**提高抓取頻率、**禁止**繞過驗證碼或反爬蟲機制、**禁止**對單一來源同時發出多個並行請求。

## 架構總覽

```
┌─────────────────────────────────────────────────────────────┐
│  Python Pipeline (backend/pipeline.py)                      │
│                                                             │
│   公開 API 源 (無認證)                                       │
│   ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  │
│   │twse.py   │  │tpex.py   │  │finmind.py│  │mops.py   │  │
│   │3s 節流   │  │3s 節流   │  │5s 節流   │  │8s 節流   │  │
│   └─────┬────┘  └─────┬────┘  └─────┬────┘  └─────┬────┘  │
│                                                             │
│   Playwright 源 (需登入，需先 auth_setup)                    │
│   ┌──────────┐  ┌──────────┐  ┌──────────┐                 │
│   │tdcc.py   │  │pyramid.py│  │goodinfo.py│                 │
│   │20s 節流  │  │10s 節流  │  │15s 節流  │                 │
│   │集保中心  │  │神秘金字塔│  │可選代理  │                 │
│   └─────┬────┘  └─────┬────┘  └─────┬────┘                 │
│         ▼             ▼             ▼                        │
│   ┌─────────────────────────────────────────────┐          │
│   │ normalize.py (欄位統一 → STOCK_UNIVERSE)     │          │
│   └─────────────────┬───────────────────────────┘          │
│                     ▼                                       │
│   ┌─────────────────────────────────────────────┐          │
│   │ schema.py (pydantic 驗證)                      │          │
│   └─────────────────┬───────────────────────────┘          │
│                     ▼                                       │
│   data/                                                      │
│   ├── latest/        ← 當前（前端讀）                       │
│   └── YYYY-MM-DD/    ← 每日快照（90 天後自動歸檔）           │
│                                                             │
│   data/local/        ← 私有完整資料（不推 git）              │
└─────────────────────────────────────────────────────────────┘
```

## 結構

```
backend/
├── requirements.txt
├── README.md                        ← 本檔
├── scrapers/
│   ├── base.py                      ← RateLimiter / RetryPolicy / SourceHealth / HttpClient
│   │                                    BrowserSession (Playwright + stealth) / CredentialManager
│   │                                    SessionStore (cookie 持久化) / taipei_now_iso / taipei_today
│   ├── twse.py                      ← 證交所 OpenAPI (1082 stocks, 135 indices)
│   ├── tpex.py                      ← 櫃買中心 OpenAPI (891 stocks, Big5)
│   ├── finmind.py                   ← FinMind REST (可選 token)
│   ├── mops.py                      ← 公開資訊觀測站 (2024 改版，graceful skip)
│   ├── tdcc.py                      ← 集保中心 (Playwright)
│   ├── pyramid.py                   ← 神秘金字塔 (Playwright + session cookie)
│   ├── goodinfo.py                  ← Goodinfo (Playwright + 可選住宅代理)
│   └── us_markets.py                ← 美股 hook (FINNHUB/ALPHA_VANTAGE/TWELVE_DATA/FRED)
├── schema.py                        ← pydantic models + JSON Schema
├── normalize.py                     ← 欄位對齊 + industry hint
├── pipeline.py                      ← 7 源 orchestrator
├── scripts/
│   ├── run_local.py                 ← 本地手動跑
│   ├── build_universe.py            ← 合併 TWSE + TPEx 價格到 demo_subset
│   ├── auth_setup.py                ← CLI: Playwright 開瀏覽器讓使用者登入
│   ├── windows_task.ps1             ← Windows Task Scheduler 註冊腳本
│   └── rotate_snapshots.py          ← 90 天快照歸檔腳本
└── tests/
    ├── test_rate_limiter.py         ← 3 個節流閥測試
    └── test_normalize.py            ← 12 個欄位對齊測試
```

## 節流預設

| 來源 | 最低間隔 | 單日上限 | 失敗退避 | 認證需求 |
|---|---|---|---|---|
| TWSE OpenAPI | 3 秒 | 500 次 | 60s / 300s | 無 |
| TPEx OpenAPI | 3 秒 | 500 次 | 60s / 300s | 無 |
| FinMind | 5 秒 | 200 次 | 60s / 180s | 可選 token |
| MOPS | 8 秒 | 100 次 | 90s / 300s | 無（2024 改版後端點失效）|
| 集保 (TDCC) | 20 秒 | 30 次 | 120s / 600s | 需先 auth_setup 登入 |
| 神秘金字塔 | 10 秒 | 200 次 | 90s / 600s | 需先 auth_setup 登入 |
| Goodinfo | 15 秒 | 60 次 | 120s / 600s | 需先 auth_setup 登入 + 可選住宅代理 |

## 本地執行

### 1. 第一次安裝

```powershell
cd E:\MiniMax_Desktop\Work01\chip_resonance
python -m venv backend\.venv
backend\.venv\Scripts\activate
pip install -r backend\requirements.txt
playwright install chromium
```

### 2. 設定可選憑證

```bash
# 複製範本，填入實際值
cp backend/.env.example backend/.env
vi backend/.env
```

可選設定：
- `FINMIND_TOKEN` — 啟用 FinMind 完整功能（月營收、財報、還原股價）
- `PYRAMID_USERNAME` / `PYRAMID_PASSWORD` — 加速首次登入（仍需走 auth_setup）
- `GOODINFO_USERNAME` / `GOODINFO_PASSWORD` — 同上
- `GOODINFO_PROXY_URL` — 住宅代理（避免本機 IP 被擋）

### 3. 登入需要 Playwright 的網站（一次性）

```powershell
# 神秘金字塔（需訂閱帳號）
python -m backend.scripts.auth_setup --site pyramid

# Goodinfo（需付費會員）
python -m backend.scripts.auth_setup --site goodinfo

# 集保中心（可選登入；公開資料不一定要）
python -m backend.scripts.auth_setup --site tdcc
```

每個指令會：
1. 開啟 headed Chromium 瀏覽器
2. 導航到登入頁
3. 等待您手動登入完成
4. 自動存 `backend/.sessions/<site>.json`

### 4. 跑 pipeline

```powershell
# 只跑公開源（TWSE + TPEx + FinMind + MOPS，~3 分鐘）
python -m backend.scripts.run_local --source public

# 跑全部（~30-60 分鐘，含 Playwright 源）
python -m backend.scripts.run_local --source all

# 只跑單一來源
python -m backend.scripts.run_local --source twse
python -m backend.scripts.run_local --source pyramid
```

### 5. 註冊 Windows 排程

```powershell
# 以系統管理員身份
.\backend\scripts\windows_task.ps1 -Register

# 立即跑一次完整 pipeline
.\backend\scripts.windows_task.ps1 -RunNow -Source all
```

排程內容：
- 週一至週五 13:35 跑 public 子集
- 週五 14:35 跑完整 pipeline

### 6. 部署到 Docker / Synology NAS

```bash
# 1. 編輯 .env
cp backend/.env.example backend/.env && vi backend/.env

# 2. 構建並啟動
docker compose build
docker compose up -d

# 3. 查看日誌
docker compose logs -f
```

## 部署到 Synology NAS（Container Manager）

1. SSH 進入 NAS
2. `git clone https://github.com/Jansprit/chip-resonance.git`
3. 在 Container Manager 中匯入 `docker-compose.yml`
4. 設定排程（Container Manager 內建 cron 或 ssh 進去用 crontab）

## 資料輸出

| 檔案 | 內容 | 大小 |
|---|---|---|
| `data/latest/prices.json` | TWSE 上市 1082 檔當日收盤 | ~290 KB |
| `data/latest/tpex_prices.json` | TPEx 上櫃 891 檔當日收盤 | ~270 KB |
| `data/latest/market_index.json` | 135 個主指數與類股指數 | ~14 KB |
| `data/latest/universe.json` | TWSE + TPEx 全市場 1973 檔 | ~370 KB |
| `data/latest/demo_subset.json` | 43 檔示範個股（含所有 chip 欄位）| ~36 KB |
| `data/latest/meta.json` | 各源狀態、節流配額、最後更新時間 | ~1.5 KB |
| `data/YYYY-MM-DD/*.json` | 每日快照（90 天後自動歸檔到 `_archive/`） |

前端（GitHub Pages）只讀 `data/latest/`。

## 測試

```bash
# 跑所有單元測試
python backend/tests/test_rate_limiter.py
python backend/tests/test_normalize.py

# CI 自動跑
gh run watch
```

## 故障排除

### TPEx 報錯 "Response ended prematurely"

可能原因：連續請求太頻繁被伺服器中斷。已內建 3 秒節流；若仍發生，可暫時跳過 TPEx。

### Playwright 來源被偵測為 bot

- 確保已跑 `auth_setup.py` 完成手動登入
- 必要時提供住宅代理：`GOODINFO_PROXY_URL=http://user:pass@host:port`
- 集保 / 神秘金字塔：每週只抓一次（已是週資料）

### 401 / 403 / 429

- `RateLimiter` 會自動停用該來源當日抓取
- 寫入 `data/latest/meta.json` 的 `disabled_sources` 陣列
- 下次手動觸發或排程會自動重試

## 開發規範

1. **不修改 `RateLimiter` 預設值**（3 秒是最低保護線）
2. **不要寫死憑證**到任何 .py 檔；一律從 `CredentialManager` 讀 `.env`
3. **新增 scraper 時**：
   - 實作 `HttpClient` + `RateLimiter` + `SourceHealth`
   - 提供 `fetch_*()` 函式（純資料抓取）與 `save_latest()` 函式（JSON 寫入）
   - 在 `pipeline.py` 加對應的 `run_*()` runner
4. **修改現有 scraper**前：先抓取真實 HTML 存到 `data/local/raw/<site>/`，再 tune selector