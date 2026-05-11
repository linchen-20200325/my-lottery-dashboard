"""Dynamic history engine (v3.0 Phase 1).

Consumes a chronologically ordered list of historical draws (newest first)
and produces:
  - hot / warm / cold layering by 遺漏期數 (gap since last appearance)
  - bidirectional `exclude_tails` set: overheated ∪ dormant
  - `auto_keys`: one number sampled from hot ∩ one from cold (dynamic 雙膽)

Stdlib only — `random` + `collections`. No pandas / numpy.
"""

from __future__ import annotations

import random
from collections import Counter
from dataclasses import dataclass
from typing import Sequence

POOL_MIN, POOL_MAX = 1, 49
TICKET_SIZE = 6
TAILS_RANGE = range(10)

# Default thresholds — overridable from caller / UI sliders
DEFAULTS = {
    "hot_max_gap": 2,          # gap ≤ 2 → 熱碼
    "warm_max_gap": 14,        # 2 < gap ≤ 14 → 溫碼; gap > 14 → 冷碼
    "overheat_recent_periods": 3,
    "overheat_min_count": 4,   # 近 3 期該尾出 ≥4 次 → 過熱
    "dormant_periods": 10,     # 連續 10 期該尾未出 → 死寂
}


@dataclass(frozen=True)
class HistoryAnalysis:
    hot: list[int]
    warm: list[int]
    cold: list[int]
    gaps: dict[int, int]              # number → 遺漏期數
    tail_counts_recent: dict[int, int]  # tail → count in `overheat_recent_periods`
    overheated_tails: list[int]
    dormant_tails: list[int]
    exclude_tails: list[int]          # overheated ∪ dormant
    auto_keys: list[int]              # 1 hot + 1 cold (dynamic 雙膽)


def _gaps(draws: Sequence[Sequence[int]]) -> dict[int, int]:
    """Return number → 遺漏期數 (periods since last appearance).

    `draws[0]` is newest. A number appearing in draws[0] has gap 0.
    A number never seen across history gets `len(draws)` (treated as cold).
    """
    last_seen: dict[int, int] = {}
    for i, draw in enumerate(draws):
        for n in draw:
            last_seen.setdefault(n, i)
    out: dict[int, int] = {}
    for n in range(POOL_MIN, POOL_MAX + 1):
        out[n] = last_seen.get(n, len(draws))
    return out


def _layer(
    gaps: dict[int, int], hot_max: int, warm_max: int
) -> tuple[list[int], list[int], list[int]]:
    hot, warm, cold = [], [], []
    for n in range(POOL_MIN, POOL_MAX + 1):
        g = gaps[n]
        if g <= hot_max:
            hot.append(n)
        elif g <= warm_max:
            warm.append(n)
        else:
            cold.append(n)
    return hot, warm, cold


def _tail_counts(draws: Sequence[Sequence[int]], k: int) -> dict[int, int]:
    """Count tail occurrences across the most recent `k` draws."""
    counter: Counter[int] = Counter()
    for draw in draws[:k]:
        for n in draw:
            counter[n % 10] += 1
    return {t: counter.get(t, 0) for t in TAILS_RANGE}


def _dormant_tails(draws: Sequence[Sequence[int]], k: int) -> list[int]:
    """Tails not appearing in the last `k` draws at all."""
    seen: set[int] = set()
    for draw in draws[:k]:
        for n in draw:
            seen.add(n % 10)
    return sorted(t for t in TAILS_RANGE if t not in seen)


def _auto_keys(
    hot: list[int], cold: list[int], rng: random.Random
) -> list[int]:
    """Pick 1 hot + 1 cold as 雙膽. If a layer empty, sample from non-empty."""
    keys: list[int] = []
    if hot:
        keys.append(rng.choice(hot))
    if cold:
        # avoid collision with hot pick (cannot collide by definition, but safe)
        candidates = [n for n in cold if n not in keys]
        if candidates:
            keys.append(rng.choice(candidates))
    if not keys:
        # degenerate: history empty → fall back to any pool number
        keys = [rng.randint(POOL_MIN, POOL_MAX)]
    return sorted(keys)


def analyze(
    draws: Sequence[Sequence[int]],
    hot_max_gap: int = DEFAULTS["hot_max_gap"],
    warm_max_gap: int = DEFAULTS["warm_max_gap"],
    overheat_recent_periods: int = DEFAULTS["overheat_recent_periods"],
    overheat_min_count: int = DEFAULTS["overheat_min_count"],
    dormant_periods: int = DEFAULTS["dormant_periods"],
    rng: random.Random | None = None,
) -> HistoryAnalysis:
    """Run Phase 1 dynamic analysis.

    Raises ValueError if `draws` is empty or thresholds are nonsense.
    """
    if not draws:
        raise ValueError("history_draws must not be empty")
    if hot_max_gap < 0 or warm_max_gap < hot_max_gap:
        raise ValueError("require 0 <= hot_max_gap <= warm_max_gap")
    if overheat_recent_periods < 1 or dormant_periods < 1:
        raise ValueError("threshold periods must be >= 1")
    if overheat_min_count < 1:
        raise ValueError("overheat_min_count must be >= 1")

    rng = rng if rng is not None else random.Random()

    gaps = _gaps(draws)
    hot, warm, cold = _layer(gaps, hot_max_gap, warm_max_gap)

    tail_counts = _tail_counts(draws, overheat_recent_periods)
    overheated = sorted(
        t for t, c in tail_counts.items() if c >= overheat_min_count
    )
    dormant = _dormant_tails(draws, dormant_periods)
    exclude_tails = sorted(set(overheated) | set(dormant))

    auto_keys = _auto_keys(hot, cold, rng)

    return HistoryAnalysis(
        hot=hot,
        warm=warm,
        cold=cold,
        gaps=gaps,
        tail_counts_recent=tail_counts,
        overheated_tails=overheated,
        dormant_tails=dormant,
        exclude_tails=exclude_tails,
        auto_keys=auto_keys,
    )
