# SPEC — my-lottery-2026 v5.0

> 規格書（Specifications）。冷資料區，與 `ARCHITECTURE.md`（系統藍圖）、`STATE.md`（當前進度）、`CLAUDE.md`（治理協議）三檔協作。
>
> 本檔聚焦「**契約 (Contract)**」：函式輸入 / 輸出 / 不變式 / 例外。不重複藍圖（模組關係去 ARCHITECTURE）、不重複進度（去 STATE）。

---

## 1. 資料格式

### 1.1 歷史 CSV `data/lotto649.csv`

| 欄位 | 型別 | 範例 | 約束 |
|---|---|---|---|
| `draw_term` | str | `"2446"` | 唯一鍵；數字字串 |
| `draw_date` | str | `"2026/5/12"` 或 `"2026-05-12"` | 兩種格式皆相容（loader 只取前 10 字元、不解析） |
| `n1`-`n6` | int | `6, 12, 18, 19, 32, 36` | 1-49、無重複、引擎讀取後排序 |
| `special` | int | `34` | 1-49；引擎**不使用**特別號，僅 UI 預覽顯示 |

排序：CSV 內以 `draw_term` **降序**（最新在頂），但引擎與 loader 不依賴順序。

### 1.2 內部 dataclass

```python
@dataclass(frozen=True)
class Draw:
    draw_term: str
    draw_date: str
    n1: int; n2: int; n3: int; n4: int; n5: int; n6: int
    special: int
```

### 1.3 `HistoryAnalysis`（Phase 1 訊號）

```python
@dataclass(frozen=True)
class HistoryAnalysis:
    hot_numbers: tuple[int, ...]          # gap ≤ max(2, μ-0.5σ)
    cold_numbers: tuple[int, ...]         # gap ≥ μ+1.5σ
    auto_keys: tuple[int, ...]            # 1 熱 + 1 冷（最多）
    dynamic_sum_range: tuple[int, int]    # SMA(10) ± 30, clamp [90, 210]
    overheated_tails: tuple[int, ...]     # 近 3 期 ≥ 4 次的尾數
    dead_tails: tuple[int, ...]           # 近 10 期未出的尾數
    mu: float
    sigma: float
```

---

## 2. 函式契約

### 2.1 `src.data.loader.load_csv_file(source) -> list[tuple[int, ...]]`

**主路徑 / strict**：給引擎吃的歷史資料。

| 參數 | 接受型別 |
|---|---|
| `source` | `Path` / `str`（路徑或原始 CSV 文字） / `bytes` / file-like with `.read()` |

**回傳**：list of 6-tuple（每 tuple 已 sorted、6 顆唯一號碼 1-49）。

**例外**：
- `ValueError`：缺欄、號碼超出值域、重複、行數 < 1。
- `FileNotFoundError`：路徑不存在。

### 2.2 `src.data.loader.preview_recent(source, limit=5) -> list[dict]`

**副路徑 / lenient**：UI 驗證用。**永不 raise**；解析失敗回空 list。

回傳每 dict 含 `term` / `date` / `nums` (list[int]) / `special`（缺欄則為 `"—"`）。

### 2.3 `src.generator.history_engine.analyze(history, hot_floor=None) -> HistoryAnalysis`

**輸入**：`load_csv_file` 的回傳值。
**不變式**：σ 下限 `max(1.0, std)`；`hot_floor` 預設由 UI 滑桿可調，引擎側 `max(2, μ-0.5σ)`。
**例外**：歷史空、或任何 tuple 不是 6 顆 → `ValueError`。

### 2.4 `src.generator.lotto_picker.pick_tickets(...)` ⭐ 核心

```python
def pick_tickets(
    analysis: HistoryAnalysis,
    num_tickets: int,
    seed: int | None = None,
    manual_keys: list[int] | None = None,
    manual_excluded_numbers: list[int] | None = None,
) -> list[tuple[int, ...]]:
```

**Phase 2 - 膽碼決議**：
- `manual_keys` 給定：與 `manual_excluded_numbers` 交集 → `ValueError("keys [...] conflict with manual_excluded_numbers")`
- `manual_keys=None`（動態）：取 `analysis.auto_keys` − `excl_nums`（**silent drop**，無 raise）；全空也 OK，進 no-keys mode

**Phase 3 - shuffle**：`combinations(drag, 6-len(keys))` 後 `random.shuffle`，使用 `Random(seed)` 或 `Random()`。

