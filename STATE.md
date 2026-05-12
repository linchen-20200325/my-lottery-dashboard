# STATE — my-lottery-2026

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
│   └── scraper/lotto649_downloader.py     # 離線抓檔（用 taiwanlottery 套件）
├── data/lotto649.csv                      # 倉庫內附歷史資料（合成樣本/真實）
├── tests/                                 # 53 個單元測試
├── requirements.txt
├── CLAUDE.md
└── STATE.md
```

## 演算法 v5.0（協定 §6 摘要）
- **Phase 1 動態訊號** — Z-Score 冷熱：熱 `≤ max(2, μ−0.5σ)` / 冷 `≥ μ+1.5σ`；動態和值 `SMA(10) ± 30`，clamp `[90, 210]`；過熱/死寂尾數
- **Phase 2 Cache + 優雅降級** — `@st.cache_data(ttl=3600)`；失敗 swap `STATIC_FALLBACK_ANALYSIS` (sum 120-180、無排除) + `st.warning`
- **Phase 3 矩陣均勻化** — `random.shuffle(combinations)`
- **Phase 4 五大濾網** — prime ∈ [1,3], consec_pairs ≤ 2, **動態 sum**, odd ∈ {2,3,4}, big(>31)≥3
- **§3 回測指標** — `compression_rate`（14M 組合留多少）/ `survival_rate`（過去開獎被殺率）

## 目前進度
- [x] Core Protocol v2.0 + §6 Domain v5.0
- [x] 歷史抓檔（`taiwanlottery` 套件）
- [x] Z-Score 動態訊號引擎 (`history_engine.py` v5.0)
- [x] 五階段五濾網選號核心 (`lotto_picker.py` v5.0) + 53 單元測試
- [x] Streamlit UI v5.0（cache + fallback + 滑桿 + 動態/手動覆寫）
- [x] 回測指標 (`src/analytics/metrics.py`)
- [x] 倉庫內附 50 期合成樣本（CSV）
- [x] 部署 Streamlit Cloud（手動）  ✅ 2026-05-12 上線、UI 全綠
- [ ] 用真實 500 期資料覆蓋合成樣本（本機 scraper）

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
