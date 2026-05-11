# STATE — my-lottery-2026

## 專案目標
大樂透 (6/49) 多因子量化選號系統。Streamlit Cloud 線上 App。
EV<0 認知；不預測未來，僅壓縮包牌成本 + 過濾劣質組合。

## 技術棧
- Python 標準庫（`random`, `itertools`）為核心
- Streamlit（UI）
- 無 `pandas` / `numpy`（協定 §6 禁用）
- 部署：GitHub → Streamlit Cloud（入口 `streamlit_app.py`）

## 目錄結構
```
my-lottery-2026/
├── streamlit_app.py                     # Streamlit Cloud 入口
├── src/
│   ├── generator/lotto_picker.py        # 四階段過濾核心（stdlib only）
│   └── scraper/lotto649_downloader.py   # 離線工具（不接入 app）
├── tests/test_lotto_picker.py           # 13 個單元測試
├── data/                                # （執行 scraper 後生成 CSV）
├── requirements.txt
├── CLAUDE.md
└── STATE.md
```

## 演算法（協定 §6 摘要）
Phase 1 Pool Reduction → Phase 2 Pillar & Drag → Phase 3 Shuffle → Phase 4 Filters
濾網：`120 ≤ sum ≤ 180`、`odd ∈ {2,3,4}`、`big(>31) ≥ 3`

## 目前進度
- [x] 協議初始化（Core Protocol v2.0 + §6 Domain）
- [x] 大樂透下載器（offline；不接入 app）
- [x] 四階段量化選號核心 + 13 單元測試
- [x] Streamlit UI（側欄輸入、產出組合、每注診斷）
- [ ] 部署 Streamlit Cloud（待 push 後從 share.streamlit.io 連接 repo）
- [ ] 包牌成本計算 / 命中率回測模組

## 常用指令
```bash
# 本地預覽
streamlit run streamlit_app.py
# 跑測試
python -m unittest discover tests -v
# 離線下載歷史資料（非協定 §6 範疇，僅供研究）
python -m src.scraper.lotto649_downloader --periods 500
```

## 部署 (Streamlit Cloud)
1. Push 到 GitHub `claude/init-system-protocol-NOnrn`（或合併進 main）
2. 至 https://share.streamlit.io 連接 repo
3. Main file：`streamlit_app.py`
4. Python 版本 3.10+
