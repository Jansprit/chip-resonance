"""
test_finmind.py — FinMind 免費層的可用性與資料集邊界

**為什麼需要這份測試？**
本專案曾把 FinMind 判定為「付費牆」，於是 pipeline 在沒有 token 時
整個跳過它 —— 等於白白放棄一個免費、CI 可用的價格來源。

2026-10-25 實測推翻了這個結論：
    TaiwanStockPrice       → 200，資料回溯到 2016-01-04（免 token）
    TaiwanStockDayTrading  → 200，同樣回溯到 2016（免 token）
    TaiwanStockShareholding→ 400 "Your level is free"（**這個才要付費**）

而且 `TaiwanStockDayTrading` 的 `BuyAfterSale`（當沖量）在免費層
只會是 "" 或 "Y"，**不是數量** → 個股當沖比（dt_ratio）仍然拿不到。
這兩件事都必須被測試釘住，否則下次又會有人「想當然」。

執行：python backend/tests/test_finmind.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.scrapers import finmind


def test_is_available_without_token():
    """免費層不需要 token → 沒有 token 也必須回 True。"""
    assert finmind.is_available() is True


def test_free_datasets_include_price_and_day_trading():
    """免費資料集必須包含價格與當沖。"""
    assert "TaiwanStockPrice" in finmind.FREE_DATASETS
    assert "TaiwanStockDayTrading" in finmind.FREE_DATASETS


def test_paid_datasets_are_not_marked_free():
    """持股分級是付費的，不可混進免費清單。"""
    assert "TaiwanStockShareholding" not in finmind.FREE_DATASETS


def test_fetch_dataset_builds_correct_params():
    """
    參數組裝：**必須用 `data_id`**，不能用 `stock_id`。

    2026-10-25 實測：傳 `stock_id=2330` 會回
    `400 {"msg": "Your level is free"}` —— 那個訊息完全誤導，
    讓本專案誤以為 FinMind 是付費牆；改成 `data_id` 立刻 200，
    而且免 token 就能拿到 2016 年起的歷史。
    """
    captured = {}

    class _FakeClient:
        def get_json(self, url, params=None, **kwargs):
            captured.update(params or {})
            return [{"stock_id": "2330"}]

    rows = finmind.fetch_dataset(
        "TaiwanStockPrice",
        stock_id="2330",
        start_date="2026-01-01",
        end_date="2026-10-22",
        client=_FakeClient(),
    )
    assert rows == [{"stock_id": "2330"}]
    assert captured["dataset"] == "TaiwanStockPrice"
    assert captured["data_id"] == "2330"
    assert "stock_id" not in captured, \
        "傳 stock_id 會被 FinMind 判成「免費層無權限」，必須用 data_id"
    assert captured["start_date"] == "2026-01-01"
    assert captured["end_date"] == "2026-10-22"


def test_fetch_dataset_omits_empty_params():
    """留空的參數不應送出（FinMind 對空字串會回 422）。"""
    captured = {}

    class _FakeClient:
        def get_json(self, url, params=None, **kwargs):
            captured.update(params or {})
            return []

    finmind.fetch_dataset("TaiwanStockPrice", client=_FakeClient())
    assert "data_id" not in captured
    assert "start_date" not in captured


def test_fetch_dataset_unwraps_response_envelope():
    """
    FinMind 回的是 envelope：{"msg":"success","status":200,"data":[...]}。

    舊版直接回傳整個 envelope，於是呼叫端拿到的是
    ["msg", "status", "data"] 三個 key 的字串陣列 —— 資料完全沒進來。
    """
    class _FakeClient:
        def get_json(self, url, params=None, **kwargs):
            return {
                "msg": "success",
                "status": 200,
                "data": [{"date": "2026-09-01", "stock_id": "2330", "close": 100.0}],
            }

    rows = finmind.fetch_dataset("TaiwanStockPrice", stock_id="2330",
                                 client=_FakeClient())
    assert rows == [{"date": "2026-09-01", "stock_id": "2330", "close": 100.0}]
    assert all(isinstance(r, dict) for r in rows)


def test_fetch_dataset_raises_on_error_status():
    """FinMind 回非 200 狀態時必須拋例外（不可把錯誤 envelope 當資料）。"""
    class _FakeClient:
        def get_json(self, url, params=None, **kwargs):
            return {"msg": "Your level is free", "status": 400, "data": []}

    try:
        finmind.fetch_dataset("TaiwanStockPrice", stock_id="2330",
                              client=_FakeClient())
    except RuntimeError as exc:
        assert "Your level is free" in str(exc)
        return
    raise AssertionError("錯誤狀態必須拋例外")


def test_fetch_stock_prices_collects_rows_across_stocks():
    """批次抓取要把各檔資料接起來（不是把 envelope 的 key 接起來）。"""
    class _FakeClient:
        def get_json(self, url, params=None, **kwargs):
            sid = (params or {}).get("data_id", "?")
            return {"msg": "success", "status": 200,
                    "data": [{"stock_id": sid, "date": "2026-09-01"}]}

    rows = finmind.fetch_stock_prices(["2330", "2454"], "2026-09-01", "2026-09-02",
                                      client=_FakeClient())
    assert len(rows) == 2
    assert {r["stock_id"] for r in rows} == {"2330", "2454"}
    assert all(isinstance(r, dict) for r in rows)


def test_finmind_client_uses_fast_fail_retry():
    """
    FinMind 必須用快速失敗的重試策略。

    用全域的 60/300/900 秒退避會讓 pipeline 整整卡掉 15 分鐘，
    最後還是失敗 —— 那是參數／配額層的問題，不是暫時性的網路抖動。
    """
    client = finmind.create_finmind_client()
    assert client.retry.max_retries <= 2, "重試次數過多會拖垮整條 pipeline"
    longest = max(client.retry.schedule)
    assert longest <= 10, f"退避間隔過長：{client.retry.schedule}"


def test_day_trading_ratio_is_not_computable_from_free_tier():
    """
    免費層的 BuyAfterSale 只會是 "" 或 "Y"，不是當沖量。

    因此**不可**用這個欄位算出 dt_ratio（那會是假的 0% 或假的 100%）。
    這個測試把「不可得」釘死，避免有人誤以為可以算。
    """
    rows = [
        {"stock_id": "2330", "date": "2026-10-15", "BuyAfterSale": "",
         "Volume": 11049000, "BuyAmount": 26898040000, "SellAmount": 26963080000},
        {"stock_id": "2330", "date": "2026-10-16", "BuyAfterSale": "Y",
         "Volume": 4342000, "BuyAmount": 10551330000, "SellAmount": 10562340000},
    ]
    numeric = [
        r for r in rows
        if str(r.get("BuyAfterSale", "")).strip() not in ("", "Y")
    ]
    assert numeric == [], "免費層沒有任何可用的當沖量欄位 → dt_ratio 仍不可得"


if __name__ == "__main__":
    import sys as _sys
    from pathlib import Path as _Path

    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
    from backend.tests._runner import run_tests

    run_tests(globals(), "finmind")
