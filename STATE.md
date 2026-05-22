# STATE — my-lottery-2026

> 📐 **架構藍圖** → [`ARCHITECTURE.md`](./ARCHITECTURE.md)（模組依賴、資料流、五階段細節、CI 設計）
> 📜 **治理協議** → [`CLAUDE.md`](./CLAUDE.md)
> 本檔僅維持「**當前進度 + 常用指令**」（協定 §1 冷熱分離）

## 專案目標
大樂透 (6/49) 量化訊號儀表板 (v5.0)。Streamlit Cloud 線上 App。
Signal-Driven · Defensive Architecture · Performance First。EV<0 認知；不預測。

## 技術棧
- Python 標準庫（`random`, `itertools`, `collections`, `statistics`）為核心
- Streamlit（UI）+ `@st.cache_data(ttl=3600)`、`math.comb`（成本計算）
- 離線輔助：`taiwanlottery` (PyPI) 抓檔
- 無 `pandas` / `numpy`
- 部署：GitHub → Streamlit Cloud（入口 `streamlit_app.py`）

## 目錄結構
```
my-lottery-2026/
├── streamlit_app.py                       # Streamlit 入口 (v5.0 UI + 容錯)
├── src/
│   ├── generator/
│   │   ├── history_engine.py              # Z-Score 冷熱 + SMA 動態和值 + STATIC_FALLBACK
│   │   └── lotto_picker.py                # 五階段五濾網主流程
│   ├── data/loader.py                     # CSV/JSON 載入 (檔案 / 字串 / 上傳)
│   ├── analytics/
│   │   ├── cost_calc.py                   # 包牌成本（live app 可用）
│   │   ├── backtest.py                    # 離線命中率回測 CLI
│   │   └── metrics.py                     # compression_rate + survival_rate (§3)
│   └── scraper/lotto649_downloader.py     # 離線抓檔 v3.1（直打官方 API + UA + retry）
├── data/lotto649.csv                      # 倉庫內附歷史資料（真實 518 期 / 2026-05-12 截止）
├── tests/                                 # 80 個單元測試
├── .github/workflows/update-history.yml   # CI 自動抓檔 (Phase 6, 週二/五 22:00)
├── requirements.txt
├── CLAUDE.md
├── ARCHITECTURE.md                        # 系統架構藍圖 (冷資料)
└── STATE.md                               # 當前進度 (熱資料)
```

## 演算法 v5.0
五階段（訊號 → cache + 降級 → shuffle → 五濾網）+ §3 回測指標。
**詳細**請見 [`ARCHITECTURE.md` §4-5](./ARCHITECTURE.md)。

## 目前進度
- [x] Core Protocol v2.0 + §6 Domain v5.0
- [x] 歷史抓檔（`taiwanlottery` 套件）
- [x] Z-Score 動態訊號引擎 (`history_engine.py` v5.0)
- [x] 五階段五濾網選號核心 (`lotto_picker.py` v6) + 68 單元測試
- [x] Streamlit UI v5.0（cache + fallback + 滑桿 + 動態/手動覆寫）
- [x] 回測指標 (`src/analytics/metrics.py`)
- [x] 倉庫內附 50 期合成樣本（CSV）
- [x] 部署 Streamlit Cloud（手動）  ✅ 2026-05-12 上線、UI 全綠
- [x] 用真實 518 期資料覆蓋合成樣本  ✅ 2026-05-12（compression 14.99% / survival 14.86%）
- [x] UI 最近 N 期歷史預覽（驗證資料正確性，slider 1-20）  ✅ 2026-05-13
- [x] v6 auto-key silent drop + Phase 4 Round 2 disjoint fallback  ✅ 2026-05-14

