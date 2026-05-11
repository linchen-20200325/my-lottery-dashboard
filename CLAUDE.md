# 核心開發與治理協議 (Core Protocol v2.0)

## §1 狀態與記憶管理 (State & Memory)
- **冷熱資料分離**：專案根目錄必須維持極簡 `STATE.md`。每次任務**僅限讀取此檔與目錄結構**來理解專案目標，嚴禁要求使用者重複解釋。
- **防幻覺機制**：對話超過 10 輪時，修改程式碼前**必須重新讀取目標檔**（不准信任記憶）。
- **主動壓縮**：階段任務完成時，主動提醒我執行 `/compact` 指令，保留核心決策並清理無用推理鏈。

## §2 精準讀寫與檢索 (Precision I/O)
- **大檔案防截斷**：讀取超過 500 行的檔案，強制使用 `offset` 與 `limit` 分段讀取；搜尋結果超過 2000 bytes 時，必須用 `grep` 進行二次精確驗證。
- **動工前大掃除**：重構前優先清理 Dead code 與 Unused imports，極大化釋放 Token 空間。
- **局部編輯**：閉嘴寫扣 (No-Yapping)。嚴禁整檔覆蓋，僅針對特定函數或行數進行精準替換。

## §3 規劃與多線程 (Plan & Parallel Execute)
- **嚴格三步法**：Explore Agent（唯讀探索環境） -> 提出 Plan（3 句話藍圖）與我確認 -> 獲准後才 Execute（動手改 code）。
- **並行處理**：若任務牽涉超過 5 個檔案，主動拆分成子任務並行處理，極致利用 API Context Cache 共享快取。

## §4 鋼鐵自省與交付 (Audit & Delivery)
- **強制驗證機制**：不准說 Done 就跑。修改後必須通過 Type check 與 Lint。完成後輸出簡短報告：[邏輯]、[邊界]、[效能]、[Debug]。
- **環境與效能**：限用 `.py` 腳本（禁 `.ipynb`），維護 `requirements.txt`。必須確保 `st.cache_data` 的正確使用以優化 Streamlit 效能。
- **PR 規範**：使用 `gh pr create` 建立請求，並隨附一鍵 Merge 指令：`gh pr merge <PR號碼> --merge --delete-branch`。嚴禁自動 Merge。

## §5 卡關救援 (Anti-Loop Protocol)
- 針對同一個報錯，若連續重試 2 次未果，**立即停機**。
- 啟動除錯協議，並交由我詢問其他 AI 進行雙重驗證。

## §6 大樂透量化訊號與系統防禦架構 v5.0 (Domain Protocol)
- **系統定位**：訊號驅動 (Signal-Driven) + 容錯架構 (Defensive Architecture) + 效能優先 (Performance First)。承認 EV<0；不預測；以動態訊號 + 五大濾網雙層處理。
- **資料原則 v3.0 §3「果斷棄爬」**：歷史資料來源「**倉庫內附 CSV → UI 上傳 → 離線 scraper 補檔**」三層備援。Streamlit Cloud 端**不發外部 API**。
- **演算法五階段**（順序不可變）：
  1. **Phase 1 — 動態訊號生成**：`history_engine.analyze()` 計算 1-49 各號遺漏期數，求 μ / σ（σ 下限 `max(1.0, std)`），Z-Score 分層：
     - 熱碼：gap ≤ `max(2, μ - 0.5σ)`（floor 由 UI 可調）
     - 冷碼：gap ≥ `μ + 1.5σ`
     - 動態和值：`SMA(近 10 期)` ± 30，clamp 至 `[90, 210]`
     - 過熱尾數：近 3 期 ≥ 4 次；死寂尾數：近 10 期未出
  2. **Phase 2 — Cache + 優雅降級**：
     - 載入 + 分析必須包 `@st.cache_data(ttl=3600)`
     - try/except 接住所有失敗，UI swap 至 `STATIC_FALLBACK_ANALYSIS`（sum 120-180、無冷熱、無排除），`st.warning` 但不中斷
  3. **Phase 3 — Matrix Shuffling**：`rng = random.Random(seed) if seed else random.Random()`；`random.shuffle(list(combinations(drag, 6−len(key))))`
  4. **Phase 4 — 五大濾網**（達 `num_tickets` 即 break）：
     - 質數 `1 ≤ prime_count ≤ 3`（`PRIMES_SET = {2,3,5,7,11,13,17,19,23,29,31,37,41,43,47}`）
     - 連號對數 `≤ 2`
     - 動態和值（Phase 1 區間，或 fallback `120-180`）
     - 奇數數量 `∈ {2,3,4}`
     - 大數 (>31) `≥ 3`
- **回測指標 §3**：`src/analytics/metrics.py` 提供 `compression_rate()`（C(49,6)≈14M 經五大濾網後存活率）與 `survival_rate(csv)`（過去開獎被濾網殺率）；新增/調整濾網時必須兩指標同時審視，避免 over-fitting。
- **依賴限制**：核心引擎 `src.generator.*` 限 `random` + `itertools` + `collections` + `statistics`（禁 `pandas` / `numpy`）；Streamlit、`math.comb`、`taiwanlottery` 為周邊例外。
- **防呆**：歷史非空且每列 6 顆合法號碼、膽碼 1-5 顆、拖碼足量、無重複、值域 1-49；不符即拋 `ValueError`，UI 端必須 `try/except` 接住。
- **自我審核交付**：寫碼後輸出 5 段報告 → 邏輯審查 / 邊界 / 效能 / Debug / 最終代碼。
