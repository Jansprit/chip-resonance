"""
test_check_sources.py — 資料來源健康度檢查（check_sources.py）的行為測試

對應修復計畫 P2.2：
    「產出 source_health.json；矩陣文件涵蓋 8 源」

**為什麼需要這支工具？**
本專案最貴的成本不是程式碼，是「以為某個來源還能用」。
v0.3.x 裡 MoneyDJ 被當成免費來源、FinMind 被當成免費 API、
集保 6-1 被當成股東人數 —— 每一個都是「看起來能用，實際上不能」，
而且都是寫完程式才發現。

把「來源還能不能用」變成**可程式化檢查 + 可版本控制的報告**，
才能讓下一個人（或半年後的我）不必重走一遍。

設計原則：
- 檢查必須**誠實**：403 要標成 blocked（不是 ok），空資料要標成 empty。
- 檢查必須**不炸**：任何網路錯誤都要被捕捉成結果，不可讓流程中斷。
- 檢查必須**可離線測試**：注入 fetcher，不在測試裡打真實網路。
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.scripts import check_sources as cs


# ============ 輔助 ============

def _fake_fetcher(status: int = 200, body: str = "[]"):
    def _f(probe, timeout):
        return status, body
    return _f


def _raising_fetcher(probe, timeout):
    raise OSError("network unreachable")


# ============ 來源清單 ============

def test_registry_covers_core_sources():
    """矩陣必須涵蓋 8 個核心來源（不能只測自己寫的那幾個）。"""
    names = {p.name for p in cs.SOURCE_REGISTRY}
    required = {
        "twse_stock_day_all",
        "twse_margin",
        "twse_valuation",
        "twse_company_basic",
        "tpex_daily_close",
        "tdcc_chip_grades",
        "yahoo_chart",
        "mops_director",
    }
    missing = required - names
    assert not missing, f"來源矩陣缺少：{sorted(missing)}"


def test_registry_entries_are_wellformed():
    """每一筆都要有名字、分類、端點、說明 —— 否則矩陣文件無法自動產生。"""
    seen = set()
    for p in cs.SOURCE_REGISTRY:
        assert p.name and p.name not in seen, f"來源名稱重複或空白：{p.name}"
        seen.add(p.name)
        assert p.category in ("public", "private"), f"{p.name} 分類非法：{p.category}"
        assert p.method in ("GET", "POST"), f"{p.name} method 非法：{p.method}"
        assert p.url.startswith("http"), f"{p.name} url 非法：{p.url}"
        assert p.description, f"{p.name} 缺少說明"


def test_registry_marks_known_local_only_sources_private():
    """實測會 403 / 需登入的來源必須標成 private（不可放進 CI 集合）。"""
    private = {p.name for p in cs.SOURCE_REGISTRY if p.category == "private"}
    for name in ("wantgoo_price", "moneydj_chip", "goodinfo_chip"):
        assert name in private, f"{name} 應為 private（實測不可用於 CI）"


def test_registry_public_sources_are_all_government_or_free():
    """public 集合不得包含已知需登入 / 付費的來源。"""
    for p in cs.SOURCE_REGISTRY:
        if p.category != "public":
            continue
        low = (p.url + p.description).lower()
        assert "login" not in low
        assert "api.finmindtrade" not in low, f"{p.name} 不該是 public"


# ============ 探測行為 ============

def test_probe_source_ok():
    probe = cs.SourceProbe(
        name="demo", category="public", method="GET",
        url="https://example.com/api", description="測試",
    )
    result = cs.probe_source(probe, fetcher=_fake_fetcher(200, '[{"a":1},{"a":2}]'))
    assert result["status"] == "ok"
    assert result["http_status"] == 200
    assert result["records"] == 2
    assert result["error"] is None


def test_probe_source_blocked_on_403():
    """403 = 被擋（IP 封鎖 / 需要登入），絕對不能標成 ok。"""
    probe = cs.SourceProbe(
        name="demo", category="private", method="GET",
        url="https://example.com/api", description="測試",
    )
    result = cs.probe_source(probe, fetcher=_fake_fetcher(403, "Forbidden"))
    assert result["status"] == "blocked"
    assert result["http_status"] == 403


def test_probe_source_blocked_on_429():
    probe = cs.SourceProbe(
        name="demo", category="public", method="GET",
        url="https://example.com/api", description="測試",
    )
    result = cs.probe_source(probe, fetcher=_fake_fetcher(429, "Too Many Requests"))
    assert result["status"] == "blocked"


def test_probe_source_error_on_exception():
    """網路錯誤要被捕捉成結果，不可讓整個檢查流程中斷。"""
    probe = cs.SourceProbe(
        name="demo", category="public", method="GET",
        url="https://example.com/api", description="測試",
    )
    result = cs.probe_source(probe, fetcher=_raising_fetcher)
    assert result["status"] == "error"
    assert "network unreachable" in (result["error"] or "")
    assert result["http_status"] is None


def test_probe_source_empty_when_no_records():
    """200 但沒有資料 → empty（不是 ok）。"""
    probe = cs.SourceProbe(
        name="demo", category="public", method="GET",
        url="https://example.com/api", description="測試",
    )
    result = cs.probe_source(probe, fetcher=_fake_fetcher(200, "[]"))
    assert result["status"] == "empty"
    assert result["records"] == 0


def test_probe_source_handles_non_json_body():
    """CSV / HTML 回應也要能算筆數，不可直接爆掉。"""
    probe = cs.SourceProbe(
        name="demo", category="public", method="GET",
        url="https://example.com/api", description="測試",
    )
    body = "a,b,c\n1,2,3\n4,5,6\n"
    result = cs.probe_source(probe, fetcher=_fake_fetcher(200, body))
    assert result["status"] == "ok"
    assert result["records"] == 2      # 兩筆資料列（不含表頭）


def test_probe_source_blocked_when_login_markers_present():
    """需要登入的頁面回 200 也不代表可用 —— 看到登入頁必須標成 blocked。"""
    probe = cs.SourceProbe(
        name="demo", category="private", method="GET",
        url="https://example.com/member", description="測試",
        block_markers=("Sign in Page",),
    )
    html = "<html><head><title>Sign in Page - SSO</title></head><body>登入</body></html>"
    result = cs.probe_source(probe, fetcher=_fake_fetcher(200, html))
    assert result["status"] == "blocked"


def test_probe_source_not_blocked_without_markers():
    """沒有登入標記的正常頁面不可被誤判為 blocked。"""
    probe = cs.SourceProbe(
        name="demo", category="public", method="GET",
        url="https://example.com/ok", description="測試",
        block_markers=("Sign in Page",),
    )
    result = cs.probe_source(probe, fetcher=_fake_fetcher(200, '[{"a":1}]'))
    assert result["status"] == "ok"


def test_registry_moneydj_uses_correct_chip_url():
    """
    玩股網/MoneyDJ 的籌碼頁路徑是 /z/zc/{頁}/{code}.djhtm。

    舊版的 /z/zcj/{code}.djhtm 會 302 到 /404.htm，
    看起來像「回 200 但沒資料」，實際上是路徑錯了。
    """
    probe = next(p for p in cs.SOURCE_REGISTRY if p.name == "moneydj_chip")
    assert "/z/zc/" in probe.url, f"MoneyDJ 籌碼頁路徑錯誤：{probe.url}"
    assert probe.block_markers, "需登入的來源必須標記 block_markers"


def test_registry_login_required_sources_declare_markers():
    """private 集合中需登入的來源都必須宣告 block_markers。"""
    for p in cs.SOURCE_REGISTRY:
        if p.name in ("moneydj_chip", "goodinfo_chip"):
            assert p.block_markers, f"{p.name} 應宣告 block_markers"

    probe = cs.SourceProbe(
        name="demo", category="public", method="GET",
        url="https://example.com/api", description="測試",
    )
    result = cs.probe_source(probe, fetcher=_fake_fetcher())
    assert result["latency_ms"] >= 0


def test_probe_source_measures_latency():
    probe = cs.SourceProbe(
        name="demo", category="public", method="GET",
        url="https://example.com/api", description="測試",
    )
    result = cs.probe_source(probe, fetcher=_fake_fetcher())
    assert result["latency_ms"] >= 0


def test_probe_source_records_checked_at():
    probe = cs.SourceProbe(
        name="demo", category="public", method="GET",
        url="https://example.com/api", description="測試",
    )
    result = cs.probe_source(probe, fetcher=_fake_fetcher())
    assert result["checked_at"]
    assert len(result["checked_at"]) >= 10


# ============ 筆數計算（各來源結構不同，不可只算 JSON 陣列長度）============

def test_count_records_counts_yahoo_bars():
    """Yahoo 的資料在 chart.result[0].timestamp 陣列裡，不是頂層陣列。"""
    body = json.dumps({
        "chart": {"result": [{
            "timestamp": [1, 2, 3, 4, 5],
            "indicators": {"quote": [{"close": [1, 2, 3, 4, 5]}]},
        }], "error": None},
    })
    assert cs._count_records(body) == 5


def test_count_records_counts_twse_rwd_tables():
    """TWSE RWD 另一種外框：tables 內含資料列陣列。"""
    body = json.dumps({
        "tables": [[["2330", "台積電", "1000"], ["2454", "聯發科", "900"]]],
    })
    assert cs._count_records(body) == 2


def test_count_records_prefers_twse_rwd_total_field():
    """
    TWSE RWD 的 `total` 是最權威的筆數（= 資料列數）。

    實測回應形如：
        {"stat":"OK","fields":[...],"data":[[...],[...]],"total":2}
    只看 data 的長度會在欄位陣列時算錯。
    """
    body = json.dumps({
        "stat": "OK",
        "fields": ["證券代號", "名稱", "外陸及外資買入"],
        "data": [["2330", "台積電"], ["2454", "聯發科"], ["2317", "鴻海"]],
        "total": 3,
    })
    assert cs._count_records(body) == 3


def test_count_records_counts_twse_openapi_list():
    body = json.dumps([{"Code": "2330"}, {"Code": "2454"}, {"Code": "2317"}])
    assert cs._count_records(body) == 3


def test_count_records_counts_html_table_rows():
    """MOPS 回的是 HTML 表格，不是 JSON。"""
    html = """
    <table><tr><th>持股分公司</th><th>姓名</th></tr>
    <tr><td>台灣集中保管</td><td>張三</td></tr>
    <tr><td>台灣集中保管</td><td>李四</td></tr></table>
    """
    assert cs._count_records(html) == 2


def test_count_records_returns_zero_for_unparseable():
    assert cs._count_records("") == 0
    assert cs._count_records("   ") == 0
    assert cs._count_records("<html><body>no table</body></html>") == 0


def test_probe_source_uses_fallback_url_when_first_has_no_data():
    """
    需要日期參數的端點（例如 TWSE T86）在無交易日的回「沒有符合條件的資料」，
    檢查工具必須能往回試其他日期，否則會把「那天沒交易」誤判成「來源壞了」。
    """
    probe = cs.SourceProbe(
        name="demo", category="public", method="GET",
        url="https://example.com/day1",
        description="測試",
        fallback_urls=("https://example.com/day2",),
    )

    def _f(p, timeout):
        if p.url.endswith("day1"):
            return 200, json.dumps({"stat": "沒有符合條件的資料", "total": 0})
        return 200, json.dumps([{"a": 1}, {"a": 2}])

    result = cs.probe_source(probe, fetcher=_f)
    assert result["status"] == "ok"
    assert result["records"] == 2
    assert result["url"] == "https://example.com/day2"


def test_probe_source_reports_error_from_first_url_even_if_fallback_also_fails():
    """所有候選網址都失敗 → 保留第一筆的錯誤訊息，不可變成「空資料」。"""
    probe = cs.SourceProbe(
        name="demo", category="public", method="GET",
        url="https://example.com/day1",
        description="測試",
        fallback_urls=("https://example.com/day2",),
    )
    result = cs.probe_source(probe, fetcher=_raising_fetcher)
    assert result["status"] == "error"
    assert "network unreachable" in (result["error"] or "")


# ============ 彙總 ============

def test_check_all_aggregates_results():
    fetcher = lambda probe, timeout: (200, "[{}]")   # noqa: E731
    report = cs.check_all(fetcher=fetcher)
    assert report["total"] == len(cs.SOURCE_REGISTRY)
    assert report["ok"] == len(cs.SOURCE_REGISTRY)
    assert report["blocked"] == 0
    assert "sources" in report
    assert len(report["sources"]) == len(cs.SOURCE_REGISTRY)


def test_check_all_survives_all_failures():
    """全部來源都掛掉時，檢查本身仍要產出完整報告。"""
    report = cs.check_all(fetcher=_raising_fetcher)
    assert report["total"] == len(cs.SOURCE_REGISTRY)
    assert report["error"] == len(cs.SOURCE_REGISTRY)
    assert report["ok"] == 0


def test_check_all_can_filter_to_public_only():
    report = cs.check_all(fetcher=_fake_fetcher(), categories=("public",))
    assert report["total"] == len(
        [p for p in cs.SOURCE_REGISTRY if p.category == "public"]
    )
    for s in report["sources"]:
        assert s["category"] == "public"


def test_check_all_writes_valid_json():
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "source_health.json"
        cs.check_all(fetcher=_fake_fetcher(), output=out)
        payload = json.loads(out.read_text(encoding="utf-8"))
        assert payload["total"] == len(cs.SOURCE_REGISTRY)
        assert isinstance(payload["sources"], list)
        assert payload["sources"][0]["name"]


def test_check_all_source_entries_have_required_fields():
    report = cs.check_all(fetcher=_fake_fetcher())
    for s in report["sources"]:
        for key in ("name", "category", "url", "status", "http_status",
                    "records", "latency_ms", "error", "checked_at"):
            assert key in s, f"{s.get('name')} 缺少 {key}"


def test_check_all_summary_has_degraded_flag():
    """public 來源全掛 → degraded=True（CI 可據此告警）。"""
    report = cs.check_all(fetcher=_raising_fetcher, categories=("public",))
    assert report["degraded"] is True
    report2 = cs.check_all(fetcher=_fake_fetcher(200, '[{"a":1}]'), categories=("public",))
    assert report2["degraded"] is False


def test_check_all_empty_public_source_counts_as_degraded():
    """public 來源回 200 但沒資料 → 也是降級（空資料等於拿不到東西）。"""
    report = cs.check_all(fetcher=_fake_fetcher(200, "[]"), categories=("public",))
    assert report["empty"] == report["public_total"]
    assert report["degraded"] is True

if __name__ == "__main__":
    # 自動發現所有 test_ 函式 —— 新增測試不可能再被靜默遺漏。
    # 見 backend/tests/_runner.py 的說明。
    import sys as _sys
    from pathlib import Path as _Path

    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
    from backend.tests._runner import run_tests

    run_tests(globals(), "check_sources")
