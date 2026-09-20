# Backend — 籌碼共振選股系統爬蟲管線

> ⚠️ **重要**：本目錄包含真實從台灣公開財經網站抓取資料的爬蟲。
> 每個資料源都有**嚴格的節流與退避設定**，目的是保護來源站點的可用性並避免 IP 被封鎖。
> **禁止**提高抓取頻率、**禁止**繞過驗證碼或反爬蟲機制、**禁止**對單一來源同時發出多個並行請求。

## 結構

```
backend/
├── requirements.txt
├── README.md                      ← 本檔
├── scrapers/
│   ├── base.py                    ← 共用基礎（RateLimiter / RetryPolicy / SourceHealth）
│   ├── twse.py                    ← 證交所 OpenAPI
│   ├── finmind.py                 ← FinMind REST 客戶端
│   ├── mops.py                    ← 公開資訊觀測站（董監 / 財報）
├── schema.py                      ← pydantic 模型（驗證 raw JSON 結構）
├── normalize.py                   ← 把不同源的欄位對齊成 STOCK_UNIVERSE 結構
├── pipeline.py                    ← 主流程 orchestrator
├── scripts/
│   └── run_local.py               ← 本地手動跑（測試用）
└── tests/
    └── test_rate_limiter.py       ← 節流閥單元測試
```

## 節流預設（最低間隔 / 單日上限）

| 來源 | 最低間隔 | 單日上限 | 失敗退避 |
|---|---|---|---|
| TWSE OpenAPI | 3 秒 | 500 次 | 60s / 300s |
| FinMind | 5 秒 | 200 次 | 60s / 180s |
| MOPS | 8 秒 | 100 次 | 90s / 300s |

## 本地執行

```bash
# 一次性建立環境（用 uv 比較快，沒有 uv 用 pip 也可以）
cd backend
python -m venv .venv
.venv\Scripts\activate           # Windows
pip install -r requirements.txt

# 只跑 TWSE 來源（~30 分鐘跑完 1700 檔）
python -m scripts.run_local --source twse

# 跑全部來源（~70 分鐘）
python -m scripts.run_local --source all

# 跑單一股票 debug
python -m scripts.run_local --source twse --code 2330
```

## 設計原則

1. **單來源單執行緒**：每個 scraper 模組內部用 `RateLimiter` 序列化請求，絕不對同一站點發出並行請求。
2. **跨來源可並行**：不同站點之間可用 `asyncio.gather` 並行（不會被單一站點偵測）。
3. **失敗可恢復**：每個來源失敗時只停止該來源，不影響其他來源；CI 結束時寫入 `_meta.json.disabled_sources` 陣列。
4. **資料不可變**：成功抓取的快照寫入 `data/YYYY-MM-DD/`，永不覆寫；`data/latest/` 是軟連結或單一檔指向最新日期。
5. **驗證嚴格**：pydantic 驗證失敗時**拒絕寫入**，保留舊資料；前端永遠不會看到壞資料。

## 授權狀態

| 資料源 | 授權 | 備註 |
|---|---|---|
| TWSE OpenAPI | 公開 | 免費、無需 API key |
| FinMind | 公開 | 免費方案有每小時 request 上限 |
| MOPS | 公開 | 公開資訊觀測站，HTML 解析，溫和節流即可 |
| 集保中心 | 公開（需登入） | P2 階段加入，需要 session cookie |
| Goodinfo | 需付費 | P4 階段，使用者提供授權後才啟用 |
| 神秘金字塔 | 需付費 | P4 階段 |