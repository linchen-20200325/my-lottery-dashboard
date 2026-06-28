"""DomainConfig — 雙樂透領域常數的單一真實來源 (SSOT)。

CLAUDE.md §2.1 / REFACTOR_AUDIT §5.1。本模組把目前散落在
`history_engine` / `powerball_engine` / `lotto_picker` / `powerball_picker`
四檔、且僅「值不同、結構全同」的領域常數收斂成兩個 frozen dataclass 實例
`LOTTO649` / `POWERBALL`。

設計約束:
  - **frozen + 全 hashable**:所有欄位為 int/float/str/frozenset(無 mutable
    dict 欄位),故 `DomainConfig` 可作 cache key,不破壞 `@st.cache_data` 語義
    (REFACTOR_AUDIT §7 紅線)。
  - **`defaults` property** 回傳與 `*_engine.DEFAULTS` 結構相同的「新」dict,
    供未來 engine 改 import 時零摩擦替換。
  - **策略常數不收**:Howard 8 條、DECADE_BANDS、谷底陷阱僅大樂透適用,屬
    可插拔策略(REFACTOR_AUDIT §5.2「抽共用、留差異」),維持在 `lotto_picker`。
  - **stdlib only**:僅 `dataclasses` + `frozenset`,零第三方依賴。

本檔目前為「宣告式 SSOT」(additive):建立後尚未被消費端 import,值由
`tests/test_domain.py` 對四檔現役常數逐欄對帳鎖定,後續批次(B3/B4)再逐一
把 engine/picker/loader 切換為 import 自本檔。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DomainConfig:
    """單一樂透的全部領域常數(值分歧處的單一真實來源)。"""

    name: str

    # ── 號池 ──────────────────────────────────────────────
    pool_min: int
    pool_max: int
    ticket_size: int
    special_min: int          # 大樂透特別號 ∈ [1,49];威力彩第二區 ∈ [1,8]
    special_max: int
    tails_range_n: int = 10    # 尾數 0-9

    # ── Z-Score / SMA tunables(對應 *_engine.DEFAULTS)──────
    hot_sigma_factor: float = 0.5
    cold_sigma_factor: float = 1.5
    min_std: float = 1.0
    hot_threshold_floor: int = 2
    sum_sma_window: int = 10
    sum_range_pad: int = 30
    sum_clamp_lo: int = 90
    sum_clamp_hi: int = 210
    overheat_recent_periods: int = 3
    overheat_min_count: int = 3
    dormant_periods: int = 8

    # ── 靜態 fallback 和值 ────────────────────────────────
    static_sum_min: int = 120
    static_sum_max: int = 180

    # ── 選號濾網常數(對應 *_picker)──────────────────────
    big_threshold: int = 31
    min_big_count: int = 3
    min_key_nums: int = 1
    max_key_nums: int = 5
    min_prime_count: int = 1
    max_prime_count: int = 3
    max_consecutive_pairs: int = 2
    allowed_odd_counts: frozenset = frozenset({2, 3, 4})
    primes_set: frozenset = frozenset()

    @property
    def defaults(self) -> dict:
        """回傳與 `*_engine.DEFAULTS` 結構相同的新 dict(每次重建,不共享狀態)。"""
        return {
            "hot_sigma_factor": self.hot_sigma_factor,
            "cold_sigma_factor": self.cold_sigma_factor,
            "min_std": self.min_std,
            "hot_threshold_floor": self.hot_threshold_floor,
            "sum_sma_window": self.sum_sma_window,
            "sum_range_pad": self.sum_range_pad,
            "sum_clamp_lo": self.sum_clamp_lo,
            "sum_clamp_hi": self.sum_clamp_hi,
            "overheat_recent_periods": self.overheat_recent_periods,
            "overheat_min_count": self.overheat_min_count,
            "dormant_periods": self.dormant_periods,
        }


# ── 大樂透 6/49 ────────────────────────────────────────────
# 對帳來源:history_engine.{POOL_*,TICKET_SIZE,DEFAULTS,STATIC_SUM_*}、
#           lotto_picker.{BIG_THRESHOLD,PRIMES_SET,...}
LOTTO649 = DomainConfig(
    name="大樂透 6/49",
    pool_min=1,
    pool_max=49,
    ticket_size=6,
    special_min=1,          # 台彩規則:特別號 ∈ [1,49](CLAUDE.md §3.2 #2)
    special_max=49,
    sum_range_pad=30,
    sum_clamp_lo=90,
    sum_clamp_hi=210,
    static_sum_min=120,
    static_sum_max=180,
    big_threshold=31,       # 49 中位
    primes_set=frozenset({2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47}),
)

# ── 威力彩 6/38 + 1/8 ──────────────────────────────────────
# 對帳來源:powerball_engine.{MAIN_POOL_*,BONUS_POOL_*,DEFAULTS,STATIC_SUM_*}、
#           powerball_picker.{BIG_THRESHOLD,PRIMES_SET,...}
POWERBALL = DomainConfig(
    name="威力彩 6/38 + 1/8",
    pool_min=1,
    pool_max=38,
    ticket_size=6,
    special_min=1,          # 第二區 ∈ [1,8]
    special_max=8,
    sum_range_pad=25,       # 池小 → pad 緊一階
    sum_clamp_lo=80,        # 理論最小 21
    sum_clamp_hi=154,       # 理論最大 213
    static_sum_min=90,
    static_sum_max=144,
    big_threshold=19,       # 38 中位
    primes_set=frozenset({2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37}),
)
