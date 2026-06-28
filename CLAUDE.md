# CLAUDE.md — 資料完整性憲法

> 本檔為 AI 協作的最高行為準則,目標:確保資料**真實、可追溯、計算正確、可重現**。
> 違反本檔任一條視同 bug,須當場修正。

---

## §1. 最高原則:Fail Loud, Never Fake(寧可炸掉,不可造假)

凌駕一切的鐵律。錯誤的數字比沒有數字更危險。

當缺資料、外部呼叫失敗、值異常、或假設無法成立時:

- ✅ **一律 `raise` 並清楚說明**(哪個來源、哪幾筆、為什麼)
- ❌ **禁止**用以下手段讓流程「看起來成功」:
  - `fillna(0)` / 填入任意預設值
  - 無說明的 `ffill` / `bfill`
  - 回傳 dummy / example / 範例資料
  - `except: pass` 或吞掉例外
  - 自行「估一個合理值」當常數
- ⚠️ 任何填補**必須**:(1) 顯式呼叫、(2) 寫入 log、(3) 在輸出帶旗標(如 `is_imputed`)

> **判斷準則**:若你正打算寫一段「讓程式不報錯」的程式碼,先問:
> 「這是在**解決**問題,還是在**掩蓋**問題?」掩蓋 = 違憲。

> **本專案的合法 fallback**:`STATIC_FALLBACK_ANALYSIS`(`history_engine.py:71-82`、`powerball_engine.py:69-87`)在歷史 CSV 載入失敗時取代動態訊號,**必須**伴隨 `analysis.is_fallback=True` 旗標 + UI `st.caption("⚠️ 靜態 Fallback")`(`lotto649_view.py:339`)。任何呼叫端見到 `is_fallback=True` 都不得當作正常訊號用。

---

## §2. 資料層(Data Integrity)

### 2.1 SSOT — 單一權威來源

**權威分級(由高至低,衝突時上層獲勝)**:

| 級 | 來源 | 路徑 | 備註 |
|---|---|---|---|
| 1 | 官方台彩 API | `api.taiwanlottery.com/TLCAPIWeB/Lottery/Lotto649Result`(大樂透)、`/SuperLotto638Result`(威力彩) | **僅在離線 scraper 端呼叫**(GitHub Actions cron);Streamlit Cloud 端絕不發 |
| 2 | 倉庫內附 CSV | `data/lotto649.csv`、`data/powerball.csv` | scraper 抓檔 + 按 `_term_sort_key` 排序產出;**append-only**,既有列**永不覆蓋**(`lotto649_downloader.py:284-290`) |
| 3 | UI 手動上傳 CSV/JSON | `loader.load_csv_file/string`、`load_json_string` | 使用者校正用,臨時優先生效,**不寫回 repo** |
| 4 | UI 貼上文字 | 同上;`load_auto()` 自動判 JSON/CSV | 同上 |

**重要**:Streamlit Cloud 端**不發外部 API**;runtime 只能用 #2-#4。所有 live app 路徑必須能在 zero-network 下完成(舊 `CLAUDE.md §6 「果斷棄爬」`)。

**禁止取平均**:同一期(同 `draw_date`)若 #2 與 #3 衝突,UI 上傳暫時覆蓋顯示但**不**寫回 CSV;cron 下次拉取以 #1 為準。

### 2.2 Provenance — 血緣追蹤

CSV schema 已內建血緣欄位:`draw_term`(來源 ID)、`draw_date`(資料歸屬日)。
Scraper 自帶 `LOGGER.info("API %s-%s: returned %d row(s)")`(`lotto649_downloader.py:213`),抓取時間與來源月份雙軌可追溯(Actions log 永久保留)。

```python
# 通用 provenance dataclass(template 範例,本專案因 stdlib-only 未強制 wrap)
from dataclasses import dataclass
from datetime import datetime, date

@dataclass(frozen=True)
class DataPoint:
    value: float
    source: str            # 來源識別
    fetched_at: datetime   # UTC,抓取當下
    as_of: date            # 資料歸屬日期(≠ 抓取日,極重要)
```

**包裝層已就位**(v6.7):`src/data/provenance.py` 的 `HistoryProvenance` dataclass 持有 `source / fetched_at / as_of / earliest / n_rows`;loader 提供 `load_*_with_provenance()` additive 變體(`loader.py:74-103`、`loader_powerball.py:65-92`)。引擎 dataclass(`HistoryAnalysis` / `PowerballAnalysis`)**故意維持純信號狀態**,不灌 provenance — 避免污染 stdlib-only 測試 fixture 與引擎 cache key。

