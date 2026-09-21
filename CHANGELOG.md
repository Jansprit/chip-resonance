# Changelog

All notable changes to the 籌碼共振選股系統 (Chip-Resonance Selection System).

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
