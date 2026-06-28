# ARCHITECTURE — my-lottery-2026（逆向地圖 / v6.21 現況快照）

> 系統架構藍圖（冷資料）。配合根目錄 `STATE.md`（熱資料：當前進度）、`CLAUDE.md`（資料完整性憲法）使用。
> **雙樂透**:大樂透 6/49 + 威力彩 6/38 + 1/8。Streamlit 單頁雙 `st.tabs`(非 multipage `pages/`)。
>
> ⚠️ **本檔於 2026-06-28 全面重測校準**:舊版宣稱的 `pages/1_威力彩.py` multipage 結構**已不存在**(實際入口為 `streamlit_app.py` 的 `st.tabs`);舊版模組依賴圖僅畫大樂透單線,未含 UI view 層、provenance、freshness、abbreviated_wheel。本版以實檔逐一核對。

---

## 1. 系統定位

- **訊號驅動 (Signal-Driven)**:以歷史開獎統計(Z-Score 冷熱、SMA 動態和值)驅動候選號池,**非預測**。
- **容錯架構 (Defensive)**:三層(`@st.cache_data` + `STATIC_FALLBACK_ANALYSIS` + `ValueError` 阻擋),任一層失效 UI 仍可用。
- **效能優先 (Performance First)**:`src.generator.*` 僅用 Python 標準庫(`random`/`itertools`/`collections`/`statistics`/`math`)。**禁 pandas / numpy**。
- **誠實前提**:EV<0;本系統優化「組合品質」與「資金分散」,不保證命中。
- **零網路 runtime**:Streamlit Cloud 端**絕不發外部 API**;只讀倉庫內附 CSV / UI 上傳 / 貼上文字(CLAUDE.md §2.1)。

---

## 2. 資料夾結構樹 + 精確職責(逆向地圖核心)

```
my-lottery-dashboard/
├── streamlit_app.py              # 入口:st.tabs 雙分頁 → 各呼叫一個 view.render()
├── src/
│   ├── ui/                       # ── 表現層(Streamlit widget + 容錯渲染)
│   │   ├── lotto649_view.py      #   大樂透分頁(含 Howard 模式 + 精簡包牌,939 行)
│   │   └── powerball_view.py     #   威力彩分頁(含第二區 bonus,728 行)
│   ├── generator/                # ── 訊號 + 選號核心(stdlib-only)
│   │   ├── history_engine.py     #   大樂透訊號:gap → Z-Score 冷熱 + SMA 動態和值
│   │   ├── powerball_engine.py   #   威力彩訊號:主池 + 第二區雙池分析
│   │   ├── lotto_picker.py       #   大樂透選號:五階段管線 + 五濾網 + Howard 8 條
│   │   ├── powerball_picker.py   #   威力彩選號:五階段管線 + 五濾網 + 第二區
│   │   └── abbreviated_wheel.py  #   精簡包牌:L(12,6,4,3) 4保3 greedy set-cover
│   ├── data/                     # ── 載入 + 血緣 + 新鮮度
│   │   ├── loader.py             #   大樂透 CSV/JSON 載入 + 逐列 schema 驗證
│   │   ├── loader_powerball.py   #   威力彩 CSV/JSON 載入(額外驗第二區)
│   │   ├── provenance.py         #   HistoryProvenance dataclass + additive 變體
│   │   └── freshness.py          #   開獎日截止線 + CSV 落後偵測
│   ├── analytics/                # ── 離線分析(主要 CLI;cost_calc 例外可上線)
│   │   ├── cost_calc.py          #   包牌成本 comb(drag, 6-key) × NT$50
│   │   ├── backtest.py           #   歷史命中率回測 + ROI(僅大樂透)
│   │   └── metrics.py            #   compression_rate / survival_rate + Monte Carlo 對帳
│   └── scraper/                  # ── 離線抓檔(僅 GitHub Actions / 本機,Cloud 不跑)
│       ├── lotto649_downloader.py#   直打台彩 Lotto649Result API + retry + 增量合併
│       └── powerball_downloader.py# 直打 SuperLotto638Result API(結構同上)
├── scripts/                      # ── 一次性 / CI 工具
│   ├── check_constitution.py     #   憲法 CI checker(grep pandas/fillna/except:pass)
│   ├── import_powerball_history.py # 【一次性,已執行完畢】v3.7 威力彩史料匯入
│   ├── sanitize_legacy_dates.py  #   【一次性,已執行完畢】v3.7 合成日期清洗
│   └── quick_merge.sh            #   §8.5 跳 PR 白名單直推腳本
├── data/
│   ├── lotto649.csv              # 大樂透歷史(append-only,newest-first)
│   └── powerball.csv             # 威力彩歷史(同上)
├── tests/                        # 18 個 unittest 檔(stdlib unittest)
├── .github/workflows/
│   ├── update-history.yml        # 大樂透 cron(週二/五 4 槽)
│   ├── update-powerball.yml      # 威力彩 cron(週一/四 4 槽)
│   └── constitution-check.yml    # PR gate:跑 check_constitution.py + unittest
├── CLAUDE.md / STATE.md / SPEC.md / ARCHITECTURE.md / requirements.txt
```

