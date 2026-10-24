# tools/source-probes — 資料來源實測探測腳本

這裡的腳本**不是 pipeline 的一部分**,而是「用手實測某個資料源到底能不能用」的工具。
它們的存在是為了對應 [專案開發歷程分析.MD](../專案開發歷程分析.MD) 的核心結論:

> 專案在 34 天裡繞了三圈,根因是我從「一次 HTTP 回應」推論來源可達性,
> 卻沒有留下**可重現的存取證據**。

## 使用方式

```powershell
# 端點總覽（Yahoo / TWSE / TPEx / FinMind）
python tools/source-probes/probe_overview.py

# TWSE RWD 端點逐一試（融資券 / 三大法人 / 月線 / 當沖）
python tools/source-probes/probe_twse_tpex.py

# 集保 dataset id 清單 + 證交所當沖端點
python tools/source-probes/probe_tdcc_margin.py

# 市場當沖統計 / TPEx API / 集保 6-1 股東人數欄位
python tools/source-probes/probe_daytrade_holders.py

# MoneyDJ 籌碼頁（zcj/zck/zcn/zcw）純 HTTP 抓表格
python tools/source-probes/probe_moneydj_pages.py

# MoneyDJ 籌碼頁表格解析（去 script 汙染、完整欄位）
python tools/source-probes/parse_moneydj_chip.py

# 真實瀏覽器（滑鼠 / 滾輪 / 點擊）驗證 MoneyDJ 與玩股網
python tools/source-probes/probe_browser_sources.py
python tools/source-probes/probe_moneydj_browser.py
```

## 使用原則

1. **先跑探測,再寫 pipeline**。不要先寫 `raise NotImplementedError` 再說「之後再試」。
2. **每個來源至少兩種存取方式**:純 HTTP + 真實瀏覽器。兩者結果不同時,
   通常就是「IP 層級封鎖」或「需簽章」的線索。
3. **判定失敗要附證據**:端點、參數、HTTP 狀態、回應片段。
   「被封鎖」不是結論,「403 + datacenter IP 回應 + 同站台 404 端點比對」才是。
4. **結果要回寫到** `docs/資料來源可達性矩陣.md`(P2.1 產出)。

## 已知的實測結論(2026-10-24)

| 結論 | 證據 |
|---|---|
| MoneyDJ 籌碼頁需會員資格 | 2330 → 200 完整表格;2454 / 5880 → SSO。**真實瀏覽器結果相同** |
| MoneyDJ 免登入額度約 1 檔/日 | BCD 第 1 檔成功、2~6 檔全 SSO;全新 session + 間隔 0/20/45/90 秒皆失敗 |
| 玩股網價格歷史本機可用、CI 不可用 | 本機 43/43 檔 200;GitHub Actions datacenter IP → 403 |
| FinMind 是付費牆不是防爬 | 完整瀏覽器指紋 + cookie 後仍 400 "Your level is free" |
| TWSE / TPEx / 集保 / MOPS 不擋 datacenter IP | 全部 200,見各探測腳本輸出 |
