<!-- 這份表格由 `python -m backend.scripts.check_sources` 產生，勿手動編輯 -->

| 來源 | 分類 | 端點 | 狀態 | HTTP | 筆數 | 延遲 | 備註 |
|---|---|---|---|---|---:|---:|---|
| `twse_stock_day_all` | public | `https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL` | ok | 200 | 1383 | 296 ms |  |
| `twse_mi_index` | public | `https://openapi.twse.com.tw/v1/exchangeReport/MI_INDEX` | ok | 200 | 267 | 46 ms |  |
| `twse_margin` | public | `https://openapi.twse.com.tw/v1/exchangeReport/MI_MARGN` | ok | 200 | 1302 | 65 ms |  |
| `twse_valuation` | public | `https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_d` | ok | 200 | 1084 | 49 ms |  |
| `twse_company_basic` | public | `https://openapi.twse.com.tw/v1/opendata/t187ap03_L` | ok | 200 | 1097 | 62 ms |  |
| `twse_stock_day` | public | `https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?date=2026093001&stockNo=2330&response=json` | ok | 200 | 15 | 122 ms |  |
| `twse_fund_t86` | public | `https://www.twse.com.tw/rwd/zh/fund/T86?date=20261022&response=json` | ok | 200 | 7 | 1643 ms |  |
| `tpex_daily_close` | public | `https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes` | ok | 200 | 13032 | 576 ms |  |
| `tdcc_chip_grades` | public | `https://opendata.tdcc.com.tw/getOD.ashx?id=1-5&type=csv` | ok | 200 | 69700 | 569 ms |  |
| `tdcc_holder_index` | public | `https://opendata.tdcc.com.tw/getOD.ashx?id=6-1&type=csv` | ok | 200 | 19998 | 216 ms |  |
| `yahoo_chart` | public | `https://query1.finance.yahoo.com/v8/finance/chart/2330.TW?range=2y&interval=1d` | ok | 200 | 487 | 180 ms |  |
| `mops_director` | public | `https://mopsov.twse.com.tw/mops/web/ajax_stapap1` | ok | 200 | 63 | 4697 ms |  |
| `wantgoo_price` | private | `https://www.wantgoo.com/investrue/2330/historical-daily-candlesticks?before=1792771200000&top=490` | ok | 200 | 490 | 280 ms | 本機可用；GitHub Actions datacenter IP 回 403 |
| `wantgoo_all_quote` | private | `https://www.wantgoo.com/investrue/all-quote-info` | ok | 200 | 6044 | 104 ms | 本機可用；datacenter IP 回 403 |
| `moneydj_chip` | private | `https://www.moneydj.com/z/zc/zcj/2330.djhtm` | blocked | 200 | 0 | 92 ms | 籌碼頁需會員（實測 2330 可、其餘 SSO）；登入頁（需會員／session） |
| `goodinfo_chip` | private | `https://goodinfo.tw/tw/StockChipDetail.asp?STOCK_ID=2330` | blocked | 403 | 0 | 135 ms | 需登入 session |
| `finmind_api` | private | `https://api.finmindtrade.com/api/v4/data` | error | 422 | 1 | 246 ms | 付費牆（免費層不提供該資料集）；HTTP 422 |

產生時間：2026-10-25T01:49:56+08:00　（14/17 正常、2 被擋、0 空資料、1 錯誤）
