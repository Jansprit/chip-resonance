"""
test_frontend_assets.py — 前端靜態資源與資料路徑的守門測試

**為什麼需要這份測試？**
2026-10-25 第一次部署後，backtest.html 的「真實回測報告」區塊顯示
「載入真實回測報告失敗：HTTP 404」—— 而檔案其實**有**部署
（`https://jansprit.github.io/chip-resonance/data/latest/backtest_report.json`
回 200）。

真因是 fetch 用了**絕對路徑** `/data/latest/backtest_report.json`：
專案型 GitHub Pages 的網站實際在 `https://<user>.github.io/<repo>/`，
絕對路徑會跑到網域根目錄 → 404。

而且這個錯誤**在本機完全測不出來**（本機開檔案或用相對根目錄伺服器時，
絕對路徑剛好有效），只有部署到 GitHub Pages 才會爆。

這份測試把「資料路徑必須是相對路徑」釘死。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

REPO = Path(__file__).resolve().parents[2]
FRONTEND = ("app.js", "data.js")

# fetch('...') / fetchJSON('...') / fetch(`...`) 的字串或樣板字串
_FETCH_RE = re.compile(
    r"""fetch(?:JSON)?\(\s*[`'"]([^`'"]*data/latest[^`'"]*)[`'"]""",
)


def _fetch_urls(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    return _FETCH_RE.findall(text)


def test_frontend_files_exist():
    for name in FRONTEND:
        assert (REPO / name).exists(), f"缺少前端檔案 {name}"


def test_data_paths_are_relative():
    """
    所有指向 data/latest 的 fetch 必須是**相對**路徑。

    絕對路徑在專案型 GitHub Pages 會 404，但在本機看不出來。
    """
    offenders = []
    for name in FRONTEND:
        for url in _fetch_urls(REPO / name):
            if url.startswith("/"):
                offenders.append(f"{name}: {url}")
    assert not offenders, (
        "以下是絕對路徑，在專案型 GitHub Pages 會 404：\n" + "\n".join(offenders)
    )


def test_data_paths_have_cache_busting():
    """
    data/latest 的 fetch 必須帶 cache-busting 參數。

    GitHub Pages 對靜態檔設了 max-age，
    就算 fetch 帶 cache:'no-store'，瀏覽器仍可能回傳記憶體快取，
    導致頁面顯示舊的報告。data.js 原本就有這個處理，app.js 必須比照。
    """
    offenders = []
    for name in FRONTEND:
        text = (REPO / name).read_text(encoding="utf-8")
        for url in _fetch_urls(REPO / name):
            # 抓的是呼叫點那一行的內容（樣板字串會跨行）
            idx = text.find(url)
            window = text[max(0, idx - 200): idx + len(url) + 200]
            if "bust" not in window and "Date.now()" not in window:
                offenders.append(f"{name}: {url}")
    assert not offenders, (
        "以下資料路徑沒有 cache-busting，會拿到舊資料：\n" + "\n".join(offenders)
    )


def test_script_tags_are_versioned():
    """
    app.js / data.js 的 script 標籤必須帶版本參數。

    靜態站部署新版本後，瀏覽器與 CDN 都會快取舊的 JS ——
    症狀是「改了程式但網站沒變」，而且本機開發完全看不出來。
    2026-10-25 實測：修正相對路徑後重新部署，線上仍是舊的 app.js。
    """
    offenders = []
    for name in ("index.html", "factors.html", "backtest.html", "scoring.html"):
        html = (REPO / name).read_text(encoding="utf-8")
        for m in re.finditer(r'<script src="(app|data)\.js([^"]*)"></script>', html):
            if "?v=" not in m.group(2):
                offenders.append(f"{name}: {m.group(0)}")
    assert not offenders, (
        "以下 script 標籤沒有版本參數，部署後使用者會拿到舊的 JS：\n"
        + "\n".join(offenders)
    )


def test_backtest_page_has_report_container():
    """backtest.html 必須有真實報告的掛載點與說明。"""
    html = (REPO / "backtest.html").read_text(encoding="utf-8")
    assert 'id="backtest-report"' in html, "backtest.html 缺少 backtest-report 容器"
    assert "真實回測報告" in html, "backtest.html 缺少真實報告區塊標題"
    # 示意資料必須明確標示為示意
    assert "示意" in html, "示意圖表必須標示為示意，不可與真實報告混淆"


def test_app_js_renders_backtest_report():
    """app.js 必須真的把報告畫出來（不是只有一個空容器）。"""
    js = (REPO / "app.js").read_text(encoding="utf-8")
    assert "renderBacktestReport" in js
    assert "sufficient_for_strategy" in js, "必須依報告的 sufficient_for_strategy 決定文案"
    assert "不可解讀為策略績效" in js, "樣本不足時必須強制標示不可解讀為策略績效"


def test_backtest_report_container_is_not_prefilled_with_fake_data():
    """
    容器初始內容不可是假 KPI。

    「載入中…」是誠實的；「+12.4%」是假的。
    """
    html = (REPO / "backtest.html").read_text(encoding="utf-8")
    idx = html.find('id="backtest-report"')
    assert idx != -1
    snippet = html[idx: idx + 400]
    assert "+12.4%" not in snippet, "報告容器內不可預填假 KPI"
    assert "載入中" in snippet or "載入" in snippet, "應顯示載入狀態"


if __name__ == "__main__":
    import sys as _sys
    from pathlib import Path as _Path

    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
    from backend.tests._runner import run_tests

    run_tests(globals(), "frontend_assets")