### 2.3 Point-in-Time — 防 Lookahead / 用「當時可得」的資料

**發布延遲**:

| 來源 | 開獎時間 (GMT+8) | API 上線延遲 | 對應 cron 槽位 |
|---|---|---|---|
| 大樂透 | 週二、週五 21:30 | 30-60 分 | `23/53/23/23` 分(`update-history.yml`,22:23 → 翌日 00:23,4 槽) |
| 威力彩 | 週一、週四 20:00 | 30-60 分 | `7/37/7/37` 分(`update-powerball.yml`,翌日 00:07 → 01:37,4 槽) |

**回溯修正(restatement)**:**不適用** — 台彩開獎結果一旦公告即為定稿,實務上不會回溯。歷史唯一一次資料變動是 v3.7「合成 date 污染清洗」(`scripts/sanitize_legacy_dates.py`、`scripts/import_powerball_history.py`),屬**修補既有 bug** 而非 official restatement。

**回測 lookahead 防護**(v6.3.1 已落地):
- `src/analytics/backtest.py:71-73` 使用 `history = rows[k+1:k+1+lookback]`(嚴格 newest-first 之後 = 較舊)
- `src/analytics/backtest.py:_assert_newest_first()` 不變量斷言 — oldest-first CSV 直接 raise
- `src/scraper/*_downloader.py:_term_sort_key()` 保證 `save_csv()` 輸出 newest-first

### 2.4 Freshness — 新鮮度

**規則**:不用「N 天滾動窗口」,改用**開獎日 + 當日 22:00 GMT+8** 截止線(因雙樂透開獎日不同,各算各的)。

| 樂透 | 開獎日 (GMT+8) | 預期新鮮截止 | 過了截止仍無新資料 → |
|---|---|---|---|
| 大樂透 | 週二 (`weekday()==1`)、週五 (`weekday()==4`) 21:30 | **當日 22:00 GMT+8** | UI `st.warning` + 提示觸發 GitHub Actions |
| 威力彩 | 週一 (`weekday()==0`)、週四 (`weekday()==3`) 20:00 | **當日 22:00 GMT+8** | 同上 |
| Cron run 失敗 | — | 立即 | 自動開 issue 帶 log tail 50 行(`update-history.yml:77-107`)✅ 已有 |

**判定邏輯**(描述,實作待補於 `lotto649_view.py` / `powerball_view.py` 的 `_load_bundled()` 後):

```python
# 範式;以「最近一個已過 22:00 截止線的開獎日」當預期新鮮日期
def expected_latest_draw(now_gmt8: datetime, draw_weekdays: set[int]) -> date:
    """大樂透傳 {1,4},威力彩傳 {0,3}。"""
    today = now_gmt8.date()
    for back in range(0, 8):
        cand = today - timedelta(days=back)
        if cand.weekday() not in draw_weekdays:
            continue
        if back == 0 and now_gmt8.hour < 22:
            continue  # 今天是開獎日但未到 22:00 截止線
        return cand
    raise RuntimeError("unreachable")

# UI 端使用
if parse_csv_latest_date(history) < expected_latest_draw(now, {1, 4}):
    st.warning("⚠️ CSV 已落後 — 觸發 GitHub Actions 抓檔或上傳最新 CSV")
```

**已落地**(v6.5):`src/data/freshness.py` 實作上述邏輯;兩 UI view 各自加 `_freshness_warning()` cached helper(`ttl=600`),倉庫 CSV 過期顯示 `st.warning("⏰ 資料可能過期...")`。僅檢查 #2 倉庫內附 CSV,#3 上傳/#4 貼上路徑由使用者負責。

---

## §3. 驗證層(Validation)— 不符合契約就拒收

### 3.1 邊界契約(Schema)

本專案禁 `pandas` / `numpy`,**不使用 pandera**。Schema 由 stdlib 函數實現(每列每欄手動 validate + raise):