**每層精確職責(單一責任邊界)**:

| 層 | 模組 | 職責(做什麼) | 邊界(不做什麼) |
|---|---|---|---|
| 入口 | `streamlit_app.py` | 設定頁面、開兩個 tab、把對應 CSV path 傳給各 view | 不載資料、不分析、不選號(純委派) |
| 表現層 | `src/ui/*_view.py` | widget、session_state(`l649_`/`pb_` 前綴)、cache 包裝、容錯渲染、降級提示 | 不定義演算法常數(應 import) |
| 訊號層 | `src/generator/*_engine.py` | gap 統計 → 冷暖熱分層 + 動態和值 + `STATIC_FALLBACK_ANALYSIS` | 不發網路、不碰 Streamlit |
| 選號層 | `src/generator/*_picker.py` | Phase 3 shuffle + Phase 4 五濾網 + Round 2 disjoint;大樂透另含 Howard | 不載 CSV、不發網路 |
| 包牌 | `src/generator/abbreviated_wheel.py` | 固定 12 號 8 注 4保3 covering(刻意**不過**五濾網) | 不混 Howard/v6.16 濾網 |
| 載入層 | `src/data/loader*.py` | CSV/JSON → `list[list[int]]`,逐欄 raise(Fail Loud) | 不寫回 repo、不發網路 |
| 血緣/新鮮 | `src/data/provenance.py`、`freshness.py` | 來源/抓取時間/歸屬日;開獎截止線落後偵測 | additive,不污染引擎 dataclass |
| 分析層 | `src/analytics/*.py` | 壓縮率/存活率/回測 ROI/成本 | `backtest`/`metrics` 目前**僅大樂透** |
| 抓檔層 | `src/scraper/*_downloader.py` | 官方 API → 增量合併 CSV(離線) | **Cloud runtime 永不呼叫** |

---

## 3. 模組依賴圖(實檔核對)

```
                      streamlit_app.py  (st.tabs)
                       /                       \
        src.ui.lotto649_view        src.ui.powerball_view
          │   │   │   │                 │   │   │   │
          ▼   ▼   ▼   ▼                 ▼   ▼   ▼   ▼
   loader  history  lotto   abbrev   loader_   powerball  powerball
   .py     _engine  _picker _wheel   powerball _engine    _picker
          \________/  │                \________/  │
            (provenance.py / freshness.py 為兩 view 共用旁路)

   src.analytics.{cost_calc, backtest, metrics}  ← 大樂透 CLI(cost_calc 亦可上線)
   src.scraper.{lotto649,powerball}_downloader   ← 離線/Actions,與 live app 解耦
```

**核心依賴限制(CLAUDE.md §8.4)**:`src.generator.*` 僅 stdlib;周邊例外 `streamlit`(UI)、`requests`+`urllib3`(scraper 限定)。

---

## 4. 五階段演算法

| 階段 | 模組 | 動作 | 關鍵參數 |
|---|---|---|---|
| **P1** 動態訊號 | `*_engine.analyze()` | gap → μ/σ → Z-Score 冷暖熱 + 尾數過熱/沉睡 + SMA 動態和值 | 熱 `gap ≤ max(2, μ−0.5σ)`、冷 `gap ≥ μ+1.5σ`、σ 下限 `1.0` |
| **P2** Cache + 降級 | `*_view.py` | `@st.cache_data(ttl=3600)`;載入/分析失敗 swap `STATIC_FALLBACK_ANALYSIS`(`is_fallback=True` + `st.warning`) | 大樂透 sum 120-180、威力彩 90-144 |
| **P3** 矩陣均勻化 | `*_picker._shuffle_pool()` | `random.shuffle(combinations(drag, 6−len(key)))` | `Random(seed)` 可重現 |
| **P4 R1** 五大濾網 | `*_picker._passes_filters()` | 質數∈[1,3]、連號對≤2、動態和值、奇數∈{2,3,4}、大數≥3 | 達 `num_tickets` 即 break |
| **P4 R2** Disjoint fallback | 同檔 | R1 不足時 6 號全域互斥,3 sub-round 漸放寬 | R2 不含膽碼 |
| **Howard(僅大樂透)** | `lotto_picker` | 黃金 8 條(sum 115-185、小數切分、軟分≥3/5…) | R1 套 Howard,R2/R3 退 v6.16 |

