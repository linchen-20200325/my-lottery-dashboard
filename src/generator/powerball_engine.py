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
from collections import Counter
from dataclasses import dataclass
from statistics import mean, pstdev
from typing import Sequence

# 第一區 (主號碼池)
MAIN_POOL_MIN, MAIN_POOL_MAX = 1, 38
TICKET_SIZE = 6
# 第二區 (特別號池)
BONUS_POOL_MIN, BONUS_POOL_MAX = 1, 8
TAILS_RANGE = range(10)

# 預設參數（vs 大樂透：池小 → pad 緊一階、clamp 縮窄）
DEFAULTS = {
    "hot_sigma_factor": 0.5,
    "cold_sigma_factor": 1.5,
    "min_std": 1.0,
    "hot_threshold_floor": 2,
    "sum_sma_window": 10,
    "sum_range_pad": 25,
    "sum_clamp_lo": 80,         # 6 from 1-38 安全下限（理論最小 21）
    "sum_clamp_hi": 154,        # 6 from 1-38 安全上限（理論最大 213）
    "overheat_recent_periods": 3,
    "overheat_min_count": 4,
    "dormant_periods": 10,
}

# 靜態 fallback（Phase 2 容錯）
STATIC_SUM_MIN = 90
STATIC_SUM_MAX = 144


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


# --- Internals ----------------------------------------------------------------


def _gaps(draws: Sequence[Sequence[int]], lo: int, hi: int) -> dict[int, int]:
    """Number → 遺漏期數（newest-first；gap 0 = 最新期出現）。"""
    last_seen: dict[int, int] = {}
    for i, draw in enumerate(draws):
        for n in draw:
            last_seen.setdefault(n, i)
    return {n: last_seen.get(n, len(draws)) for n in range(lo, hi + 1)}


def _z_layer(
    gaps: dict[int, int],
    hot_threshold: float,
    cold_threshold: float,
    lo: int,
    hi: int,
) -> tuple[list[int], list[int], list[int]]:
    hot, warm, cold = [], [], []
    for n in range(lo, hi + 1):
        g = gaps[n]
        if g <= hot_threshold:
            hot.append(n)
        elif g >= cold_threshold:
            cold.append(n)
        else:
            warm.append(n)
    return hot, warm, cold


def _tail_counts(draws: Sequence[Sequence[int]], k: int) -> dict[int, int]:
    counter: Counter[int] = Counter()
    for draw in draws[:k]:
        for n in draw:
            counter[n % 10] += 1
    return {t: counter.get(t, 0) for t in TAILS_RANGE}


def _dormant_tails(draws: Sequence[Sequence[int]], k: int) -> list[int]:
    seen: set[int] = set()
    for draw in draws[:k]:
        for n in draw:
            seen.add(n % 10)
    return sorted(t for t in TAILS_RANGE if t not in seen)


def _auto_keys(
    hot: list[int], cold: list[int], rng: random.Random
) -> list[int]:
    keys: list[int] = []
    if hot:
        keys.append(rng.choice(hot))
    if cold:
        candidates = [n for n in cold if n not in keys]
        if candidates:
            keys.append(rng.choice(candidates))
    if not keys:
        keys = [rng.randint(MAIN_POOL_MIN, MAIN_POOL_MAX)]
    return sorted(keys)


def _dynamic_sum_range(
    draws: Sequence[Sequence[int]],
    window: int,
    pad: int,
    clamp_lo: int,
    clamp_hi: int,
) -> tuple[float, int, int]:
    sums = [sum(d) for d in draws[:window]]
    sma = mean(sums) if sums else float((clamp_lo + clamp_hi) // 2)
    lo = max(clamp_lo, int(round(sma - pad)))
    hi = min(clamp_hi, int(round(sma + pad)))
    return sma, lo, hi


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
    if not draws:
        raise ValueError("history_draws must not be empty")
    if hot_sigma_factor < 0 or cold_sigma_factor < 0:
        raise ValueError("sigma factors must be >= 0")
    if sum_clamp_lo >= sum_clamp_hi:
        raise ValueError("sum_clamp_lo must be < sum_clamp_hi")
    if sum_range_pad < 0:
        raise ValueError("sum_range_pad must be >= 0")
    if overheat_recent_periods < 1 or dormant_periods < 1:
        raise ValueError("recent-period thresholds must be >= 1")
    if overheat_min_count < 1:
        raise ValueError("overheat_min_count must be >= 1")

    rng = rng if rng is not None else random.Random()

    # --- 第一區 ---
    gaps = _gaps(draws, MAIN_POOL_MIN, MAIN_POOL_MAX)
    gap_values = list(gaps.values())
    g_mean = mean(gap_values)
    g_std = max(min_std, pstdev(gap_values))
    hot_threshold = max(float(hot_threshold_floor), g_mean - hot_sigma_factor * g_std)
    cold_threshold = g_mean + cold_sigma_factor * g_std

    hot, warm, cold = _z_layer(
        gaps, hot_threshold, cold_threshold, MAIN_POOL_MIN, MAIN_POOL_MAX,
    )

    sum_sma, sum_lo, sum_hi = _dynamic_sum_range(
        draws, sum_sma_window, sum_range_pad, sum_clamp_lo, sum_clamp_hi,
    )

    tail_counts = _tail_counts(draws, overheat_recent_periods)
    overheated = sorted(
        t for t, c in tail_counts.items() if c >= overheat_min_count
    )
    dormant = _dormant_tails(draws, dormant_periods)
    exclude_tails = sorted(set(overheated) | set(dormant))

    auto_keys = _auto_keys(hot, cold, rng)

    # --- 第二區 ---
    specials_seq: Sequence[int] = specials if specials is not None else []
    bonus_gaps, bonus_hot, bonus_cold, bonus_pick = _bonus_analyze(specials_seq, rng)

    return PowerballAnalysis(
        hot=hot,
        warm=warm,
        cold=cold,
        gaps=gaps,
        gap_mean=g_mean,
        gap_std=g_std,
        hot_threshold=hot_threshold,
        cold_threshold=cold_threshold,
        sum_sma=sum_sma,
        sum_min_dynamic=sum_lo,
        sum_max_dynamic=sum_hi,
        tail_counts_recent=tail_counts,
        overheated_tails=overheated,
        dormant_tails=dormant,
        exclude_tails=exclude_tails,
        auto_keys=auto_keys,
        bonus_gaps=bonus_gaps,
        bonus_hot=bonus_hot,
        bonus_cold=bonus_cold,
        bonus_auto_pick=bonus_pick,
        is_fallback=False,
    )
