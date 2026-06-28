# REFACTOR AUDIT — 第一階段鐵腕重構審查報告 + 排毒藍圖

> 日期:2026-06-28 ｜ 範圍:全專案(35 個 `.py`,8772 行)｜ 方法:5 組鏡像檔案對地毯式比對 + grep 反捏造抽查。
> **本報告為唯讀稽核產物,未改任何 `.py`。** 動工前須經使用者「同意」。
> 所有主張附 `file:line`;關鍵 SSOT 主張已 grep 二次驗證(見 §0)。

---

## §0. 反捏造抽查(已驗,CLAUDE.md §6)

| 主張 | grep 驗證結果 |
|---|---|
| `POOL_*` 在 metrics 重刻 | `metrics.py:49 POOL_MIN, POOL_MAX = 1, 49` ⟂ `history_engine.py:22` 同值 ✅ |
| `TICKET_SIZE=6` 四處 | `loader.py:24` / `loader_powerball.py:19` / `history_engine.py:23` / `powerball_engine.py:24` ✅ |
| v6.4 常數雙刻 | 兩 scraper 各有 `REQUEST_TIMEOUT/HTTP_RETRY_TOTAL/API_PAGE_SIZE/MAX_DRAWS_PER_MONTH/API_BASE` ✅ |
| 大樂透不驗特別號 | `loader.py:47 from_csv_rows → list[list[int]]`(無 special);`_validate_special` 僅 `loader_powerball.py:43` ✅ |

---

## §1. 一句話診斷

**這不是「某幾個檔案爛掉」,而是「整個專案沿著『大樂透 / 威力彩』這條軸線被整層複製貼上」。** 每一層(UI / 引擎 / 選號 / 載入 / 抓檔)都有一對名字不同、本質相同的雙胞胎。膨脹的根因只有一個:**v6.0 導入威力彩時走「獨立模組樹避免泛型化抽象稅」(ARCHITECTURE.md 舊 §10 原話),用 copy-paste 換取當時的開發速度,債滾到今天。**

---

## §2. 重複 / 衝突功能總覽(鏡像檔案對)

| # | 鏡像對 | 行數 | 估 copy-paste | 可收斂行數 | 真正差異(該保留的) |
|---|---|---|---|---|---|
| A | `lotto649_view.py` ⟷ `powerball_view.py` | 939 / 728 | pb ~70-75% 抄自 l649 | ~350-420 | l649:Howard、精簡包牌、Round 分拆、成本面板;pb:第二區 bonus |
| B | `history_engine.py` ⟷ `powerball_engine.py` | 271 / 323 | HE ~80% 進 PE | ~180-200 | pe:`_bonus_analyze` 第二區雙池 |
| C | `lotto_picker.py` ⟷ `powerball_picker.py` | 631 / 420 | pp ~90% 抄自 lp | ~200 | lp:Howard 8 條 130-150 行;pp:`_resolve_bonus` |
| D | `loader.py` ⟷ `loader_powerball.py` | 219 / 223 | pb ~75-80% | ~165 | pb:`_validate_special` + special 串接 |
| E | `lotto649_downloader.py` ⟷ `powerball_downloader.py` | 376 / 332 | pb ~85-90% | ~280 | 僅 API path / 回應欄名 / `_parse_row` schema(<40 行) |

**合計**:四層鏡像約 **1175-1225 行**是純 copy-paste,可被參數化 base 吸收。這是「全域代碼膨脹」的量化體。

### 2.1 逐層證據(精選,完整見各層附錄)

**A — UI 層(最大膨脹源)**
- 頂部 12 個 cached helper(`_load_bundled`/`_freshness_warning`/`_load_upload`/`cached_analysis`…)兩檔幾乎逐字相同,僅 key 前綴 + CSV path + draw-weekday 差(`lotto649_view.py:70-166` ⟂ `powerball_view.py:50-143`)。
- 設定 expander 的「資料來源 → Z-Score → SMA → 尾數訊號 → 膽碼 → 排除」整條 widget 階梯同序同字(`lotto649_view.py:176-514` ⟂ `powerball_view.py:152-484`),~75% 共用。