| 欄位 | 型別 | 約束 | 驗證點 |
|---|---|---|---|
| `draw_term` | `str` | 非空;`int(term)` 可解析;`_term_sort_key` 分桶 | `lotto649_downloader.py:247-268` |
| `draw_date` | `str` | 空字串(已清洗,合法)或 `YYYY/MM/DD` 且 `datetime.date(y,m,d)` 合法 | `canon_date()`(`scraper/_dates.py`,SSOT;v6.22 起兩 scraper `_canon_date` 委派之;v6.3.1 已加日期合法性驗證) |
| `n1..n6` | `int` | 大樂透 ∈ [1, 49] 且 6 顆無重複;威力彩 ∈ [1, 38] 且 6 顆無重複 | `loader.py:27-39`、`loader_powerball.py:23-37` |
| `special` | `int` | 大樂透 ∈ [1, 49];威力彩 ∈ [1, 8] | `loader_powerball.py:40-45`(大樂透特別號目前 loader 未獨立驗證,scraper 端寫入時保證) |
| `draws: list[list[int]]`(in-memory) | sequence | newest-first;每列 6 unique ints | `history_engine.py:185`、`powerball_engine.py:204` |
| `specials: list[int]`(in-memory) | sequence(powerball only) | 每元素 ∈ [1, 8] | `powerball_engine._bonus_analyze():170-185`(v6.3.1 後 raise) |

**`lazy=True` 等價**:本專案的 validate 一遇錯即 raise(不收集多筆),設計上是 fail-fast 而非 batch report。歷史已驗證過的 CSV 列無需重 validate。

### 3.2 範圍 / 合理性檢查

**寫死的領域知識**(每條都對應一個 raise / assert):

| # | 規則 | 來源 | 驗證點 |
|---|---|---|---|
| 1 | 大樂透:6 顆主號 ∈ [1, 49] 且唯一 | 台彩規則 | `loader.py:27-39` |
| 2 | 大樂透:特別號 ∈ [1, 49] | 台彩規則 | scraper 寫入點 |
| 3 | 威力彩:6 顆第一區 ∈ [1, 38] 且唯一 | 台彩規則 | `loader_powerball.py:23-37` |
| 4 | 威力彩:第二區 ∈ [1, 8] | 台彩規則 | `loader_powerball.py:40-45` |
| 5 | 膽碼數量 ∈ [1, 5] | 演算法設計 | `lotto_picker.py:39-40` `MIN/MAX_KEY_NUMS` |
| 6 | 排除尾數 ∈ [0, 9] | 數學域 | `lotto_picker._validate_range()` 內聯 |
| 7 | 注數 ≥ 1 | UI 契約 | `lotto_picker.py:217-218` |
| 8 | 和值動態區間:大樂透 clamp `[90, 210]` | 物理上下界(理論 [21, 279];SMA pad=±30 後安全帶) | `history_engine.py:37-38` `DEFAULTS["sum_clamp_lo/hi"]` |
| 9 | 和值動態區間:威力彩 clamp `[80, 154]` | 同上(理論 [21, 213];池小→pad=±25) | `powerball_engine.py:37-38` |
| 10 | 質數集:大樂透 = 15 個 ≤ 49 的質數 | 數學常數 | `lotto_picker.py:42-44` `PRIMES_SET` |
| 11 | 質數集:威力彩 = 12 個 ≤ 38 的質數(裁掉 41/43/47) | 數學常數 | `powerball_picker.py:42-44` |
| 12 | 大數門檻:大樂透 > 31 | 49 中位 | `lotto_picker.py:37` `BIG_THRESHOLD` |
| 13 | 大數門檻:威力彩 > 19 | 38 中位 | `powerball_picker.py:37` |
| 14 | 連號對數 ≤ 2 | 演算法設計 | 兩 picker `MAX_CONSECUTIVE_PAIRS` |
| 15 | 奇數數量 ∈ {2, 3, 4} | 演算法設計 | 兩 picker `ALLOWED_ODD_COUNTS` |
| 16 | 大數至少 3 顆 | 演算法設計 | 兩 picker `MIN_BIG_COUNT` |
| 17 | 質數 ∈ [1, 3] | 演算法設計 | 兩 picker `MIN/MAX_PRIME_COUNT` |
| 18 | pair-disjoint 模式:膽碼 ≤ 1 顆 | 邏輯互斥(2 顆膽會強制 key-pair 重複) | `lotto_picker.py:319-324` |
| 19 | gap (遺漏期數) ∈ [0, len(history)] | 物理定義 | `history_engine._gaps()` |
| 20 | gap_std floor = `min_std = 1.0` | 防 Z-Score /0 | `history_engine.py:203` |
| 21 | **Howard 模式**:sum ∈ [115, 185] | Gail Howard《Lottery Master Guide》#1 | `lotto_picker.py` `HOWARD_SUM_MIN/MAX` |
| 22 | **Howard 模式**:小數(≤24)∈ {2, 3, 4} | Howard #3 切分 24/25 雙向 | `lotto_picker.py` `HOWARD_SMALL_THRESHOLD/HOWARD_ALLOWED_SMALL_COUNTS` |
| 23 | **Howard 模式**:同尾恰 1 對(軟分) | Howard #4 | `_howard_soft_score()` |
| 24 | **Howard 模式**:字頭空 1-2 個(軟分) | Howard #5 | `HOWARD_MAX_EMPTY_DECADES` 配 `MIN_EMPTY_DECADES` |
| 25 | **Howard 模式**:連號恰 1 對(軟分) | Howard #6 | `HOWARD_EXACT_CONSEC_PAIRS` |
| 26 | **Howard 模式**:gap≤5 顆數 ∈ {4, 5}(軟分) | Howard #7 | `HOWARD_GAP5_THRESHOLD/ALLOWED_COUNTS` |
| 27 | **Howard 模式**:含上期 1 顆(軟分) | Howard #8 | `HOWARD_REPEAT_FROM_LAST` |
| 28 | **Howard 模式**:軟分 ≥ 3/5 才通過 | 平衡硬綁與彈性 | `HOWARD_SOFT_MIN_SCORE` |
| 29 | **Howard 模式**:史料 ≥ 5 期 + 非 fallback,否則 raise | §1 Fail Loud(UI 端先擋並降回 v6.16) | `generate_tickets()` |
| 30 | **Abbreviated Wheel**:池大小 = 12、每注 = 6、覆蓋 t=4 / 保證 p=3(4保3) | 自家 greedy set-cover 計算(L(12,6,4,3) ≤ 8;Gail Howard《Lotto Wheel Five to Win》理論依據) | `abbreviated_wheel.py` `WHEEL_SIZE/WHEEL_GUARANTEE_T/WHEEL_GUARANTEE_P` |
| 31 | **Abbreviated Wheel**:8 注覆蓋全 495 個 4-subset | 暴搜測試驗證 | `tests/test_abbreviated_wheel.py::TestWheelInvariant::test_4_in_4_guarantee_3_exhaustive` |
| 32 | **Abbreviated Wheel**:不過 v6.16/Howard 濾網 | 濾網會破壞 covering 數學保證;故意不混用 | `abbreviated_wheel.py` module docstring |

