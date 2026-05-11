# STATE — my-lottery-2026

## 專案目標
大樂透 (6/49) 動態量化選號系統 (v3.0)。Streamlit Cloud 線上 App。
EV<0 認知；不預測未來；以動能 + 均值回歸 + 五大靜態濾網雙層過濾，壓縮包牌成本。

## 技術棧
- Python 標準庫（`random`, `itertools`, `collections`）為核心
- Streamlit（UI）、`math.comb`（成本計算）
- 離線輔助：`taiwanlottery` (PyPI) 抓檔
- 無 `pandas` / `numpy`
- 部署：GitHub → Streamlit Cloud（入口 `streamlit_app.py`）

## 目錄結構
```
my-lottery-2026/
├── streamlit_app.py                       # Streamlit 入口 (v3.0 UI)
├── src/
│   ├── generator/
│   │   ├── history_engine.py              # 熱/溫/冷分層 + 雙向尾數排除 + 動態雙膽
│   │   └── lotto_picker.py                # 五階段五濾網主流程
│   ├── data/loader.py                     # CSV/JSON 載入 (檔案 / 字串 / 上傳)
│   ├── analytics/
│   │   ├── cost_calc.py                   # 包牌成本（live app 可用）
│   │   └── backtest.py                    # 離線命中率回測 CLI
│   └── scraper/lotto649_downloader.py     # 離線抓檔（用 taiwanlottery 套件）
├── data/lotto649.csv                      # 倉庫內附歷史資料（合成樣本/真實）
├── tests/                                 # 41 個單元測試
├── requirements.txt
├── CLAUDE.md
└── STATE.md
```

## 演算法 v3.0（協定 §6 摘要）
- **Phase 1 動態歷史分析** — 熱(≤2 期) / 溫(3-14 期) / 冷(≥15 期)；過熱尾數(近 3 期 ≥4 次) ∪ 死寂尾數(10 期未出) = `exclude_tails`
- **Phase 2 動態雙膽** — 1 熱 + 1 冷；可手動覆寫
- **Phase 3 矩陣均勻化** — `random.shuffle(combinations)`
- **Phase 4 五大濾網** — sum 120-180, odd ∈ {2,3,4}, big(>31)≥3, prime ∈ [1,3], consecutive_pairs ≤ 2

## 目前進度
- [x] 協議升級 Core Protocol v2.0 + §6 Domain v3.0
- [x] 歷史抓檔 (改用 `taiwanlottery` PyPI 套件)
- [x] 動態歷史引擎 (`history_engine.py`)
- [x] 五階段選號核心 (`lotto_picker.py` v3.0) + 41 單元測試
- [x] Streamlit UI v3.0（上傳 / 滑桿 / 動態手動雙模）
- [x] 包牌成本計算 + 離線回測 CLI
- [x] 倉庫內附 50 期合成樣本（CSV）
- [ ] 部署 Streamlit Cloud（手動）
- [ ] 用真實 500 期資料覆蓋合成樣本

## 常用指令
```bash
# 本地預覽
streamlit run streamlit_app.py
# 跑測試
python -m unittest discover tests -v
# 抓真實歷史（本機，需網路；會覆蓋 data/lotto649.csv）
python -m src.scraper.lotto649_downloader --periods 500
# 離線回測
python -m src.analytics.backtest --csv data/lotto649.csv --lookback 30
```

## 部署 (Streamlit Cloud)
1. Push 到 GitHub `main`
2. 至 https://share.streamlit.io 連接 repo
3. Main file：`streamlit_app.py`
4. Python 版本 3.10+
5. UI 內若 `data/lotto649.csv` 過舊，使用「上傳 CSV」選項覆寫