**B/C — 引擎 + 選號**
- `_tail_counts` / `_dormant_tails` 兩引擎**逐位元組相同**(`history_engine.py:128-141` ≡ `powerball_engine.py:132-145`)。
- `_ensure_int_list` / `_validate_range` / `_validate_unique` 兩 picker **逐位元組相同**(`lotto_picker.py:95-112` ≡ `powerball_picker.py:53-70`)。
- 兩 `DEFAULTS` dict **結構全同、僅 3 個 key 值不同**(`sum_range_pad` 30/25、`sum_clamp_lo` 90/80、`sum_clamp_hi` 210/154)——「該抽 config object」的教科書特徵(`history_engine.py:27-45` ⟂ `powerball_engine.py:30-44`)。
- `PE._gaps`/`_z_layer` **已參數化** `(lo, hi)`,`HE` 仍硬寫 `range(POOL_MIN, POOL_MAX+1)` ——抽象其實零成本,PE 自己已證明(`powerball_engine.py:104,113` ⟂ `history_engine.py:99,111`)。

**D/E — 載入 + 抓檔**
- v6.4 把 8 個常數從 inline 抽成 module const,**卻沒集中**,在兩 scraper 各刻一份(`lotto649_downloader.py:58-69` ⟂ `powerball_downloader.py:45-55`),`DEFAULT_HEADERS` / `Draw` / `_months_back` / `_build_session` / `save_csv` 多為逐位元組相同。
- `_canon_date` 的 `YYYY/MM/DD` 解析在**四處**重複:兩 scraper + `provenance.extract_dates`(`provenance.py:47-65`)+ `freshness.latest_csv_date`(`freshness.py:55-77`)。

---

## §3. 衝突 / 漂移風險(latent bug — 最危險類別)

複製貼上最大的代價不是行數,是**「修了一邊忘了另一邊」**。已找到的不對稱:

| 編號 | 漂移 | 位置 | 風險 |
|---|---|---|---|
| DR-1 | 大樂透 loader **完全不驗特別號**,威力彩有 | `loader.py`(無)⟂ `loader_powerball.py:43-48` | 髒 CSV 帶超界大樂透特別號不會被擋;`_parse_row:194 int(special or 0)` 還會把缺值偽造成 0(§1 Fail Loud 緊張) |
| DR-2 | 膽碼 ∩ 排除 衝突驗證**只有大樂透有** | `lotto649_view.py:720-727`(pb 無) | 威力彩使用者可同時把某號設膽又排除,UI 不擋 |
| DR-3 | `_passes_filters` 共用 5 濾網被埋在大樂透的 Howard/decade/basement 擴充裡 | `lotto_picker.py:189-243` ⟂ `powerball_picker.py:84-109` | 改質數檢查要改兩處,且一處藏在三個 feature 分支中——**四檔最危險的重複** |
| DR-4 | 早載入 except 子句不對稱 | l649 `except (HistoryLoadError, OSError)` ⟂ pb 多一個 `except Exception` | pb 較硬;同源鏡像卻錯誤處理不一致 |
| DR-5 | `cached_analysis` 矛盾捕捉 | `lotto649_view.py:709 except (ValueError, Exception)` | `ValueError` 是 `Exception` 子類,等於 bare catch-all,半成品收窄痕跡 |
| DR-6 | `_preview_json` 特別號欄位漂移 | pb 讀 `special or bonus`(`loader_powerball.py:221`)⟂ l649 只讀 `special`(`loader.py:217`) | 同源 helper 已悄悄分岔 |
| DR-7 | seed=0 時 rng 契約不一 | l649 傳 `None`、pb 傳 `random.Random()` | 兩 picker 對 `None`/fresh Random 行為需一致,否則可重現性漂移 |
| DR-8 | 八常數 + `API_BASE` 無共用 import | 兩 scraper 各刻 | 改一邊 retry 數另一邊 silent 不跟進 |

**目前無「行為矛盾」(複製仍忠實),風險全在未來。** 而 CLAUDE.md 的人工手動鏡像治理模式,正好讓這類漂移高機率發生。

---

## §4. 膨脹與效能低落根因分析