## 後續規劃 (Phase 6 — Future Work)
- [x] **修正『觸發 GitHub Actions 抓檔』按鈕 URL**  ✅ 2026-05-18（舊倉庫 `CornCorn-2015/my-lottery-2026` → 新倉庫 `LinChen-20200325/my-lottery-dashboard`，使用者點擊不再 404）
- [x] **爬蟲自動更新歷史資料**  ✅ 2026-05-16（v3.3 + repo toggle 全鏈打通；CSV 519 期，最新 2026/5/15）
  - 開獎時程：**每週二、週五**；抓檔時間 **22:00 (GMT+8)** → cron `0 14 * * 2,5`
  - 實作：`.github/workflows/update-history.yml` + `src/scraper/lotto649_downloader.py`
  - **第一層 (v3.0 → v3.1)**：舊 `taiwanlottery` PyPI wrapper 無 UA/retry/log → 直打 `api.taiwanlottery.com` + Mozilla UA + Referer + `urllib3.Retry` (429/5xx) + JSON-decode 外層 retry
  - **第二層 (v3.1 → v3.2)**：v3.1 scraper 通了但 `git push origin main` 被 main branch protection 擋 → 改 PR 流程（建分支 → `gh pr create` → `gh pr merge --squash --auto`）
  - **第三層 (v3.2 → v3.3)**：v3.2 跑出兩個新 bug：
    1. **Scraper dedup bug** — 官方 API 改用新期別編碼 (e.g. `115000053` 取代 `2447`)，舊 dedup key 用 `draw_term` → 同一期出兩列。**修復**：`download()` 改用 canonical `draw_date` 比對新 fetched 與既有 CSV，已存在日期跳過；既有 CSV 列**永不覆蓋**（保留歷史 as-is）
    2. **Workflow `set -e` brittleness** — `PR_URL=$(gh pr create ...)` 失敗時 set -e 直接 kill，連 fallback 也吃不到。**修復**：每個關鍵命令獨立錯誤 trap，PR 建立失敗會把 stderr 印到 log；merge fallback 改 if/elif 鏈確保 step 一定綠燈
  - **第四層 (v3.3 → 完成)**：v3.3 scraper + workflow 邏輯全綠，但 `gh pr create` 仍紅 — 根因**不在 YAML**，而是 **Repo Settings → Actions → General → Workflow permissions → "Allow GitHub Actions to create and approve pull requests"** 預設 OFF（獨立於 YAML `permissions:` 區塊的 repo 級開關，YAML 改不掉）。**修復**：手動勾選該開關 + Save。驗證：MCP token 帶 `pull-requests: write` 可建 PR (#17) 並 squash 進 main，證明 scraper/workflow 邏輯本身已就緒；toggle 翻完後下個 cron (週二 22:00) 即可自動運作
  - **第五層 (v3.4 — 偽綠燈)**：2026-05-21 手動觸發 run #3 顯示 Success 39s 但無 PR、CSV 仍停在 5/15。根因：`fetch()` 對單月 API 失敗只 `LOGGER.warning + continue`；當月 (idx=0) fetch 被 Cloudflare 擋掉時，舊月仍能跑出已知舊資料 → `download()` 看到 `added=0` → `git diff --quiet` 真的沒變 → workflow 偽綠燈，stale CSV 永遠不更新。**修復**：
    1. `fetch()` 當月 (idx=0) 失敗改 `raise RuntimeError`，迫使 workflow 紅燈 + 觸發 issue
    2. `fetch()` 加 per-month INFO log（API returned N row(s)）
    3. `download()` 加診斷 log（`fetched_max / existing_max / added`）便於 Actions log 直接定位
    4. workflow `Run scraper` step 用 `tee /tmp/scraper.log` + `set -o pipefail` 留存輸出
    5. `Open issue on failure` step 把 scraper log tail 50 行包進 issue body（含 HTTP status / body preview / per-month count）
  - **第六層 (v3.5 — 拿掉 PR 噪音)**：v3.2-3.4 走 PR 流程繞 main protection，每次 data 更新都產生 closed PR (週二/五兩枚)。改方案 A：bot 加進 main bypass list、scraper 改回直推 main。**改動**：
    1. workflow YAML 拿掉「建分支 → `gh pr create` → `gh pr merge`」三段，改 `git pull --rebase origin main && git push origin main`
    2. `actions/checkout@v4` 加 `ref: main`，確保從 feature branch 手動 dispatch 也是更新 main 的 CSV
    3. `permissions:` 拿掉 `pull-requests: write`（不再需要）
    4. failure issue body 排查清單更新（PR 失敗模式 → bypass list 漏勾 / rebase 衝突）
    5. **Repo Settings 必動**：Settings → Branches → `main` → Edit protection rule → 勾「Allow specified actors to bypass required pull requests」→ 加 `github-actions[bot]`（YAML 無法覆蓋此 repo 級開關，類似 v3.3 的「Allow Actions to create PRs」toggle）
  - 防呆：existing 列即便 date 欄錯亂也保留；`if not fetched` raise；`git diff --quiet` 跳過無變動
  - 測試：92 個 unit tests 全綠（新增 `test_current_month_failure_raises` / `test_older_month_failure_does_not_raise` / `test_diagnostic_log_present`）

## 常用指令
```bash
# 本地預覽
streamlit run streamlit_app.py
# 跑測試
python -m unittest discover tests -v
# 抓真實歷史（本機，需網路）
python -m src.scraper.lotto649_downloader --periods 500
# 離線回測 (命中率)
python -m src.analytics.backtest --csv data/lotto649.csv --lookback 30
# 濾網診斷 (壓縮率 + 存活率)
python -m src.analytics.metrics --csv data/lotto649.csv
```

## 部署 (Streamlit Cloud)
1. Push 到 GitHub `main`
2. 至 https://share.streamlit.io 連接 repo
3. Main file：`streamlit_app.py`
4. Python 版本 3.10+
5. UI 內若 `data/lotto649.csv` 過舊或缺檔，會自動降級至靜態安全模式並顯示警告