**Phase 4 Round 1 - 五大濾網**（達 `num_tickets` 即 break）：
| 濾網 | 條件 |
|---|---|
| 質數 | `PRIMES_SET = {2,3,5,7,11,13,17,19,23,29,31,37,41,43,47}`、count ∈ [1, 3] |
| 連號對 | ≤ 2 對 |
| 動態和值 | 落在 `analysis.dynamic_sum_range` 內 |
| 奇數 | count ∈ {2, 3, 4} |
| 大數 (>31) | ≥ 3 顆 |

**Phase 4 Round 2 - Disjoint Fallback (v6)**：
- 觸發條件：R1 結束 `len(results) < num_tickets`
- 規則：新票的 6 顆號碼**完全不與既有票共號**（`used_numbers ∩ combo = ∅`）
- 不含膽碼（用剩下的拖碼 + 排除字段 + R1 已用字段的補集）
- 3 sub-rounds 漸進放寬：
  1. `dynamic_sum_range` + 全五濾網
  2. `[90, 210]` static + 全五濾網
  3. `[6*1, 6*49] = [6, 294]` + 僅基本濾網（無和值約束）
- 若候選 < 6 顆 → 不嘗試、直接回傳手上的 results

**Phase 4 Pair-disjoint Mode (v5.1, 取代 R1+R2)**：
- 啟用條件：`pair_disjoint=True`（UI toggle）
- 規則：跨所有產出 ticket，任 2 顆號碼組成的 pair 出現次數 ≤ `pair_overlap_max + 1`（sub_round 由 0 漸增）
- 約束：`len(key_set) > 1` → `ValueError`（key-pair 強制重複、與本模式互斥）
  - **UI 層 (v5.1.1)**：膽碼留自動時 `auto_keys` 為雙膽（1 熱+1 冷）會撞此約束 → UI 在呼叫前自動保留 1 顆熱膽碼當錨點、`st.info` 提示（manual ≥2 顆仍由 guard 擋下並提示用戶調整）
- 5 大濾網**仍適用**（漸進放寬的只有 pair-overlap、不放寬濾網本身）
- sub-round 0 = 嚴格 pair-disjoint；每多 +1 容忍多 1 個共享 pair
- 候選 ticket 計算 `C(6,2)=15` 個 pair、與 `used_pairs` 取交集大小、超過當前 sub_round 即跳過

**回傳**：tuple of tuple；每 tuple 已 sorted、長度 6、無重複；長度 ≤ `num_tickets`（達不到時不報錯，由 UI 顯示張數差）。

**例外**：
- `manual_keys` 與 `manual_excluded_numbers` 衝突
- `analysis` 為空 / 異常
- `num_tickets < 1`
- `pair_disjoint=True` 且 `len(keys) ≥ 2`
- `pair_overlap_max` 非整數 / 負數

### 2.5 `src.scraper.lotto649_downloader.fetch(periods, session=None) -> list[Draw]`

**直打** `https://api.taiwanlottery.com/TLCAPIWeB/Lottery/Lotto649Result`。

**HTTP 防禦**：
- Session 帶 Mozilla UA + Referer + `Accept: application/json`
- `urllib3.Retry` 自動重試 429/500/502/503/504（3 次、backoff 2.0）
- JSON-decode 外層 retry：3 次（指數 backoff 2/4/8s）、失敗時 log `status / content-type / body preview`

**回傳**：list of `Draw`（`draw_date` 已 canonicalize 至 `YYYY/MM/DD`），fetch 內部用 `draw_term` dedupe，最多 `periods` 筆。每月 fetch 完印 `INFO Month YYYY-MM: API returned N row(s)`。

**例外**：
- **當月 (idx=0) 失敗 → `RuntimeError`**（v3.4 起；阻止「Cloudflare 擋當月、舊月 OK」造成的偽綠燈 stale CSV）
- 舊月 (idx ≥ 1) 失敗只 `LOGGER.warning + continue`
- 總結為空時上層 `download()` 才拋 `RuntimeError`

### 2.6 `src.scraper.lotto649_downloader.download(periods, output) -> int`

**Append-only 合併**。流程：
1. `fetch(periods)` 取得最新 N 期（API shape）
2. `load_existing(output)` 讀既有 CSV（key=`draw_term`，**從不 canonicalize 既有列**）
3. 對既有列構 set of `_canon_date(draw_date)`
4. **印診斷 log**：`fetched=N (max_date=X) | existing=M (max_date=Y)` — 排查 stale-CSV 不再需要本機重跑
5. 對 fetched 每一列：若 canonical date 已在 existing set 中 → 跳過；否則加入 merged dict
6. `save_csv(merged.values(), output)` 寫回（sort by `draw_term` desc）

