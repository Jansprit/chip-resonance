# Changelog

All notable changes to the 籌碼共振選股系統 (Chip-Resonance Selection System).

## [v0.3.0] — 2026-10-22 — 體檢報告修復 + 資料來源真正接通

本版依 [docs/2026-10-21-專案體檢報告.md](docs/2026-10-21-專案體檢報告.md)
逐項修復 15 個缺陷，並修掉報告本身沒看到的**森林層根因**。

### 🔴 根因修復（森林層）

- **資料來源從未進入評分引擎**
  v0.2.0 的 `build_universe.py` 只合併 TWSE / TPEx 價格，
  其餘 6 個來源抓回的資料全部停在各自的 JSON 裡 → 8/9 因子永遠是示意值。
  現在每個來源都有欄位映射與 provenance：
  集保開放平台 → `pct_1000up_*`、MOPS → `director_*`、MoneyDJ 週 K 線 → 價格衍生因子、
  產業 60 日報酬中位數（只用真實 `ret_60d` 計算）。
- **缺少資料來源契約**
  每個欄位現在都標記 `_provenance`（`real` / `illustrative`），
  只有輸入**全部**為真實的因子才能計算；
  「真實 now 混著示意 history」會被判定為不可用（否則會算出假 delta）。
- **缺少來源層驗證**
  CI 原本只驗 JSON 形狀、從不驗內容；schema 驗證器改為依檔名挑模型、
  驗證每一筆、未知型別直接 exit 1。

### ✅ 已修復的缺陷

| 編號 | 缺陷 | 修法 |
|---|---|---|
| BUG-01 | TDCC 合併把 `pct_1000up_w1/w2/w3` 覆寫成 `undefined` → 39/39 個股分數 NaN | 原子合併 + provenance 感知 + `safeNum()` + 權重重新分配 |
| BUG-02 | MOPS 端點 `mops.twse.com.tw/.../t146sb05` → 302 → 65 bytes 錯誤頁 | 改用 `mopsov.twse.com.tw/mops/web/ajax_stapap1`，純 HTTP、不需 cookie，實作解析器 |
| BUG-03 | 玩股網 4 個 URL 全部 404 | 修正頁面路徑；實作兩層表頭解析器；API 被封鎖時誠實回報而非填 0 |
| BUG-04 | `tdcc_opendata` 從未在 CI 執行 | 納入 `public` 集合 |
| BUG-05 | `requirements.txt` 缺 playwright | 補上 playwright / beautifulsoup4 / lxml |
| BUG-06 | 905KB 私有 TDCC 歷史被提交進公開倉庫 | 移出版控 + `.gitignore` 全面加強 |
| BUG-07 | 6 個 schema 驗證有 5 個帶 `\|\| true` | 移除 `\|\| true`，並強化驗證器本身 |
| BUG-08 | cron 在 6 分鐘窗口內最多執行 6 次 | 改用日期命名的 lock 檔，每窗口每天只跑一次 |
| BUG-09 | 缺 `.dockerignore` | 新增，排除 `.git` / 私有資料 / 大檔 |
| BUG-10 | `meta.json` 只列有跑的來源 | 固定列出全部 8 來源，未跑的標 `not_run` |
| BUG-11 | `parse_holder_csv_to_pct_per_stock` 靠變數遮蔽才剛好是 O(n) | 改成明確的 O(n) 契約 + 說明 |
| BUG-12 | 兩套 sys.path 策略混用 | 全部統一為 repo root + `backend.*` |
| BUG-13 | `PIPELINE_LIMIT` / `PYRAMID_*` / `GOODINFO_*` 死設定 | `PIPELINE_LIMIT` 真的接上；死憑證移除，改回報真實的 session 狀態 |
| BUG-14 | 欄位沒有來源標記 | `_provenance` + 前端資料品質徽章 + demo/strict 橫幅 |
| BUG-15 | 沒有可靠的真實/示意區分 | strict / demo 兩種評分模式 |
| BUG-16 | README 宣稱「9 大因子完整實作」 | 因子表改成列出實際所需輸入、來源與實測狀態 |
| BUG-17 | `build_universe.py` 讀自己的輸出 | 改讀 `backend/seed/demo_universe.json`（唯一母體）|

### 🔧 其他修正

- `_select_codes()` 路徑錯誤（讀 `data/latest/latest/universe.json`）→ 每次都靜默走 fallback 的 5 檔硬編碼
- MoneyDJ BCD 是**欄位-major** 格式，舊 parser 當逐行 CSV 解析 → 只會得到 `values` 陣列
  （已用 TWSE 官方收盤價交叉驗證：2026/10/21 2330 O2425 H2435 L2400 C2420 V27,095 完全吻合）
- TDCC 趨勢在存檔**之後**才計算 → 最新快照永遠缺 `w1/w2/w3`
- MoneyDJ BCD 端點已改為要求 SSO 登入（實測等 150 秒仍 302 → `/sso/signin`）
- 設定解析統一：環境變數優先、其次 `backend/.env`
  （舊版 `RL_JITTER` / `PIPELINE_LIMIT` 只讀 `os.environ`，`.env` 裡的值被靜默忽略）
- `run_pyramid_async` 誤用 `mops_available()`（複製貼上錯誤）

### ➕ 新增

- `backend/seed/demo_universe.json` — 43 檔示範個股的唯一母體
- `backend/tests/test_config_resolution.py`（18）、`test_mops.py`（14）、
  `test_merge_layer.py`（13）、`test_wantgoo.py`（13）
- 測試總數 28 → **83**（11 個測試檔）
- MoneyDJ 週 K 線來源（純 HTTP，取代 Playwright）
- 集保公開精簡歷史 `data/latest/tdcc_history_public.json`（讓 CI 也能累積多週趨勢）