### 3.3 反捏造(Anti-Fabrication)

- **禁止 magic number**:常數一律從 `DEFAULTS` dict / 模組頂 const 讀,並附來源註解;**不准腦補**。
- **禁止無聲填補**:本專案無 `fillna` / `ffill`(無 pandas);任何 fallback 必須帶 `is_fallback=True` 旗標。
- **禁止 dummy data 流入正式路徑**:`tests/` 與 `src/` 物理隔離;`generate_tickets(history_draws=[[1,2,3,4,5,6]])` 這種 sanity input 只能在 test 用。
- **禁止 `except: pass`**:全專案 grep 結果僅 `streamlit_app.py:536` 一處(`cost_summary` ValueError 容錯),且行為等同 `except ValueError: return None`(只跳過該 UI panel,不污染資料)— 合規。

**該寫死、禁止腦補的關鍵常數**:

| 常數 | 值 | Provenance |
|---|---|---|
| `UNIT_PRICE_TWD` | 50 | 台彩 2014 調整後單注價(`cost_calc.py:19`) |
| `PRIZE_TWD[6/5/4/3]` | 100M / 150K / 2K / 400 | `backtest.py:32-37`(名目估算,僅作演算法行為審視用,非分潤後實際) |
| 大樂透 cron 槽位 | UTC `23/53/23/23` 分 `14/14/15/16` 時 | 開獎 21:30 GMT+8 + 30-60 分 API 延遲;`update-history.yml:8-11` |
| 威力彩 cron 槽位 | UTC `7/37/7/37` 分 `16/16/17/17` 時 | 開獎 20:00 GMT+8 + 翻日 4 槽;`update-powerball.yml:8-11` |
| `JSON_RETRY_ATTEMPTS = 3` / `JSON_RETRY_BACKOFF = 2.0` | API 容錯 | `lotto649_downloader.py:59-60` |
| `REQUEST_TIMEOUT = 15` 秒 | API 容錯 | `lotto649_downloader.py:58` |

