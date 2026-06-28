# scripts/archive — 已執行完畢的一次性腳本(請勿再執行)

本資料夾保存 **v3.7 一次性資料修補腳本**,留作血緣紀錄(CLAUDE.md §2.2)。
它們**已在 v3.7 執行完畢**,任務即「修補既有 bug」而非常態流程,**不應再被執行**
(再跑會對已乾淨的 `data/*.csv` 重複改寫)。`src/`、`tests/`、CI workflow 皆未引用。

| 檔案 | 一次性任務 | 已被 canonical 取代的邏輯 |
|---|---|---|
| `sanitize_legacy_dates.py` | 清洗 `data/lotto649.csv` 的合成 2026 日期污染 | 日期合法性驗證 → `scraper._canon_date`(現 `scraper/_dates.canon_date`) |
| `import_powerball_history.py` | 匯入威力彩歷史並正規化 term/date | `clean_date()` → `canon_date`;`_sort_key()` → `scraper._term_sort_key` |

> 若未來需要同類資料修補,請以現行 `src/scraper/` canonical 函式撰寫新腳本,不要復用本資料夾的陳舊副本。