| 根因 | 說明 | 證據 |
|---|---|---|
| R1. **軸線複製(主因)** | 威力彩沒走參數化,整層另開一棵樹 | §2 五對鏡像 |
| R2. **SSOT 破口** | 同一領域常數散在多檔,而非單一 config | `TICKET_SIZE` 4 處、`POOL_*` `metrics.py:49` 重刻、v6.4 常數雙刻、UI 和值邊界 `lotto649_view.py:469`/`powerball_view.py:454` 硬寫 |
| R3. **抽象稅恐懼** | v6.0 刻意選 copy-paste「避免泛型化抽象稅」,但 PE 自己已證明 `_gaps(lo,hi)` 參數化零成本 | `powerball_engine.py:104` |
| R4. **分析層單樂透耦合** | `backtest.py`/`metrics.py` 寫死 6/49,威力彩無分析路徑 | `backtest.py:29,32-37`、`metrics.py:36-50` |
| R5. **一次性腳本未歸檔** | v3.7 migration 腳本仍在工作樹,且重刻 canonical 邏輯 | `import_powerball_history.py`、`sanitize_legacy_dates.py` 自標 "One-shot" |

**效能備註**:本專案多為整數域 O(N) 載入 + O(C(drag,k)) shuffle,UI 路徑實測 < 1s;**「效能低落」主要是維護效能(認知負荷 + 改一處要改多處)而非 runtime 效能。** 唯一 runtime 重算 `compression_rate` 全 14M 列舉僅離線 CLI 用,Streamlit 不呼叫。維護膨脹才是這次要排的毒。

---

## §5. 排毒與收納藍圖(SSOT + 分層)

> 原則:**抽共用、留差異**。共用骨架收進 base,真正的領域差異(第二區、Howard、wheel)維持獨立 plug-in。**covering 數學保證的 `abbreviated_wheel.py` 不動**(刻意不混濾網)。

### 5.1 第一收納:`DomainConfig`(單一真實來源 frozen dataclass)

新增 `src/generator/domain.py`,一個 frozen dataclass 吃下**所有值分歧常數**:

```
pool_min, pool_max          # (1,49) | (1,38)
ticket_size = 6
defaults: dict              # 11-key DEFAULTS(僅 3 key 值不同)
static_sum_min, static_sum_max
big_threshold               # 31 | 19
primes_set: frozenset
special_range               # None | (1,8)
# 以下目前兩邊同值,一併收進來防未來漂移:
allowed_odd_counts, min_big_count, min/max_prime_count,
max_consecutive_pairs, min/max_key_nums
```

實例化 `LOTTO649 = DomainConfig(...)`、`POWERBALL = DomainConfig(...)`。**一舉消滅 R2 全部散落常數**(`TICKET_SIZE` 4 處 → 1、`POOL_*` 重刻 → import、兩 `DEFAULTS` → 兩 config 實例)。

### 5.2 分層收納(OOP / 分層,抽共用留差異)

| 新模組 | 吸收 | 留作 plug-in 的差異 |
|---|---|---|
| `src/generator/base_engine.py` | `_gaps`/`_z_layer`(已參數化)/`_tail_counts`/`_dormant_tails`/`_auto_keys`/`_dynamic_sum_range` + `analyze_main_zone()` | 第二區 `_bonus_analyze` → `PowerballAnalysis(HistoryAnalysis)` 子類或 `BonusZone` mixin |
| `src/generator/base_picker.py` | 3 個逐位元組相同 validator + 基礎 5 濾網 + `_generate_batch_disjoint` 骨架 + `generate_tickets` P1-P4 cascade | Howard → `HowardStrategy` plug-in 注入 `_passes_filters`(DR-3 消失);第二區 → `_resolve_bonus` 後置步驟 |
| `src/data/_loader_base.py` | `_validate_draw`(吃 `main_range`+`error_cls`)/`_validate_special`(`special_range=None` 時跳過)/`from_csv_rows`/`load_*`/4 個 preview helper | 各 loader 縮成 ~10 行 config + re-export shim |
| `src/scraper/_downloader_base.py` | 8 個 v6.4 常數 + `DEFAULT_HEADERS` + `Draw` + `_canon_date` + `_months_back`/`_build_session`/`fetch`/`load_existing`/`_term_sort_key`/`save_csv`/`download`/`main` | 僅 `_parse_row`(schema 欄名)+ config(`api_path`/`response_fields`/`default_periods`)注入 |
| `src/ui/_view_base.py` | 12 個 cached helper factory + 設定 expander 各 section render 函式 + fallback notice + 結果表渲染 | l649:Howard/wheel/Round 分拆/成本面板;pb:第二區 bonus selectbox |

