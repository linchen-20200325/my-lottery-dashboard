# ARCHITECTURE — my-lottery-2026 v5.0

> 系統架構藍圖。冷資料區，配合根目錄 `STATE.md`（熱資料：當前進度）、`CLAUDE.md`（治理協議）使用。

---

## 1. 系統定位
- **訊號驅動 (Signal-Driven)**：以歷史開獎統計（Z-Score、SMA）驅動候選號池，非預測。
- **容錯架構 (Defensive)**：三層防護（cache + fallback + ValueError），任一層失效 UI 仍可用。
- **效能優先 (Performance First)**：核心引擎僅用 Python 標準庫；`@st.cache_data(ttl=3600)` 摺疊重算。
- **誠實前提**：EV<0；本系統優化的是「組合品質」與「資金分散」，不保證命中。

---

## 2. 模組依賴圖

```
┌─────────────────────────────────────────────────────────────┐
│                     streamlit_app.py                        │   UI 層
│            (Streamlit Cloud entry point)                    │   (cache + fallback)
└──────────┬───────────────────────────┬──────────────────────┘
           │                           │
           ▼                           ▼
┌──────────────────────┐    ┌──────────────────────┐
│  src.data.loader     │    │  src.analytics.*     │   分析層
│  (CSV / JSON / 上傳)  │    │  cost_calc /         │   (cost / backtest /
└──────────┬───────────┘    │  backtest / metrics  │    metrics)
           │                └──────────────────────┘
           │
           ▼
┌──────────────────────────────────┐
│  src.generator.history_engine    │   訊號層
│  (Z-Score 冷熱 / SMA 動態和值 /   │   (Phase 1)
│   STATIC_FALLBACK_ANALYSIS)      │
└──────────┬───────────────────────┘
           │
           ▼
┌──────────────────────────────────┐
│  src.generator.lotto_picker      │   選號核心
│  (Phase 3 shuffle + Phase 4 五濾網)│   (Phase 3-4)
└──────────────────────────────────┘

(離線輔助，與 live app 解耦)
┌──────────────────────────────────┐
│  src.scraper.lotto649_downloader │   抓檔層 v3.1
│  (直打官方 API + UA + retry +     │   (本機 / GitHub Actions)
│   增量合併)                        │
└──────────────────────────────────┘
```

**核心依賴限制（協定 §6）**：`src.generator.*` 只准用 `random` + `itertools` + `collections` + `statistics`。禁止 `pandas` / `numpy`。Streamlit、`math.comb`、`requests`（scraper 限定）為周邊例外。

---

## 3. 資料流

```
[資料來源三層備援 §3「果斷棄爬」]
  ① 倉庫內附 CSV (data/lotto649.csv)         ← 主路徑
  ② Streamlit UI 手動上傳                     ← 備援 1
  ③ 離線 scraper 補檔 (taiwanlottery)         ← 備援 2 (本機 or Actions)
                    │
                    ▼
        src.data.loader.load_csv_file()      ← 引擎主路徑 (strict, raises on bad input)
        (extract n1-n6, 忽略日期/特別號)
                    │
                    ├──→ src.data.loader.preview_recent()  ← UI 驗證副路徑 (lenient, never raises)
                    │     (含 term/date/special, 主面板頂部展示近 N 期)
                    ▼
        src.generator.history_engine.analyze()
        (1-49 各號遺漏期數 → μ, σ → 冷熱分層)
                    │
                    ▼
        src.generator.lotto_picker.pick_tickets()
        (Phase 3 shuffle → Phase 4 filter cascade)
                    │
                    ▼
              UI 渲染選號結果
```

**Live app 鐵律**：Streamlit Cloud 端**不發外部 API**。資料只進不出。

---

## 4. 五階段演算法 (Algorithm v5.0)

| 階段 | 模組 | 動作 | 關鍵參數 |
|---|---|---|---|
| **Phase 1** 動態訊號 | `history_engine.analyze()` | 計算 1-49 遺漏期數 → μ/σ → Z-Score 分層 | 熱碼 `gap ≤ max(2, μ−0.5σ)`；冷碼 `gap ≥ μ+1.5σ`；σ 下限 `max(1.0, std)` |
| **Phase 2** Cache + 降級 | `streamlit_app.py` | `@st.cache_data(ttl=3600)` 包載入；失敗 swap `STATIC_FALLBACK_ANALYSIS` | Fallback：sum 120-180、無冷熱、無排除 |
| **Phase 3** 矩陣均勻化 | `lotto_picker._shuffle_pool()` | `random.shuffle(combinations(drag, 6−len(key)))` | 種子可選 (`Random(seed)`) |
| **Phase 4 Round 1** 五大濾網 | `lotto_picker._passes_filters()` | 達 `num_tickets` 即 break | 質數 ∈ [1,3]、連號對 ≤ 2、動態和值 (Phase 1)、奇數 ∈ {2,3,4}、大數(>31)≥3 |
| **Phase 4 Round 2** Disjoint Fallback (v6) | `lotto_picker` 同檔 | 僅當 R1 < `num_tickets` 觸發 | 每張新票 6 顆主號**完全不與既有票共號** (`used_numbers ∩ combo = ∅`)；3 sub-rounds 漸進放寬 (動態和值 → static 90-210 → 完全跳和值)；R2 票不含膽碼 |

**自動膽碼衝突處理 (v6)**：`manual_keys=None` (動態模式) 時若 `analysis.auto_keys` 與 `manual_excluded_numbers` 衝突 → **silent drop** 衝突膽碼，不 raise；keys 被掏空則進入 no-膽碼 mode。手動 `manual_keys` 衝突仍 raise（用戶明確衝突）。