**已落地**(v6.4)— 兩 scraper 同步抽出:
- `HTTP_RETRY_TOTAL` / `HTTP_RETRY_BACKOFF`(語義獨立於 JSON_RETRY_*)取代 inline `Retry(total=3, backoff_factor=2.0)`
- `API_PAGE_SIZE = 31` 取代 URL inline
- `MAX_DRAWS_PER_MONTH = 8` / `MONTHS_BUFFER = 2` 取代 `(periods + 7) // 8 + 2`

**已落地**(v6.8):兩 engine 的 `STATIC_FALLBACK_ANALYSIS` 上方加 derivation block,說明 `hot_threshold=2.0`(= `DEFAULTS["hot_threshold_floor"]`)與 `cold_threshold=15.0`(= 每號約 8 期出一次 × `μ + 1.5σ` 保守估算)的來源。

**已落地**(v6.19)— Gail Howard 黃金 8 條(opt-in `howard_mode=True`,僅大樂透):
- `HOWARD_SUM_MIN/MAX = 115/185`(#1)、`HOWARD_SMALL_THRESHOLD = 24` + `HOWARD_ALLOWED_SMALL_COUNTS = {2,3,4}`(#3)— 來源 Gail Howard《Lottery Master Guide》
- `HOWARD_EXACT_TAIL_PAIRS = 1`(#4)、`HOWARD_MAX_EMPTY_DECADES = 2`(#5,配 v6.16 `MIN_EMPTY_DECADES`)、`HOWARD_EXACT_CONSEC_PAIRS = 1`(#6)
- `HOWARD_GAP5_THRESHOLD = 5` + `HOWARD_GAP5_ALLOWED_COUNTS = {4,5}`(#7)、`HOWARD_REPEAT_FROM_LAST = 1`(#8)
- `HOWARD_SOFT_MIN_SCORE = 3`(5 條軟分通過閾值;史料不足條目自動 +1,基數不變)
- `HOWARD_MIN_HISTORY = 5`(史料不足 → §1 Fail Loud raise;UI 端先擋並降回 v6.16 + warn)
- Round 1 套 Howard;Round 2/3 fallback 退回 v6.16 五大濾網(plan 規定)
- v6.16 谷底陷阱 (`MAX_BASEMENT_PER_TICKET = 1`) 在 Howard 模式仍生效(雙重保險)
- 全部都在 `src/generator/lotto_picker.py` 模組頂常數區,UI `src/ui/lotto649_view.py` 透過 import 顯示條文

### 3.4 統計異常偵測

**本專案大致不適用** — 樂透開獎為官方公告,無「人為捏造數字」風險。但相關設計:
- `history_engine._gaps()` 用 `setdefault` 自然忽略重複 draw(若 CSV dedup 漏網,新出現的同 term 不會覆蓋舊值)
- v6.3.1 `_canon_date` 拒絕不存在日期(2026/02/30 等)= 阻擋編碼錯誤造成的偽造日期

未來若加入「使用者下注紀錄」等申報式資料,則須引入 Benford / IQR 檢查。目前無此模組。

---

## §4. 計算層(Computation Correctness)

### 4.1 量綱 / 單位一致性

**幣別**:全程 `NT$`(`UNIT_PRICE_TWD` / `PRIZE_TWD` / `cost_twd` / `payout_twd` / `net_twd` 等變數名都帶 `_twd` 後綴)。

**% vs 小數 — 規則(v6.9 已落地)**:
- `metrics.py` `dict["compression_ratio"]` / `dict["survival_ratio"]` / `dict["estimated_ratio"]`:**小數** (0.0-1.0)
- `backtest.py` `dict["roi_percent"]`:已 ×100 (display-ready)
- 顯示層自行 `*100` 標「%」(`metrics._format()` / `backtest._format_report()`)
- **規則(dict key 命名約束)**:`_ratio` 結尾必為小數 ∈ [0, 1];`_percent` 結尾必為已 ×100。
- 違反 = bug — `tests/test_metrics.py::TestNamingConvention` 起 regression 守門。
- 函數名(operation)用 `_rate` 後綴(如 `compression_rate()`),但**回傳值**透過 `_ratio` key 暴露 — `_rate` 不是值的後綴。

**沒有**:年化 vs 期頻、實質 vs 名目、不同計價幣別等陷阱(樂透域單純,單幣別、單頻率)。

### 4.2 不變量斷言(Invariants)

```python
# 範式(本專案禁 numpy,用 math.isclose / 純比較)
import math
assert math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-12)  # 禁止用 ==
assert all(1 <= n <= 49 for n in ticket) and len(set(ticket)) == 6
assert dates[0] >= dates[-1], "CSV must be newest-first"
```

**本領域必有的不變量**(v6.4 後已全數落地,8 處 `assert` 散在引擎與 scraper):

| 不變量 | 在哪 assert | 現狀 |
|---|---|---|
| `all(1 ≤ n ≤ POOL_MAX and len(set(t))==6 for t in tickets)` | `lotto_picker / powerball_picker` 兩個 return 點 | ✅ v6.4 |
| `set(gaps.keys()) == set(range(lo, hi+1))` | `base_engine.analyze_main_zone()`(v6.23 B4a 收斂;兩 `analyze()` 委派) | ✅ v6.4 |
| `set(hot) ∪ set(warm) ∪ set(cold) == 全 pool` | `base_engine.analyze_main_zone()`(同上) | ✅ v6.4 |
| `sum_min_dynamic ≤ sum_max_dynamic` | `base_engine.analyze_main_zone()`(配合 `_dynamic_sum_range` lo>hi collapse 修復) | ✅ v6.4 |
| `len(merged) >= len(existing)` (append-only 保證) | `_downloader_base.run_download()` 返回前(v6.22 起兩 scraper 委派) | ✅ v6.4 |
| CSV newest-first 順序 | `backtest._read_csv` | ✅ v6.3.1 |
| `history_specials` 全 ∈ [1, 8] | `_bonus_analyze` | ✅ v6.3.1 |
| `bonus_pick ∈ [1, 8]` | `powerball_picker / powerball_engine` 返回前 | ✅ v6.4 |

### 4.3 重算對帳(Reconciliation)

**目前缺口** — 三大指標各只有一條算路:
- `compression_rate`(`metrics.py:68-82`):全 14M 列舉
- `survival_rate`(`metrics.py:85-111`):歷史 CSV 過濾
- `backtest.roi_percent`(`backtest.py:99`):cost vs payout 直算

**應補**:
- `compression_rate` ↔ Monte Carlo 抽 10⁵ 隨機 combos、跑同濾網,survival 比例應收斂至 exact 值(差距 > 1% 視為演算法 bug)
- `survival_rate` ↔ `1 - rejection_rate` 反向對帳(`rejected_count / total == 1 - survival_rate`)
- `backtest` ↔ 用 `random.shuffle` 重抽 seed 跑 N 輪,ROI 標準差應落在合理 confidence interval

浮點比較:**禁 `==`**,一律 `math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-12)`。

### 4.4 數值穩定性

**不適用(本專案多為整數域,無 underflow / overflow / catastrophic cancellation 風險)**。

僅有的浮點:`pstdev(gap_values)` 在 `base_engine.analyze_main_zone()`(v6.23 B4a 收斂;兩引擎委派),由 `min_std = 1.0` floor 防 /0。

### 4.5 時序對齊

- **日曆**:台彩開獎日 — **大樂透週二、週五**;**威力彩週一、週四**。GitHub cron 用 **UTC**;業務時區 **GMT+8 (`Asia/Taipei`)**,固定無夏令時。
- **時區存儲**:CSV `draw_date` 為 `YYYY/MM/DD` 純日期字串(台灣當地日;21:30 開獎不跨午夜,故無時區歧義)。Scraper Actions log 與 issue body 用 `date -u +'%Y-%m-%d %H:%M UTC'` 留 UTC 時戳。
- **resample / 重採樣**:**不適用**(無 pandas)。
- **業務調整**:**不適用** — 樂透開獎結果不需任何 split / dividend / corporate action 還原。

### 4.6 邊界條件

| 邊界 | 既有護網 | 狀態 |
|---|---|---|
| 空 history | `analyze()` raise (`history_engine.py:185`) | ✅ |
| 單列 history | `analyze()` 在 `if not draws` 後加 `if len(draws) < 2: raise ValueError("need >= 2 rows ...")`,杜絕零變異退化(v6.9) | ✅ |
| CSV 只有 header | `loader.from_csv_rows():52` raise | ✅ |
| 全 fallback | `STATIC_FALLBACK_ANALYSIS` 接住,UI 顯示安全模式 + `is_fallback=True` | ✅ |
| 五大濾網篩光所有候選 | 返回空 tickets,UI `st.warning` | ✅ |
| 當期 cron API 失敗 | idx=0 強制 raise(`lotto649_downloader.py:206-211`) | ✅ |
| 重複 draw_term | 兩 scraper `load_existing()` v6.8 加 LOGGER.warning + last-write-wins | ✅ v6.8 |
| CSV 中文編碼破壞日期 | `_canon_date` 回 `""`(v6.3.1 後) | ✅ |
| 威力彩 `special` 超界(歷史) | `_bonus_analyze` raise(v6.3.1) | ✅ |
| pair-disjoint 用 ≥ 2 膽 | picker raise (`lotto_picker.py:319-324`) | ✅ |
| 拖碼池不足 | picker raise (`lotto_picker.py:287-291`) | ✅ |
| oldest-first CSV 進 backtest | `_assert_newest_first` raise(v6.3.1) | ✅ |
| 不存在日期(2/30、13/05) | `_canon_date` 回 `""`(v6.3.1) | ✅ |

---

## §5. 流程層(Process)

- **冪等性**:✅ scraper `download()` append-only by date,重抓無重複(`lotto649_downloader.py:283-322`);引擎以同 seed 必得同結果(`random.Random(seed)`)。
- **可重現性**:`rng = random.Random(seed)` 模式(`lotto_picker.py:220`);`requirements.txt` 用 `>=` 寬鬆 pin(`streamlit>=1.39`、`requests>=2.31`、`urllib3>=2.0`)— v6.9 曾改 `~=` 收緊但 v6.10.1 hotfix revert(`~=1.39.0` 對撞 Streamlit Cloud runtime 預載新版的 transitive 相依鏈)。若未來要再 pin,先在 Cloud 同款 Python 環境跑 `pip install --dry-run` 驗證 transitive 無衝突。歷史運算用倉庫內 CSV 凍結快照(非即時 API)。
- **可觀測性**:Scraper `LOGGER.info` per-month 行數 + diagnostic `fetched_max vs existing_max` 對比(`lotto649_downloader.py:305-308`);workflow 失敗自動開 issue 帶 log tail 50 行(`update-history.yml:77-107`)。Streamlit `@st.cache_data(ttl=3600)` 包載入 + analyze。
- **效能**:**明文禁 pandas 向量化**(舊 `CLAUDE.md §6 依賴限制`);`compression_rate()` 全 14M combos walk = ~30-60s 接受(僅離線 CLI 用,Streamlit 不呼叫)。Streamlit UI 路徑只有 O(N) 載入 + O(N) gap 計算 + O(C(drag, k)) shuffle,實測 < 1s。

---

## §6. AI 自審規範(每寫完一段主動執行,勿等我問)

每完成一段資料處理或計算後,**扮演風控稽核**(不替自己的程式辯護),逐項打勾並
**指出具體在第幾行**或**貼出驗證輸出**。禁止只回「都做了 ✅」。

```
□ SSOT;關鍵數值 provenance 可追溯(source / draw_term / draw_date / Actions log)
□ 無 magic number;常數來自 DEFAULTS / 模組頂 const,並附來源註解
□ 缺值顯式處理且 log;無 fillna(0) / 沉默 ffill / except:pass;
  UI fallback 至 STATIC_FALLBACK_ANALYSIS 必須帶 is_fallback=True + st.warning
□ 邊界已測:空集 / 單筆 / 全 fallback / 重複 draw_term / 中文亂碼日期 / 不存在日期
□ 量綱一致:NT$ 幣別 / *_ratio (0..1) vs *_percent (×100) 命名清楚 / 整數 vs 浮點不混用
□ 無 lookahead:CSV newest-first + backtest._assert_newest_first 不可繞過
□ 開獎日校準:大樂透(二/五) / 威力彩(一/四) / cron 4 槽容錯
□ 浮點比較用 math.isclose,非 ==
□ 關鍵指標(compression / survival / roi)有第二種算法對帳 [v6.5:`compression_rate_monte_carlo` + `reconcile_compression(rel_tol=0.05)`,CLI `--reconcile`]
□ 不變量斷言(每注 6 unique ∈ pool / hot∪warm∪cold = pool / sum_lo ≤ sum_hi / append-only)
□ stdlib-only(src.generator.*);無 pandas / numpy 偷渡;周邊例外只有 streamlit / requests / math
```

最後另外提供:**3 個最容易讓這段程式出錯的輸入**,並寫成測試(本專案用 `unittest`;
property-based 可選 `hypothesis`,golden test 用合成 deterministic seed)。

---

## §7. 每個新功能動工前(先對齊再寫 code)

我交付新功能時,你**動手寫程式前**先回答:

1. 資料來源是哪個 endpoint?CSV 欄位是什麼單位 / 範圍?
2. 這資料有發布延遲嗎(API 30-60 分 / cron 4 槽是否要新增)?需新增 newest-first 排序保證嗎?
3. 邊界條件:空 history / 單列 / 全 fallback / 髒 CSV / 重複 term 怎麼接?
4. 計算式先用**數學式**寫給我確認;若涉及機率 / 濾網,先列 expected compression / survival,再寫程式。

先別寫 code,我們先對齊這四點。

---

## §8. 協作流程附錄(Workflow Governance,沿用自 Protocol v2.0)

資料完整性憲法(§1-§7)管「程式碼寫出來對不對」;本節管「我們怎麼一起工作」。

### 8.1 狀態與記憶管理(State & Memory)
- **冷熱資料分離**:專案根目錄維持極簡 `STATE.md`(當前進度 + 常用指令);深度紀錄(模組依賴、資料流、五階段細節、CI 設計)歸 `ARCHITECTURE.md`。每次任務**僅讀 STATE.md + 目錄結構**理解目標,**嚴禁**要求使用者重複解釋。
- **防幻覺機制**:對話超過 **10 輪**時,修改程式碼**前**必須重新讀取目標檔(不准信任記憶)。
- **主動壓縮**:階段任務完成時,主動提醒執行 `/compact`,保留核心決策、清理無用推理鏈。

### 8.2 精準讀寫與檢索(Precision I/O)
- **大檔案防截斷**:讀取超過 **500 行**的檔案,強制 `offset` + `limit` 分段;搜尋結果超過 **2000 bytes** 必須用 `grep` 二次精確驗證。
- **動工前大掃除**:重構前優先清理 dead code / unused imports,極大化釋放 token 空間。
- **局部編輯**:閉嘴寫扣(No-Yapping)。**嚴禁整檔覆蓋**,僅針對特定函數或行數精準替換(用 `Edit` 而非 `Write`)。

### 8.3 規劃與多線程(Plan & Parallel Execute)
- **嚴格三步法**:`Explore Agent`(唯讀探索) → 提出 **Plan**(3 句話藍圖)與我確認 → 獲准後才 **Execute**(動手改 code)。
- **並行處理**:若任務牽涉超過 **5 個檔案**,主動拆分子任務並行處理,共享 API context cache。

### 8.4 鋼鐵自省與交付(Audit & Delivery)
- **強制驗證機制**:不准說 "Done" 就跑。修改後必須通過 type check / lint / 相關 unit tests;完成後輸出簡短報告 `[邏輯]/[邊界]/[效能]/[Debug]`(覆蓋 §6 自審清單核心點)。
- **環境與效能**:限用 `.py` 腳本(**禁** `.ipynb`),維護 `requirements.txt`;Streamlit 路徑必須正確包 `@st.cache_data(ttl=3600)`。

### 8.5 PR 規範與跳 PR 白名單
- **預設走 PR**:同步存檔 `STATE.md` 與 `ARCHITECTURE.md`、`SPEC.md`(若有架構級變動)。
- **跳 PR 直推主分支白名單**(走 `scripts/quick_merge.sh`):
  1. `STATE.md` / `CLAUDE.md` / 程式註解 / typo 修正
  2. 版本字串 bump(**不含**任何程式邏輯/演算法/介面行為改動)
  3. 不影響功能行為的純文件改動(`README.md`、`ARCHITECTURE.md`、`SPEC.md` 等)

  **其他一律走 PR**,保留 CI gate + 變更紀錄。**任何一行 `.py` 邏輯變動 → 強制 PR**。

### 8.6 卡關救援(Anti-Loop Protocol)
- 同一個報錯**連續重試 2 次未果**,**立即停機**。
- 啟動除錯協議,並交由使用者詢問其他 AI 進行雙重驗證。
