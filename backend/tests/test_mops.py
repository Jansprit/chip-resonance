"""
test_mops.py — Tests for the MOPS (公開資訊觀測站) scraper

對應 docs/2026-10-21-專案體檢報告.md BUG-02

BUG-02 根因：端點寫成 mops.twse.com.tw/mops/web/t146sb05，
該網址 302 → /mops/error/404，只會回 65 bytes 的錯誤頁。
正確的是 mopsov.twse.com.tw/mops/web/ajax_stapap1（純 HTTP，不需要 cookie）。

驗證：
- 端點常數不會退回到壞掉的 host / 舊頁面
- 民國年換算正確（2026 → 115）
- 月份平移跨年正確
- 董監事持股 HTML 解析（持股、設質股數、設質比例、資料年月）
- 「查無資料」空頁要能被辨識，不會被當成 0 持股
- 兩個月份合併 → 近 3 月持股變化率
- 質設異動明細解析

執行：python backend/tests/test_mops.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.scrapers import mops


# ============ 測試用 HTML fixture ============

DIRECTOR_HTML = """
<html><body>
<div id="div01">
<table class='noBorder'><tr><td class='reportCont'>資料年月:11509</td></tr></table>
<table class='hasBorder'>
<tr class='tblHead'>
<td valign=top nowrap rowspan=2>職稱</td>
<td valign=top nowrap rowspan=2>姓名</td>
<td valign=top nowrap rowspan=2>選任時持股</td>
<td valign=top nowrap rowspan=2>目前持股</td>
<td valign=top nowrap rowspan=2>設質股數</td>
<td valign=top nowrap rowspan=2>設質股數佔持股比例</td>
</tr>
<TR class='odd'><TD>董事長本人</TD><TD>魏哲家</TD><TD>      6,392,834</TD><TD>      7,656,724</TD><TD>      1,600,000</TD><TD>20.89%</TD></TR>
<TR class='even'><TD>董事本人</TD><TD>行政院國家發展基金管理會</TD><TD>  1,653,709,980</TD><TD>  1,653,709,980</TD><TD>              0</TD><TD>0.00%</TD></TR>
</table>
</div>
</body></html>
"""

PLEDGE_HTML = """
<html><body>
<div id="div01">
<center><h3>資料期間為 114/01/01 至 115/10/22</h3></center>
<table class='hasBorder' cellpadding='3' cellspacing='0'>
<tr class='tblHead'>
<th>公司代號</th><th>公司名稱</th>
<th>設質人身份別</th><th>設質人姓名</th><th>質設異動發生日期</th>
<th>設質股數</th><th>解質股數</th><th>累積質設股數</th>
<th>質權人姓名</th><th>備註</th><th>申報日期</th>
</tr>
<tr class='odd'><td align='center'>2330</td><td align='left'>台積電</td><td align='left'>H00250<br>副總經理本人</td><td align='left'>方淑華</td><td align='cente'>114/04/08</td><td style='text-align:right !important;'>             50,000</td><td style='text-align:right !important;'>                  0</td><td style='text-align:right !important;'>            100,000</td><td align='left'>元大證券</td><td align='left'>&nbsp;</td><td align='left'>114/04/09</td></tr>
</table>
</div>
</body></html>
"""

NO_DATA_HTML = """
<html><body><div id="div01">
<center><h3>公開資訊觀測站 資料庫中查無資料 !</h3></center>
</div></body></html>
"""


# ============ 端點回歸防護 ============

def test_endpoint_host_is_mopsov():
    """BUG-02：mops.twse.com.tw 會 302 → /mops/error/404（65 bytes 錯誤頁）。"""
    assert "mopsov.twse.com.tw" in mops.MOPS_BASE
    assert "mops.twse.com.tw" not in mops.MOPS_BASE.replace("mopsov.twse.com.tw", "")
    assert mops.MOPS_AJAX_DIRECTOR.endswith("/mops/web/ajax_stapap1")
    assert mops.MOPS_AJAX_PLEDGE_EVENT.endswith("/mops/web/ajax_STAMAK03_1")


def test_legacy_404_page_not_used():
    """舊的 t146sb05 / t05bd09 不能再被當作查詢端點。"""
    for legacy in ("t146sb05", "t05bd09"):
        assert legacy not in mops.MOPS_AJAX_DIRECTOR
        assert legacy not in mops.MOPS_AJAX_PLEDGE_EVENT


def test_is_available_true():
    """MOPS 免登入、純 HTTP 可用，不應被 skip。"""
    assert mops.is_available() is True


# ============ 民國換算 ============

def test_to_roc():
    assert mops.to_roc(2026, 10) == (115, "10")
    assert mops.to_roc(2025, 1) == (114, "01")
    assert mops.to_roc(2026, 12) == (115, "12")


def test_roc_period_to_ym():
    assert mops.roc_period_to_ym("11509") == (2026, 9)
    assert mops.roc_period_to_ym("11401") == (2025, 1)


def test_shift_month_crosses_year():
    assert mops.shift_month(2026, 10, -3) == (2026, 7)
    assert mops.shift_month(2026, 1, -3) == (2025, 10)
    assert mops.shift_month(2025, 12, -3) == (2025, 9)
    assert mops.shift_month(2026, 10, 3) == (2027, 1)


# ============ 董監事持股解析 ============

def test_parse_director_holding():
    r = mops.parse_director_holding_html(DIRECTOR_HTML, "2330")
    assert r["code"] == "2330"
    assert r["period"] == "11509"
    assert r["no_data"] is False
    assert r["rows"] == 2
    assert r["holding_total"] == 7_656_724 + 1_653_709_980
    assert r["pledged_total"] == 1_600_000
    # 設質比例
    expected = 1_600_000 / (7_656_724 + 1_653_709_980) * 100
    assert abs(r["pledge_pct"] - expected) < 1e-3


def test_parse_director_detects_no_data():
    """MOPS 對沒有資料的月份回「查無資料」，必須辨識出來而不是當成 0 持股。"""
    r = mops.parse_director_holding_html(NO_DATA_HTML, "2330")
    assert r["no_data"] is True
    assert r["rows"] == 0
    assert r["pledge_pct"] is None


def test_combine_director_periods():
    cur = mops.parse_director_holding_html(DIRECTOR_HTML, "2330")
    past = {
        "code": "2330", "period": "11506", "no_data": False, "rows": 2,
        "holding_total": cur["holding_total"] * 1.10,
        "pledged_total": cur["pledged_total"],
        "pledge_pct": cur["pledge_pct"],
    }
    merged = mops.combine_director_periods(cur, past)
    # 變化率以「3 個月前」為分母：(now - then) / then
    # now = cur, then = cur * 1.10 → (cur - 1.1cur) / (1.1cur) = -9.0909%
    expected = (cur["holding_total"] - past["holding_total"]) / past["holding_total"] * 100
    assert abs(merged["director_holding_change_3m"] - expected) < 1e-3
    assert abs(merged["director_holding_change_3m"] - (-9.0909)) < 0.01
    assert merged["pledge_pct"] == cur["pledge_pct"]


def test_combine_director_periods_without_past():
    """沒有 3 個月前的資料時，變化率必須是 None（不可計算 → 因子 unavailable）。"""
    cur = mops.parse_director_holding_html(DIRECTOR_HTML, "2330")
    merged = mops.combine_director_periods(cur, None)
    assert merged["director_holding_change_3m"] is None


# ============ 質設異動解析 ============

def test_parse_pledge_html():
    r = mops.parse_pledge_html(PLEDGE_HTML, "2330")
    assert r["code"] == "2330"
    assert r["events"] == 1
    assert r["pledged_total"] == 50_000
    assert r["released_total"] == 0
    assert r["cumulative_max"] == 100_000
    assert r["no_data"] is False


def test_parse_pledge_detects_no_data():
    r = mops.parse_pledge_html(NO_DATA_HTML, "2330")
    assert r["events"] == 0
    assert r["no_data"] is True


# ============ 數字解析 ============

def test_to_float_handles_formatting():
    assert mops._to_float("      6,392,834") == 6392834.0
    assert mops._to_float("20.89%") == 20.89
    assert mops._to_float("--") is None
    assert mops._to_float("") is None
    assert mops._to_float(None) is None

if __name__ == "__main__":
    # 自動發現所有 test_ 函式 —— 新增測試不可能再被靜默遺漏。
    # 見 backend/tests/_runner.py 的說明。
    import sys as _sys
    from pathlib import Path as _Path

    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
    from backend.tests._runner import run_tests

    run_tests(globals(), "mops")
