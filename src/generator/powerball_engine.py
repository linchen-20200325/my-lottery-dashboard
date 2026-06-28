"""Taiwan PowerLotto (威力彩) dynamic engine — 雙池訊號 (v6.0).

威力彩規則：
  - 第一區：6 from 1-38
  - 第二區：1 from 1-8（特別號獨立池）

第一區複用大樂透五階段邏輯（Z-Score gap layering + SMA 動態和值 +
雙向 `exclude_tails` + 雙膽 auto_keys），參數重校至 1-38 池。
第二區 1-8 池過小、不切冷/暖/熱三層，只跑單純 gap 排序取 hot pick。

Stdlib only — `random` + `collections` + `statistics`.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from statistics import mean
from typing import Sequence

from src.generator.base_engine import (
    TAILS_RANGE,
    analyze_main_zone,
    validate_analyze_params,
)
from src.generator.domain import POWERBALL as _DOM

# 領域常數單一真實來源 = domain.POWERBALL(v6.24 T1:消除「影子 SSOT」,引擎不再自刻
# 1/38、1/8、DEFAULTS dict、90/144)。名稱維持原樣供既有消費端零摩擦 import,
# 值由 test_domain.py 對帳鎖定。
# 第一區 (主號碼池)
MAIN_POOL_MIN, MAIN_POOL_MAX = _DOM.pool_min, _DOM.pool_max
TICKET_SIZE = _DOM.ticket_size
# 第二區 (特別號池)
BONUS_POOL_MIN, BONUS_POOL_MAX = _DOM.special_min, _DOM.special_max

# 預設參數來自 domain.POWERBALL.defaults(vs 大樂透:池小 → pad 緊一階 25、
# clamp 縮窄 [80,154];sum_clamp_lo 理論最小 21、sum_clamp_hi 理論最大 213;
# tail 訊號 v6.10 放寬同 history_engine.DEFAULTS 段註解)。
DEFAULTS = _DOM.defaults

# 靜態 fallback（Phase 2 容錯）
STATIC_SUM_MIN, STATIC_SUM_MAX = _DOM.static_sum_min, _DOM.static_sum_max


@dataclass(frozen=True)
class PowerballAnalysis:
    # --- 第一區訊號 ---
    hot: list[int]
    warm: list[int]
    cold: list[int]
    gaps: dict[int, int]
    gap_mean: float
    gap_std: float
    hot_threshold: float
    cold_threshold: float
    sum_sma: float
    sum_min_dynamic: int
    sum_max_dynamic: int
    tail_counts_recent: dict[int, int]
    overheated_tails: list[int]
    dormant_tails: list[int]
    exclude_tails: list[int]
    auto_keys: list[int]
    # --- 第二區訊號 ---
    bonus_gaps: dict[int, int]
    bonus_hot: list[int]
    bonus_cold: list[int]
    bonus_auto_pick: int
    is_fallback: bool = False


# Fallback derivation(對應 CLAUDE.md §3.3 反捏造)— 與大樂透 STATIC_FALLBACK_ANALYSIS 同邏輯:
#   - `hot_threshold=2.0`   = `DEFAULTS["hot_threshold_floor"]`,動態↔fallback 切換時 hot 定義恆定
#   - `cold_threshold=15.0` = 威力彩 6/38 每號平均約 6.3 期出一次,15 期沒出 ≈ μ + 1.5σ 保守估算
#                              (vs 大樂透 6/49 的 8 期/次;pool 小所以 cold 門檻其實偏緊,但 fallback
#                               主要靠 sum_min/max + warm 全池就能選出可玩 ticket,cold 是次要訊號)
STATIC_FALLBACK_ANALYSIS = PowerballAnalysis(
    hot=[], warm=list(range(MAIN_POOL_MIN, MAIN_POOL_MAX + 1)), cold=[],
    gaps={n: 0 for n in range(MAIN_POOL_MIN, MAIN_POOL_MAX + 1)},
    gap_mean=0.0, gap_std=0.0,
    hot_threshold=2.0, cold_threshold=15.0,
    sum_sma=float((STATIC_SUM_MIN + STATIC_SUM_MAX) // 2),
    sum_min_dynamic=STATIC_SUM_MIN, sum_max_dynamic=STATIC_SUM_MAX,
    tail_counts_recent={t: 0 for t in TAILS_RANGE},
    overheated_tails=[], dormant_tails=[],
    exclude_tails=[], auto_keys=[],
    bonus_gaps={n: 0 for n in range(BONUS_POOL_MIN, BONUS_POOL_MAX + 1)},
    bonus_hot=list(range(BONUS_POOL_MIN, BONUS_POOL_MAX + 1)),
    bonus_cold=[],
    bonus_auto_pick=BONUS_POOL_MIN,
    is_fallback=True,
)


# --- Internals(威力彩第二區專屬;第一區五階段共用邏輯見 base_engine)-----------


def _bonus_analyze(
    specials: Sequence[int], rng: random.Random
) -> tuple[dict[int, int], list[int], list[int], int]:
    """第二區 1-8 池：gap 排序 + 取低 gap 為 hot、高為 cold、auto pick = 熱號隨機。

    Raises ValueError on any special outside [BONUS_POOL_MIN, BONUS_POOL_MAX]
    (v6.3 — was silently skipped before, which corrupted gap-index alignment).
    """
    n_draws = len(specials)
    gaps: dict[int, int] = {n: n_draws for n in range(BONUS_POOL_MIN, BONUS_POOL_MAX + 1)}
    for i, s in enumerate(specials):
        if isinstance(s, bool) or not isinstance(s, int):
            raise ValueError(f"specials[{i}] must be int (got {s!r})")
        if not (BONUS_POOL_MIN <= s <= BONUS_POOL_MAX):
            raise ValueError(
                f"specials[{i}]={s} out of range "
                f"[{BONUS_POOL_MIN}, {BONUS_POOL_MAX}]"
            )
        if gaps[s] == n_draws:
            gaps[s] = i
    if not specials:
        # 全 fallback：hot = 全 8 顆、auto pick = 1
        return (
            gaps,
            list(range(BONUS_POOL_MIN, BONUS_POOL_MAX + 1)),
            [],
            BONUS_POOL_MIN,
        )
    g_mean = mean(gaps.values())
    hot = sorted(n for n, g in gaps.items() if g <= g_mean)
    cold = sorted(n for n, g in gaps.items() if g > g_mean)
    pick = rng.choice(hot) if hot else rng.randint(BONUS_POOL_MIN, BONUS_POOL_MAX)
    return gaps, hot, cold, pick


# --- Public API ---------------------------------------------------------------


def analyze(
    draws: Sequence[Sequence[int]],
    specials: Sequence[int] | None = None,
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
) -> PowerballAnalysis:
    """威力彩 Phase 1 動態訊號生成。

    Raises ValueError on empty draws or invalid thresholds. Caller should
    catch and substitute STATIC_FALLBACK_ANALYSIS for graceful degradation.
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

    # --- 第一區（五階段委派 base_engine.analyze_main_zone;SSOT v6.23）---
    mz = analyze_main_zone(
        draws, MAIN_POOL_MIN, MAIN_POOL_MAX,
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

    # --- 第二區（威力彩專屬）---
    specials_seq: Sequence[int] = specials if specials is not None else []
    bonus_gaps, bonus_hot, bonus_cold, bonus_pick = _bonus_analyze(specials_seq, rng)

    # §4.2 不變量斷言 — 第二區專屬（第一區三鐵則已在 analyze_main_zone 內斷言）
    _bonus_pool = set(range(BONUS_POOL_MIN, BONUS_POOL_MAX + 1))
    assert set(bonus_gaps.keys()) == _bonus_pool, "bonus gaps must cover [1,8]"
    assert BONUS_POOL_MIN <= bonus_pick <= BONUS_POOL_MAX, \
        f"bonus_pick {bonus_pick} out of [1,8]"

    return PowerballAnalysis(
        **mz,
        bonus_gaps=bonus_gaps,
        bonus_hot=bonus_hot,
        bonus_cold=bonus_cold,
        bonus_auto_pick=bonus_pick,
        is_fallback=False,
    )