**順手修掉的漂移**(抽共用時自然收斂):DR-1(大樂透補 `special_range=(1,49)`)、DR-2(衝突驗證套用兩邊)、DR-3(濾網單一實作)、DR-4/DR-5(統一 except 政策)、DR-6(`_preview_json` 統一 bonus 別名)、DR-8(常數單一 import)。

### 5.3 SSOT:`_canon_date` 收一處 ✅(B1b 已落地)

兩 scraper 的 `_canon_date`(寬鬆正規化「髒」API 輸入)→ 抽 `src/scraper/_dates.py`
單一 `canon_date()`,兩 scraper 委派之。**`provenance.extract_dates` /
`freshness.latest_csv_date` 刻意不併** —— 它們用 `strptime` 嚴格解析「已標準化」
的 CSV 日期成 `date` 物件,契約不同(要 date、跳過非標準列),強併反而會改行為
(抽共用、留差異;§1 Fail Loud)。故收斂範圍 = 2 份真重複,非原估的 4 份。

### 5.4 歸檔(去 dead weight)

`scripts/import_powerball_history.py`、`scripts/sanitize_legacy_dates.py` 已執行完畢且重刻 canonical 邏輯 → 移 `scripts/archive/`(或加 `# ONE-SHOT, executed v3.7, do not run` header 並從工作樹移出)。

### 5.5 分析層(可選,較大工程)

`backtest.py`/`metrics.py` 接受 `DomainConfig` 參數,讓威力彩也有壓縮率/回測 —— **此項影響演算法行為,屬獨立 PR,不混進純重構**。

### 5.6 OOP 分層收納總表(DataFetcher / CalcEngine / ComponentUI)

把上述 base 模組明確對齊「分層 + 物件導向」三大層,**每個職責一個 owner,拒絕碎片化**。左欄為概念層(類別),中欄為落地模組,右欄為「同一份邏輯目前散在哪 → 收斂後歸誰」:

| 概念層(類別 / 介面) | 落地模組 | 現狀(散落)→ 收斂後(SSOT owner) |
|---|---|---|
| **DomainConfig**(SSOT 核心,frozen dataclass) | `src/generator/domain.py` | `TICKET_SIZE`×4、`POOL_*`(含 `metrics.py:49` 重刻)、兩 `DEFAULTS`、`BIG_THRESHOLD`/`PRIMES_SET`/sum clamp、UI 和值邊界硬寫 → **全部 → `LOTTO649` / `POWERBALL` 兩實例** |
| **DataFetcher**(抽象)→ `Lotto649Fetcher` / `PowerballFetcher` | `src/scraper/_downloader_base.py` + 兩薄 config | 兩 `*_downloader.py` 85-90% copy-paste(8 常數 + `Draw` + `_build_session`…)→ **base 一份,子類僅注入 `api_path`/`response_fields`/`_parse_row`** |
| **HistoryLoader**(抽象,吃 `DomainConfig`) | `src/data/_loader_base.py` + 兩薄 shim | 兩 `loader*.py` 75-80% copy-paste;`_validate_special` 僅威力彩有 → **base 一份,`special_range=None` 時跳過驗證;順手補 DR-1 大樂透特別號** |
| **DateParser / ProvenanceTracker / FreshnessChecker**(已近共用) | `src/data/_dates.py`(新)+ `provenance.py` + `freshness.py` | `_canon_date` 四處重複 → **單一 `canon_date()`** |
| **SignalEngine**(基)→ `MainZoneEngine` + `BonusZone` mixin | `src/generator/base_engine.py` | 兩 `*_engine.py` 80% copy-paste;`_gaps`/`_z_layer` 已參數化 → **base 一份,威力彩 mixin 疊 `_bonus_analyze`** |
| **TicketPicker**(基)+ 策略:`FilterStrategy` / `HowardStrategy` / `DisjointStrategy` | `src/generator/base_picker.py` | 兩 `*_picker.py` 90% copy-paste;5 濾網被埋在 Howard 擴充裡(DR-3)→ **base 跑 5 濾網,Howard/disjoint 作可插拔策略,大樂透才注入 Howard** |
| **WheelGenerator**(獨立,不混濾網) | `src/generator/abbreviated_wheel.py`(**維持原樣**) | covering 數學保證 → **紅線,不進 base** |
| **Analytics**:`CompressionMetric` / `SurvivalMetric` / `Backtester` / `CostCalculator` | `src/analytics/*.py` + `DomainConfig` 參數化(B6) | 目前寫死 6/49 → **吃 config 後雙樂透共用一套** |
| **ComponentUI**:`LotteryView`(基)→ `Lotto649View` / `PowerballView`;子元件 `DataSourceSelector` / `SignalParamsPanel` / `ExclusionPanel` / `ResultTable` / `FallbackNotice` | `src/ui/_view_base.py` + 兩薄 view | 兩 `*_view.py` 70-75% copy-paste(12 helper + 設定階梯)→ **共用元件一份,view 只組裝 + 注入自家差異(Howard/wheel vs 第二區)** |