---

## 5. 防禦層次

| 層 | 機制 | 觸發點 | 後果 |
|---|---|---|---|
| L1 | `try/except` 包載入+分析 | `*_view.py` | swap `STATIC_FALLBACK_ANALYSIS` + `is_fallback` 旗標 |
| L2 | `@st.cache_data(ttl=3600)` | 載入 + analyze | 1 小時內重算成本 0 |
| L3 | `ValueError` 阻非法輸入 | `loader._validate_*` / `picker.validate` | UI `try/except` 顯紅字不中斷 |

---

## 6. CI 自動化

- `update-history.yml`(大樂透,週二/五 4 槽)、`update-powerball.yml`(威力彩,週一/四 4 槽):cron → 直打 API → 增量合併 → 有變動才 commit+push main → Streamlit Cloud 自動 redeploy;任一 step 失敗自動開 issue 帶 log tail 50 行。
- `constitution-check.yml`:PR gate,跑 `scripts/check_constitution.py`(掃 pandas/numpy/fillna/`except: pass`)+ `unittest discover`。

---

## 7. 不變量(Invariants,實檔已落地)

1. 每注 6 unique ∈ pool(兩 picker return 點 assert)
2. `gaps.keys() == range(pool)`、`hot ∪ warm ∪ cold == pool`、`sum_lo ≤ sum_hi`(analyze 返回前)
3. CSV newest-first(`backtest._assert_newest_first`)
4. append-only(`len(merged) >= len(existing)`,scraper download 返回前)
5. `src.generator.*` 無 pandas/numpy(`check_constitution.py` grep)
6. Cloud runtime 不發網路(`streamlit_app` / `src.data` / `src.generator` 不 import requests)

---

## 8. 雙樂透差異對照

| 項目 | 大樂透 | 威力彩 |
|---|---|---|
| 主號池 | 1-49(6 顆) | 1-38(6 顆) |
| 第二區 | 無(special 僅顯示) | 1-8(1 顆,獨立池) |
| `PRIMES_SET` | 15 顆(≤47) | 12 顆(≤37) |
| `BIG_THRESHOLD` | 31 | 19 |
| 和值 clamp | [90, 210] | [80, 154] |
| 開獎 | 週二/週五 21:30 | 週一/週四 20:00 |
| Cron 槽位(UTC 分) | 23/53/23/23 | 7/37/7/37 |
| 進階模式 | Howard 8 條 + 精簡包牌 | 第二區 bonus(無 Howard/wheel) |
| 分析層(backtest/metrics) | ✅ 支援 | ❌ 目前無路徑 |

---

## 9. 已知架構債(2026-06-28 審查;詳見 `REFACTOR_AUDIT.md`)

> 本節僅標記**現狀事實**,不代表已修。重構藍圖另見 `REFACTOR_AUDIT.md`,動工前須對齊。

- **鏡像雙胞胎膨脹**:`ui` / `generator(engine+picker)` / `data(loader)` / `scraper` 四層各有 `大樂透 / 威力彩` 近重複檔,估約 380-420(generator)+ 165(loader)+ 280(scraper)+ 350(ui)行為 copy-paste。
- **常數散落(SSOT 破口)**:`TICKET_SIZE=6`(4 處)、`POOL_*`(`metrics.py:49` 重刻而非 import)、v6.4 八常數 + `API_BASE`(兩 scraper 各一份)、UI 和值 slider 邊界硬寫。
- **分析層單樂透耦合**:`backtest.py` / `metrics.py` 寫死 6/49,無威力彩路徑。
- **一次性腳本未歸檔**:`import_powerball_history.py` / `sanitize_legacy_dates.py` 已執行完畢且重刻 `_canon_date`/`_term_sort_key`。
- **載入層漂移**:大樂透 loader 不驗特別號(CLAUDE.md §3.2 #2 已知);`_preview_json` bonus 欄位兩 loader 不一致。

---

> 任何架構性變動請同步本檔;不再表達現狀的段落讓它退役(不留陳屍註解)。
