"""Dynamic history engine (v5.0 — Phase 1 signal generation).

Produces signals from chronologically ordered historical draws (newest first):
  - Z-Score gap layering (hot / warm / cold)
  - Dynamic sum range from SMA-N ± pad, clamped to safe bounds
  - Bidirectional `exclude_tails` (overheated ∪ dormant)
  - `auto_keys`: 1 hot + 1 cold (dynamic 雙膽)
  - `STATIC_FALLBACK_ANALYSIS` constant for graceful degradation when
    historical data is unavailable (UI failure path).

Stdlib only — `random` + `collections` + `statistics`.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Sequence

from src.generator.base_engine import (
    TAILS_RANGE,
    analyze_main_zone,
    validate_analyze_params,
)

POOL_MIN, POOL_MAX = 1, 49
TICKET_SIZE = 6

# Default tunables — overridable via UI sliders / function args
DEFAULTS = {
    # Z-Score gap layering
    "hot_sigma_factor": 0.5,        # hot threshold = max(2, μ - 0.5σ)
    "cold_sigma_factor": 1.5,       # cold threshold = μ + 1.5σ
    "min_std": 1.0,                 # std floor to prevent /0
    "hot_threshold_floor": 2,       # hot threshold never above this floor
    # Dynamic sum range
    "sum_sma_window": 10,           # last N draws for SMA
    "sum_range_pad": 30,            # ±pad around SMA
    "sum_clamp_lo": 90,             # absolute safety floor
    "sum_clamp_hi": 210,            # absolute safety ceiling
    # Tail signals (v6.10: 放寬 default 讓常見情況也能觸發訊號)
    # - overheat_min_count: 4 → 3(3 期 18 slot 中,單尾數 ≥ 3 = ~17% 集中、適度異常)
    # - dormant_periods:    10 → 8(降低 slot 數讓死寂尾數有機率出現)
    #   舊值 P(任一尾數連 10 期空) ≈ 0.18% → 期望 ≈ 0;新值 8 期 48 slot 提高靈敏度
    "overheat_recent_periods": 3,
    "overheat_min_count": 3,
    "dormant_periods": 8,
}

# Static fallback constants (Phase 2 graceful degradation)
STATIC_SUM_MIN = 120
STATIC_SUM_MAX = 180


@dataclass(frozen=True)
class HistoryAnalysis:
    hot: list[int]
    warm: list[int]
    cold: list[int]
    gaps: dict[int, int]
    gap_mean: float
    gap_std: float
    hot_threshold: float           # dynamic Z-Score derived
    cold_threshold: float
    sum_sma: float                 # SMA of recent sums
    sum_min_dynamic: int           # max(clamp_lo, SMA - pad)
    sum_max_dynamic: int           # min(clamp_hi, SMA + pad)
    tail_counts_recent: dict[int, int]
    overheated_tails: list[int]
    dormant_tails: list[int]
    exclude_tails: list[int]
    auto_keys: list[int]
    is_fallback: bool = False      # True iff produced by graceful degradation


# Fallback singleton — used by Phase 2 when load/analyze raises.
#
# Threshold derivation(對應 CLAUDE.md §3.3 反捏造規則 — 解釋為何是這兩個數):
#   - `hot_threshold=2.0`     = `DEFAULTS["hot_threshold_floor"]`,動態路徑也用同一個 floor,
#                                fallback 直接套常數讓 fallback↔ 動態切換時 hot 定義不會跳動。
#   - `cold_threshold=15.0`   = 「樂透 6/49 每號平均約 8 期出一次,15 期沒出 ≈ μ + 1.5σ
#                                的保守估算」— 對應動態路徑 `μ + cold_sigma_factor * σ` 在
#                                典型樣本下的觀測值;fallback 沒有真歷史時取此常數當 placeholder。
# 兩值都僅在 `is_fallback=True` 時生效,UI 端會 `st.caption("⚠️ 靜態 Fallback")` 提示。
STATIC_FALLBACK_ANALYSIS = HistoryAnalysis(
    hot=[], warm=list(range(POOL_MIN, POOL_MAX + 1)), cold=[],
    gaps={n: 0 for n in range(POOL_MIN, POOL_MAX + 1)},
    gap_mean=0.0, gap_std=0.0,
    hot_threshold=2.0, cold_threshold=15.0,
    sum_sma=float((STATIC_SUM_MIN + STATIC_SUM_MAX) // 2),
    sum_min_dynamic=STATIC_SUM_MIN, sum_max_dynamic=STATIC_SUM_MAX,
    tail_counts_recent={t: 0 for t in TAILS_RANGE},
    overheated_tails=[], dormant_tails=[],
    exclude_tails=[], auto_keys=[],
    is_fallback=True,
)


# --- Public API ---------------------------------------------------------------


def analyze(
    draws: Sequence[Sequence[int]],
    hot_sigma_factor: float = DEFAULTS["hot_sigma_factor"],
    cold_sigma_factor: float = DEFAULTS["cold_sigma_factor"],
    min_std: float = DEFAULTS["min_std"],
    hot_threshold_floor: int = DEFAULTS["hot_threshold_floor"],
    sum_sma_window: int = DEFAULTS["sum_sma_window"],
    sum_range_pad: int = DEFAULTS["sum_range_pad"],
    sum_clamp_lo: int = DEFAULTS["sum_clamp_lo"],
    sum_clamp_hi: int = DEFAULTS["sum_clamp_hi"],
    overheat_recent_periods: int = DEFAULTS["overheat_recent_periods"],
    overheat_min_count: int = DEFAULTS["overheat_min_count"],
    dormant_periods: int = DEFAULTS["dormant_periods"],
    rng: random.Random | None = None,
) -> HistoryAnalysis:
    """Phase 1 dynamic signal generation.

    Raises ValueError on empty draws or invalid thresholds. Callers wanting
    graceful degradation should catch this and substitute STATIC_FALLBACK_ANALYSIS.

    第一區五階段邏輯委派 `base_engine.analyze_main_zone`（SSOT;v6.23 排毒）—
    本函式僅組裝 `HistoryAnalysis` 純信號 dataclass。
    """
    validate_analyze_params(
        draws,
        hot_sigma_factor=hot_sigma_factor,
        cold_sigma_factor=cold_sigma_factor,
        sum_clamp_lo=sum_clamp_lo,
        sum_clamp_hi=sum_clamp_hi,
        sum_range_pad=sum_range_pad,
        overheat_recent_periods=overheat_recent_periods,
        dormant_periods=dormant_periods,
        overheat_min_count=overheat_min_count,
    )
    rng = rng if rng is not None else random.Random()

    mz = analyze_main_zone(
        draws, POOL_MIN, POOL_MAX,
        hot_sigma_factor=hot_sigma_factor,
        cold_sigma_factor=cold_sigma_factor,
        min_std=min_std,
        hot_threshold_floor=hot_threshold_floor,
        sum_sma_window=sum_sma_window,
        sum_range_pad=sum_range_pad,
        sum_clamp_lo=sum_clamp_lo,
        sum_clamp_hi=sum_clamp_hi,
        overheat_recent_periods=overheat_recent_periods,
        overheat_min_count=overheat_min_count,
        dormant_periods=dormant_periods,
        rng=rng,
    )
    return HistoryAnalysis(**mz, is_fallback=False)