**讀法**:由上而下即依賴方向 —— `DomainConfig` 被所有層讀;`DataFetcher`/`HistoryLoader` 餵 `SignalEngine` → `TicketPicker` → `ComponentUI` 組裝。每一橫列把「現在散在兩檔的同一份邏輯」收斂到單一 owner,這就是排毒的收納格。

---

## §6. 建議執行順序(低風險 → 高風險,分批 PR)

| 批次 | 內容 | 風險 | 驗證 |
|---|---|---|---|
| **B0** ✅ | 歸檔一次性腳本 + `metrics.py:49` 改 import `POOL_*` | 極低 | unittest 全綠 |
| **B1** ✅ | `DomainConfig` + `_canon_date` 收斂(純抽常數,行為不變) | 低 | 既有測試不改即綠 + 憲法 checker |
| **B2** ✅ | `_downloader_base.py`(差異最少、85-90% 同) | 中 | scraper 測試 + 本機 dry-run |
| **B3** ✅ | `_loader_base.py`(順帶修 DR-1 特別號驗證)+ 診斷常數接 DomainConfig(SSOT) | 中 | loader 測試 + 新增大樂透特別號越界測試 |
| **B4** | `base_engine.py` + `base_picker.py`(留 Howard/bonus plug-in) | 高 | golden seed 回歸:重構前後同 seed 必得同票 |
| **B5** | `_view_base.py`(UI,順帶修 DR-2~DR-7) | 高 | 本機 `streamlit run` 雙 tab 手測 |
| **B6**(可選) | 分析層參數化吃威力彩 | 高(改行為) | 獨立 PR |

**每批守則(CLAUDE.md §8.4)**:重構前後**同 seed golden test 必逐票相同**(這是「純重構不改行為」的鐵證);每批 `python -m unittest discover -s tests` 全綠 + `check_constitution.py` 通過;任何 `.py` 邏輯變動走 PR(§8.5)。

---

## §7. 風險與紅線

- **`abbreviated_wheel.py` 不進任何 base** —— covering 數學保證會被濾網破壞(CLAUDE.md §3.2 #32)。
- **引擎 dataclass 維持純信號**(不灌 provenance,CLAUDE.md §2.2)—— base 須保 frozen-dataclass cache-key 語義。
- **stdlib-only 不可破** —— `DomainConfig` 為純 frozen dataclass,零第三方依賴。
- **不可一次大爆炸重構** —— 依 §6 分批,每批可獨立回滾。

---

> 等待使用者「同意」後,從 B0 開始;每批動工前先回答 CLAUDE.md §7 四問再寫 code。
