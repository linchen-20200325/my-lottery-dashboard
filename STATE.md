# STATE — my-lottery-2026

## 專案目標
2026 年度大樂透 (Lotto 6/49) 資料分析與預測平台，部署於 Streamlit Cloud。

## 技術棧
- Python (`.py` only)
- Streamlit + `st.cache_data`
- 抓取：requests + BeautifulSoup (lxml)
- 資料：pandas + CSV

## 目錄結構
```
my-lottery-2026/
├── src/scraper/lotto649_downloader.py   # 大樂透歷史開獎下載器
├── data/lotto649.csv                    # (執行後生成)
├── requirements.txt
├── CLAUDE.md   # Core Protocol v2.0
└── STATE.md
```

## 目前進度
- [x] 專案協議初始化
- [x] 大樂透下載器（500 期、官網 API + Pilio 備援、增量更新）
- [ ] Streamlit 介面
- [ ] 統計分析模組
- [ ] 預測演算法

## 常用指令
```bash
python -m src.scraper.lotto649_downloader --periods 500
python -m src.scraper.lotto649_downloader --source pilio -v
```

## 分支
`claude/init-system-protocol-NOnrn`
