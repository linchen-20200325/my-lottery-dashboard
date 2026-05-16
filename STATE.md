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
- [~] **爬蟲自動更新歷史資料** — workflow 已上 main，2026-05-15 首跑失敗 (issue #8)；scraper v3.1 直打 API + UA + retry 修復，待 workflow_dispatch 驗證
  - 開獎時程：**每週二、週五**；抓檔時間 **22:00 (GMT+8)** → cron `0 14 * * 2,5`
  - 實作：`.github/workflows/update-history.yml`（checkout → setup-python 3.11 → pip install → scraper `--periods 50` → diff → 直推 main → 失敗開 issue）
  - **2026-05-15 失敗根因**：`taiwanlottery` PyPI wrapper 無 UA / retry / 診斷 log，官方 API 回非 JSON 時直接炸 `JSONDecodeError`
  - **v3.1 修復**：scraper 改直打 `api.taiwanlottery.com`，加 Mozilla UA + Referer + `urllib3.Retry`（429/5xx）+ JSON-decode 外層 retry（3 次指數 backoff）+ 失敗時記錄 status / content-type / body preview
  - 防呆：scraper 抓不到拋 RuntimeError、CSV 不覆蓋；`git diff --quiet` 偵測無變動則跳過 commit
  - 失敗通知：`if: failure()` step 用 `gh issue create` 開 issue（含 run URL）
  - 待驗證：v3.1 推上 main 後，手動觸發 `workflow_dispatch` 跑 dry run；若仍失敗則檢查 issue body 的 diagnostic log 看 Actions runner IP 是否被擋；無誤後此項打 `[x]`

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