### ⚠️ 已知限制（誠實揭露）

- 玩股網的個股 JSON API 目前對未登入訪客回 400（連站方自己的頁面請求也一樣）
- MoneyDJ 週 K 線需要先 `python -m backend.scripts.auth_setup --site pyramid` 登入
- FinMind 匿名存取已被站方封鎖，需 `FINMIND_TOKEN`
- 因此 **F2 / F3 / F8 / F9 / F10 尚不能在 strict 模式全數計算**，
  前端會顯示「◐ 部分真實」橫幅，並把沒有真實因子的個股排除於排名之外

### 📊 實測結果

public pipeline：TWSE 1088 檔、TPEx 892 檔、MOPS 20/20 檔（近 12 月質設異動 19 筆）、
集保 4088 檔 → 合併層：43 檔全數有真實價格與真實集保分級、20 檔有真實董監資料

### ✅ 最終驗證

| 項目 | 結果 |
|---|---|
| 單元測試 | 11 個測試檔、83 項全部通過 |
| `CI` workflow | 🟢 綠燈（45 秒）|
| `Scrape & Update Public Data` workflow | 🟢 綠燈（16m38s，實際推上 `data/latest/meta.json`）|
| `pages-build-deployment` | 🟢 綠燈 |
| 線上網站實機驗證 | 43 檔 / 5 檔硬性過濾；banner 顯示 `TWSE ✓ 1088 · TPEx ✓ 892 · MOPS ✓ · 集保 ✓ 4088`、資料品質橫幅 `◐ 部分真實：1/38 檔有真實因子，其餘 37 檔未進入排名` |

> 實機驗證過程中 CI 連續兩次失敗，都是 CI 自己抓出來的問題
> （驗證了已移出版控的 `prices.json`、單元測試沒裝 `beautifulsoup4`、
> 測試檔名寫死而漏掉 4 個新測試）—— 這正是 BUG-07「驗證從來沒擋下過東西」
> 想解決的問題。

---

## [v0.2.0] — 2026-09-22 — Real Data Pipeline

### Added
- **Complete 7-source backend pipeline** with anti-detection for restricted sites
  - `twse.py` — TWSE OpenAPI (1082 stocks, 135 indices)
  - `tpex.py` — TPEx (OTC) OpenAPI (891 stocks, Big5 handling)
  - `finmind.py` — FinMind REST API (optional token, graceful skip)
  - `mops.py` — 公開資訊觀測站 (2024 endpoint migrated, graceful skip)
  - `tdcc.py` — 集保中心 via Playwright
  - `pyramid.py` — 神秘金字塔 via Playwright + session cookie persistence
  - `goodinfo.py` — Goodinfo via Playwright + optional residential proxy
  - `us_markets.py` — Stub for US/global (Finnhub/Alpha Vantage/FRED)
- **`BrowserSession` class** in `base.py` with stealth, fingerprint rotation
- **`CredentialManager`** for `.env` (with summary() for meta.json)
- **`SessionStore`** for persistent Playwright storage_state
- **`auth_setup.py`** CLI for first-time Playwright login
- **`windows_task.ps1`** for Windows Task Scheduler registration
- **`rotate_snapshots.py`** for 90-day snapshot archival
- **`normalize.py`** for cross-source field unification
- **`Dockerfile` + `docker-compose.yml`** for Synology NAS deployment
- **28 unit tests** across 3 test files (rate_limiter, normalize, integration, rotate_snapshots)
- **`data/latest/`** serves real TWSE + TPEx prices; 7-source status shown in meta banner

### Fixed
- Snapshot directory paths: was `data/latest/<date>/`, now correctly `data/<date>/`
- `data.js` no longer needs hardcoded `STOCK_UNIVERSE`; async loader fetches from server
- `meta.json` (was `_meta.json`) — GitHub Pages doesn't serve `_`-prefixed files
- Missing industry mappings: `3711` (SEMI/日月光), `2912` (FOOD/統一超)

### Changed
- Frontend `app.js` `showMetaBanner` now displays all 7 source statuses
- `data.js` removed hardcoded 43-stock `STOCK_UNIVERSE`; uses async loader
- `pipeline.py` unified orchestrator with graceful skip per source
- All `save_latest()` functions take `data_dir` (not `out_dir`); pipeline passes `out_dir.parent`

## [v0.1.0] — 2026-09-20 — Initial Demo

### Added
- Static frontend with 4 HTML pages (index, factors, scoring, backtest)
- Hardcoded 43 demo stocks with illustrative chip data
- 9-factor scoring engine (`computeScores`)
- 6 hard filter conditions
- Visualizations via Chart.js (industry chart, score distribution, factor weights)
- GitHub Pages deployment with `quant_platform/` research framework
- LICENSE (MIT), CI workflow, Issue templates

### Notes
- This initial version was a presentation/demo only, not connected to real data.

---

## Future Work (per approved plan)

### P2 — Full chip data via Playwright sources
- Requires user to run `python -m backend.scripts.auth_setup --site pyramid|goodinfo|tdcc`
- HTML parsers in `parse_*_html()` functions currently raise `NotImplementedError`
- Once user provides real sessions, tune selectors against actual HTML

### P3 — Walk-forward backtest validation
- IC analysis, PSR/DSR/CSCV-PBO
- Compute scores with fixed input as regression test
- See `quant_platform/` directory (from earlier reference document)

### P4 — US/Global markets
- Implement `us_markets.py` (currently stub)
- Hook into WACC calculation with FRED 10-year Treasury yield
- SEC EDGAR filings retrieval

### Infrastructure
- Switch to Private repo (user's choice; requires GitHub Pro for Pages)
- Production deploy to Synology NAS via Docker Compose
- Add Slack/Telegram alert when scraper source disabled