**設計取捨**：
- 為何 dedup by canonical date：官方 API 改用新期別編碼 `115000053`（舊 `2447`），純 term-keyed dedup 會把同一期當兩列
- 為何不重寫既有 date 格式：原 CSV 部分 `draw_date` 欄位本身錯亂（夾帶 synthetic），統一 canonicalize 反而幹掉合法資料

---

## 3. 不變式 (Invariants)

| ID | 不變式 | 違反處理 |
|---|---|---|
| I-1 | 主號 6 顆、值域 1-49、無重複、sorted | `ValueError` |
| I-2 | 膽碼 1-5 顆（給定時）；自動模式可 0-2 顆 | `ValueError` (manual) / silent drop (auto) |
| I-3 | 拖碼足量湊滿 6 顆 | `ValueError` |
| I-4 | `src.generator.*` 限 stdlib (`random` / `itertools` / `collections` / `statistics`) | grep CI 檢查 |
| I-5 | Streamlit Cloud runtime 不發外部 API | grep CI 檢查（只准 docstring 提到） |
| I-6 | 濾網調整必伴隨 `compression_rate` + `survival_rate` 雙指標審視 | 協定 §3 |
| I-7 | R2 票與 R1 票（含彼此）完全不共號 | `used_numbers` set 強制 |
| I-8 | `unittest discover tests` 全綠 | CI 守門 |

---

## 4. UI 契約（`streamlit_app.py`）

| 元素 | 預設值 | 範圍 / 行為 |
|---|---|---|
| 預覽近 N 期 slider | 5 | 1-20、永不 raise |
| 模式（動態 / 手動） | 動態 | 手動模式顯示膽碼 / 排除輸入欄 |
| 種子（可選） | 空 | 整數；空則 `Random()` |
| 票數 | 5 | 1-50（建議） |
| 載入失敗降級 | — | swap `STATIC_FALLBACK_ANALYSIS` + `st.warning` 不中斷 |

**Cache 規範**：所有「載入」+「分析」函式必須包 `@st.cache_data(ttl=3600)`，UI 重 render 不重算。

---

## 5. CI 契約（`.github/workflows/update-history.yml`）

| 觸發 | cron 4 槽位 `23 14`, `53 14`, `23 15`, `23 16 * * 2,5`（GMT+8 22:23 / 22:53 / 23:23 / 00:23 容錯：避開 :00 整點延遲 + 多跑覆蓋 API 上線延遲）+ `workflow_dispatch` |
|---|---|
| 環境 | ubuntu-latest, python 3.11, pip cache |
| 抓檔 | `python -m src.scraper.lotto649_downloader --periods 50 --verbose 2>&1 \| tee /tmp/scraper.log`（`set -o pipefail` 保留 exit code） |
| Commit 條件 | `git diff --quiet data/lotto649.csv` 失敗（有變動） |
| 推送策略 | **直推 main** (v3.5)：`git pull --rebase origin main && git push origin main`（不再走 PR） |
| Checkout | `actions/checkout@v4` with `ref: main` — 即使 workflow_dispatch 從 feature branch 觸發也強制更新 main |
| 為何能直推 | `github-actions[bot]` 加入 main branch protection 的 bypass list；保留人類 PR 流程不受影響 |
| 失敗通知 | `gh issue create`（`if: failure()`）含 run URL + 排查清單 + **scraper log tail 50 行**（HTTP status / body preview / per-month row count，v3.4 起） |
| 並發 | `concurrency: update-history` 群組互斥；`pull --rebase` 防人類同時 push 衝突 |
| 權限 | YAML：`contents:write` + `issues:write`（v3.5 拿掉 `pull-requests:write`）；**Repo Settings**：Branches → `main` → "Allow specified actors to bypass required pull requests" 加 `github-actions[bot]`（預設無、YAML 無法覆蓋） |

---

## 6. 健康度指標

見 ARCHITECTURE.md §8。本檔僅標示 SLO：

| 指標 | SLO | 異常閾值 |
|---|---|---|
| compression_rate | 5%-30% | < 5% 過嚴；> 50% 形同虛設 |
| survival_rate | ≈ compression_rate | 偏離 ±10pp → 重新檢視 |
| unittest pass rate | 100% | 任一 fail → rollback |
| Phase 6 CI 綠燈率 | ≥ 90% | < 90% → scraper 需強化或換源 |

---

> 規格變動時：先改本檔 → 改 code → 確認測試 → STATE.md 標記 → PR + merge。
