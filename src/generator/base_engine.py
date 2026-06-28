"""Shared Phase-1 signal engine core (v6.23 — SSOT base for both lotteries).

抽出大樂透 / 威力彩兩引擎逐位元組相同(或僅 `lo/hi` 池邊界不同)的第一區
訊號邏輯,單一真實來源。兩 `*_engine.py` 各自只留:
  - 領域常數(POOL_*、DEFAULTS、STATIC_SUM_*)
  - 純信號 dataclass(`HistoryAnalysis` / `PowerballAnalysis`,刻意不進 base —
    CLAUDE.md §2.2/§7:維持 frozen-dataclass cache-key 語義 + 純信號)
  - `analyze()` 薄殼:validate → analyze_main_zone → 組裝自家 dataclass
  - 威力彩額外的第二區 `_bonus_analyze`(領域差異,留 powerball_engine)

第一區五階段(Z-Score gap 分層 + SMA 動態和值 + 雙向 exclude_tails + 雙膽
auto_keys)在此**單一實作**,以 `(lo, hi)` 池邊界參數化 —— 威力彩 PE 早已證明
此參數化零成本(`_gaps(draws, lo, hi)`)。

Stdlib only — `random` + `collections` + `statistics`(CLAUDE.md §8.4)。
"""

from __future__ import annotations

import random
from collections import Counter
from statistics import mean, pstdev
from typing import Sequence

# 尾數域 [0,9](兩引擎同值)— 領域常數,§3.2 #6 排除尾數 ∈ [0,9]
TAILS_RANGE = range(10)


# --- Leaf helpers(以池邊界 lo/hi 參數化;池無關者直接共用)---------------------


def _gaps(draws: Sequence[Sequence[int]], lo: int, hi: int) -> dict[int, int]:
    """Number → 遺漏期數(newest-first;gap 0 = 最新期出現)。"""
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
    hot: list[int], cold: list[int], rng: random.Random, lo: int, hi: int
) -> list[int]:
    keys: list[int] = []
    if hot:
        keys.append(rng.choice(hot))
    if cold:
        candidates = [n for n in cold if n not in keys]
        if candidates:
            keys.append(rng.choice(candidates))
    if not keys:
        keys = [rng.randint(lo, hi)]
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
    # Invariant: SMA 落 [clamp_lo, clamp_hi] 外時 lo/hi 會反轉 → collapse 至最近 clamp 端點
    if lo > hi:
        lo = hi = clamp_hi if sma > clamp_hi else clamp_lo
    return sma, lo, hi


# --- Validation(兩引擎逐位元組相同的參數防呆級聯;CLAUDE.md §1 Fail Loud)------


def validate_analyze_params(
    draws: Sequence[Sequence[int]],
    *,
    hot_sigma_factor: float,
    cold_sigma_factor: float,
    sum_clamp_lo: int,
    sum_clamp_hi: int,
    sum_range_pad: int,
    overheat_recent_periods: int,
    dormant_periods: int,
    overheat_min_count: int,
) -> None:
    """Raise ValueError on empty/degenerate draws or invalid thresholds.

    Callers wanting graceful degradation catch this and substitute
    `STATIC_FALLBACK_ANALYSIS`（UI failure path）。
    """
    if not draws:
        raise ValueError("history_draws must not be empty")
    if len(draws) < 2:
        raise ValueError(
            f"history_draws must have >= 2 rows for meaningful Z-score "
            f"(got {len(draws)}; single-row history degenerates to "
            f"all-hot/all-cold with zero variance — UI must fall back to "
            f"STATIC_FALLBACK_ANALYSIS)"
        )
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


# --- Main-zone orchestration(第一區五階段單一實作)----------------------------


def analyze_main_zone(
    draws: Sequence[Sequence[int]],
    lo: int,
    hi: int,
    *,
    hot_sigma_factor: float,
    cold_sigma_factor: float,
    min_std: float,
    hot_threshold_floor: int,
    sum_sma_window: int,
    sum_range_pad: int,
    sum_clamp_lo: int,
    sum_clamp_hi: int,
    overheat_recent_periods: int,
    overheat_min_count: int,
    dormant_periods: int,
    rng: random.Random,
) -> dict:
    """Compute第一區全部訊號,回傳 dict(key 對齊兩 Analysis dataclass 欄位名)。

    參數已由呼叫端 `validate_analyze_params` 驗過;此處只算 + 斷不變量。
    回傳純 dict 而非 dataclass —— 讓各引擎用 `**mz` 灌進自家純信號 dataclass,
    不污染 cache-key 語義(§7)。
    """
    gaps = _gaps(draws, lo, hi)
    gap_values = list(gaps.values())
    g_mean = mean(gap_values)
    g_std = max(min_std, pstdev(gap_values))
    hot_threshold = max(float(hot_threshold_floor), g_mean - hot_sigma_factor * g_std)
    cold_threshold = g_mean + cold_sigma_factor * g_std

    hot, warm, cold = _z_layer(gaps, hot_threshold, cold_threshold, lo, hi)

    sum_sma, sum_lo, sum_hi = _dynamic_sum_range(
        draws, sum_sma_window, sum_range_pad, sum_clamp_lo, sum_clamp_hi,
    )

    tail_counts = _tail_counts(draws, overheat_recent_periods)
    overheated = sorted(
        t for t, c in tail_counts.items() if c >= overheat_min_count
    )
    dormant = _dormant_tails(draws, dormant_periods)
    exclude_tails = sorted(set(overheated) | set(dormant))

    auto_keys = _auto_keys(hot, cold, rng, lo, hi)

    # §4.2 不變量斷言(憲法 §6 自審清單第 10 條)— 第一區三鐵則
    pool = set(range(lo, hi + 1))
    assert set(gaps.keys()) == pool, \
        f"gaps must cover pool [{lo},{hi}], missing={pool - set(gaps.keys())}"
    assert set(hot) | set(warm) | set(cold) == pool, \
        f"hot/warm/cold partition must cover pool [{lo},{hi}]"
    assert sum_lo <= sum_hi, f"sum range inverted: lo={sum_lo} > hi={sum_hi}"

    return dict(
        gaps=gaps,
        gap_mean=g_mean,
        gap_std=g_std,
        hot_threshold=hot_threshold,
        cold_threshold=cold_threshold,
        hot=hot,
        warm=warm,
        cold=cold,
        sum_sma=sum_sma,
        sum_min_dynamic=sum_lo,
        sum_max_dynamic=sum_hi,
        tail_counts_recent=tail_counts,
        overheated_tails=overheated,
        dormant_tails=dormant,
        exclude_tails=exclude_tails,
        auto_keys=auto_keys,
    )