**和值動態化**：Phase 1 算出 `SMA(近 10 期) ± 30` clamp `[90, 210]`；資料缺失時 fallback `[120, 180]`。

**質數白名單**：`PRIMES_SET = {2,3,5,7,11,13,17,19,23,29,31,37,41,43,47}`

---

## 5. 防禦層次

| 層 | 機制 | 觸發點 | 後果 |
|---|---|---|---|
| L1 | `try/except` 包載入+分析 | `streamlit_app.py` `load_history()` / `analyze()` | swap to `STATIC_FALLBACK_ANALYSIS` |
| L2 | `@st.cache_data(ttl=3600)` | 載入 + 分析函數 | 1 小時內重算成本為 0 |
| L3 | `ValueError` 阻擋非法輸入 | `lotto_picker.validate()` | 膽碼 1-5、值域 1-49、無重複；UI 端 `try/except` 顯示紅字不中斷 |

---

## 6. CI 自動化 (Phase 6)

**檔案**：`.github/workflows/update-history.yml`

```
GitHub Actions cron '0 14 * * 2,5'  (週二/週五 22:00 GMT+8, 開獎當晚)
                  │
                  ▼
      checkout → setup-python 3.11 → pip install requirements.txt
                  │
                  ▼
      python -m src.scraper.lotto649_downloader --periods 50 --verbose 2>&1 | tee /tmp/scraper.log
       (v3.1: 直打 api.taiwanlottery.com + UA + Retry(429/5xx) + JSON-decode 外層 retry 3 次)
       (v3.4: 當月 fetch 失敗 raise → 杜絕「Cloudflare 擋當月、舊月 OK」偽綠燈)
       (v3.4: per-month INFO log + download() 印 fetched_max/existing_max/added 診斷)
       (失敗 → RuntimeError + 診斷 log → CSV 不變、step exit 1、tee 的 log 進 issue body)
                  │
                  ▼
      git diff --quiet data/lotto649.csv?
       │ 無變動：跳過 PR
       │ 有變動：建分支 auto/data-update-{ts} → push → gh pr create
                              │
                              ▼
       gh pr merge --squash --auto --delete-branch  (v3.2)
        │ 成功：squash 進 main → Streamlit Cloud 自動 redeploy
        │ 失敗：fallback 為直接 merge；再失敗則留 PR 待手動 review
                  │
                  ▼ (任一 step 失敗)
      gh issue create --title "[auto-update] 樂透歷史更新失敗 YYYY-MM-DD"
       (含 run URL + scraper vs PR 兩階段排查清單 + scraper log tail 50 行)
```

**設計取捨**：
- **PR 流程 (v3.2)**：main 受 branch protection 保護禁直推；改建短命分支 + auto-merge 繞過。失敗時保留 PR 提供 audit trail。
- **`workflow_dispatch`**：保留手動觸發以支援 dry run 與緊急補檔。
- **`concurrency: update-history`**：cron + manual 重疊時不 race。
- **權限**：`contents:write + issues:write + pull-requests:write`（PR 流程需要）。

---

## 7. 護欄與不變式 (Invariants)

1. **歷史資料**非空且每列 6 顆合法號碼（值域 1-49、無重複）→ 否則 `ValueError`
2. **膽碼** 1-5 顆 + 拖碼足量湊滿 6 顆 → 否則 `ValueError`
3. **核心引擎不引入 pandas/numpy**（檢查方式：`grep -n "import pandas\|import numpy" src/generator/`）
4. **Streamlit Cloud runtime 不發外部 API**（檢查方式：`grep -n "requests\|urllib\|httpx" streamlit_app.py src/data/ src/generator/ src/analytics/` 應只命中 docstring）
5. **濾網調整**必伴隨 `compression_rate` + `survival_rate` 雙指標審視（協定 §3）
6. **新增/修改演算法**必跑 `python -m unittest discover tests` 全綠

---

## 8. 監控與健康度

| 指標 | 計算來源 | 健康範圍 | 異常處理 |
|---|---|---|---|
| compression_rate | `src/analytics/metrics.py` | 5%-30%（依資料量浮動） | < 5% 過嚴；> 50% 濾網形同虛設 |
| survival_rate | `src/analytics/metrics.py` | 接近 compression_rate | 顯著低於 compression → 反 over-fit；顯著高於 → 可能 over-fit |
| unittest pass | `python -m unittest discover tests` | 100%（57 tests） | 任一 fail：rollback |
| Phase 6 CI 綠燈率 | GitHub Actions UI | ≥ 90% | < 90%：scraper 套件需換或加 retry |

**最近一次（2026-05-12）**：compression 14.99% / survival 14.86%（中性壓縮器、無 over-fit）。

---

## 9. 變動指引

- **加新濾網**：改 `lotto_picker._passes_filters()` → 跑 metrics → 雙指標都不爆 → unittest → 文件同步 §4 表
- **改抓檔來源**：改 `src/scraper/lotto649_downloader.py` → 本機驗證 → 若 GitHub Actions runner 行為不同，調 workflow YAML 或加 retry
- **UI 改版**：改 `streamlit_app.py` → 本機 `streamlit run` → 確認 fallback 路徑仍在
- **新階段任務**：寫進 `STATE.md` 後續規劃；本檔僅在「架構」改變時動

---

> 任何架構性變動，請同步本檔；不再表達現狀就讓它退役（不要留陳屍註解）。
