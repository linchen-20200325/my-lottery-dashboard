"""Lotto 6/49 dynamic ticket generator (v5.0).

Pipeline:
    Phase 1  Dynamic signals    : delegate to history_engine.analyze()
                                  (Z-Score gap layering + SMA sum range)
    Phase 2  Pool + 雙膽        : exclude_tails ← analysis (or manual),
                                  key_nums ← auto_keys (or manual)
    Phase 3  Matrix shuffling   : random.shuffle(list(combinations(...)))
    Phase 4  Five filters       : prime ∈ [1,3], consec_pairs ≤ 2,
                                  sum ∈ analysis.sum_min/max_dynamic
                                  (or manual_sum_range), odd ∈ {2,3,4},
                                  big(>31) ≥ 3

Stdlib only: `random` + `itertools` (+ `collections`/`statistics` via engine).
"""

from __future__ import annotations

import random
from itertools import combinations
from typing import Iterable, Sequence

from src.generator.history_engine import (
    DEFAULTS,
    HistoryAnalysis,
    POOL_MAX,
    POOL_MIN,
    STATIC_SUM_MAX,
    STATIC_SUM_MIN,
    TICKET_SIZE,
    analyze,
)

# Static fallback sum range (used when history unavailable; v5.0 §2)
SUM_MIN, SUM_MAX = STATIC_SUM_MIN, STATIC_SUM_MAX
ALLOWED_ODD_COUNTS: frozenset = frozenset({2, 3, 4})
BIG_THRESHOLD = 31
MIN_BIG_COUNT = 3
MAX_KEY_NUMS = 5
MIN_KEY_NUMS = 1

PRIMES_SET: frozenset = frozenset(
    {2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47}
)
MIN_PRIME_COUNT = 1
MAX_PRIME_COUNT = 3
MAX_CONSECUTIVE_PAIRS = 2


# --- Validation helpers -------------------------------------------------------


def _ensure_int_list(name: str, values: Iterable[int]) -> list[int]:
    out: list[int] = []
    for v in values:
        if isinstance(v, bool) or not isinstance(v, int):
            raise ValueError(f"{name} must contain integers only (got {v!r})")
        out.append(v)
    return out


def _validate_range(name: str, values: list[int], lo: int, hi: int) -> None:
    for v in values:
        if not (lo <= v <= hi):
            raise ValueError(f"{name} value {v} out of range [{lo}, {hi}]")


def _validate_unique(name: str, values: list[int]) -> None:
    if len(set(values)) != len(values):
        raise ValueError(f"{name} must not contain duplicates")


def _validate_history(draws: Sequence[Sequence[int]]) -> None:
    if not draws:
        raise ValueError("history_draws must not be empty")
    for i, d in enumerate(draws):
        if len(d) != TICKET_SIZE:
            raise ValueError(f"history_draws[{i}] must have 6 numbers")
        ints = _ensure_int_list(f"history_draws[{i}]", d)
        _validate_range(f"history_draws[{i}]", ints, POOL_MIN, POOL_MAX)
        _validate_unique(f"history_draws[{i}]", ints)


# --- Core algorithm -----------------------------------------------------------


def generate_tickets(
    history_draws: Sequence[Sequence[int]],
    num_tickets: int = 5,
    *,
    # Z-Score gap layering (v5.0)
    hot_sigma_factor: float = DEFAULTS["hot_sigma_factor"],
    cold_sigma_factor: float = DEFAULTS["cold_sigma_factor"],
    # Dynamic sum range (v5.0)
    sum_sma_window: int = DEFAULTS["sum_sma_window"],
    sum_range_pad: int = DEFAULTS["sum_range_pad"],
    # Tail signals
    overheat_recent_periods: int = DEFAULTS["overheat_recent_periods"],
    overheat_min_count: int = DEFAULTS["overheat_min_count"],
    dormant_periods: int = DEFAULTS["dormant_periods"],
    # Manual overrides (UI fallback per §3)
    manual_keys: Iterable[int] | None = None,
    manual_excluded_tails: Iterable[int] | None = None,
    manual_sum_range: tuple[int, int] | None = None,
    # Pre-computed analysis (UI passes a cached analysis to avoid re-running)
    precomputed_analysis: HistoryAnalysis | None = None,
    rng: random.Random | None = None,
) -> tuple[list[tuple[int, ...]], HistoryAnalysis]:
    """Produce up to `num_tickets` filtered combinations + analysis snapshot.

    Manual overrides — when provided — supersede dynamic signals; this is the
    surface that v5.0 §2 graceful-degradation path uses (UI substitutes
    STATIC_FALLBACK_ANALYSIS via `precomputed_analysis`).

    Raises ValueError on invalid input or unsatisfiable configuration.
    """
    _validate_history(history_draws)

    if not isinstance(num_tickets, int) or isinstance(num_tickets, bool):
        raise ValueError("num_tickets must be an integer")
    if num_tickets < 1:
        raise ValueError("num_tickets must be >= 1")

    rng = rng if rng is not None else random.Random()

    # --- Phase 1: dynamic signals ---
    if precomputed_analysis is not None:
        analysis = precomputed_analysis
    else:
        analysis = analyze(
            draws=history_draws,
            hot_sigma_factor=hot_sigma_factor,
            cold_sigma_factor=cold_sigma_factor,
            sum_sma_window=sum_sma_window,
            sum_range_pad=sum_range_pad,
            overheat_recent_periods=overheat_recent_periods,
            overheat_min_count=overheat_min_count,
            dormant_periods=dormant_periods,
            rng=rng,
        )

    # --- Phase 2: pool + dynamic 雙膽 ---
    if manual_excluded_tails is not None:
        excl = _ensure_int_list("manual_excluded_tails", manual_excluded_tails)
        _validate_range("manual_excluded_tails", excl, 0, 9)
        _validate_unique("manual_excluded_tails", excl)
        tail_set = set(excl)
    else:
        tail_set = set(analysis.exclude_tails)

    pool: set[int] = {
        n for n in range(POOL_MIN, POOL_MAX + 1) if (n % 10) not in tail_set
    }

    if manual_keys is not None:
        keys = _ensure_int_list("manual_keys", manual_keys)
        _validate_range("manual_keys", keys, POOL_MIN, POOL_MAX)
        _validate_unique("manual_keys", keys)
        if not (MIN_KEY_NUMS <= len(keys) <= MAX_KEY_NUMS):
            raise ValueError(
                f"manual_keys must contain {MIN_KEY_NUMS}-{MAX_KEY_NUMS} numbers"
            )
    else:
        keys = list(analysis.auto_keys)
        if not (MIN_KEY_NUMS <= len(keys) <= MAX_KEY_NUMS):
            raise ValueError(
                f"auto_keys yielded {len(keys)}; widen thresholds or pass manual_keys"
            )

    key_set = set(keys)
    drag_candidates = pool - key_set
    needed = TICKET_SIZE - len(keys)
    if len(drag_candidates) < needed:
        raise ValueError(
            f"insufficient drag candidates: need {needed}, "
            f"available {len(drag_candidates)} (after excluding tails {sorted(tail_set)})"
        )

    # --- Phase 3: matrix shuffling ---
    drag_sorted = sorted(drag_candidates)
    all_combos = list(combinations(drag_sorted, needed))
    rng.shuffle(all_combos)

    # --- Phase 4: five filters ---
    if manual_sum_range is not None:
        s_lo, s_hi = manual_sum_range
        if not (isinstance(s_lo, int) and isinstance(s_hi, int)):
            raise ValueError("manual_sum_range must be (int, int)")
        if s_lo > s_hi:
            raise ValueError("manual_sum_range lo must be <= hi")
    else:
        s_lo, s_hi = analysis.sum_min_dynamic, analysis.sum_max_dynamic

    results: list[tuple[int, ...]] = []
    for combo in all_combos:
        ticket = tuple(sorted(key_set.union(combo)))
        if not (s_lo <= sum(ticket) <= s_hi):
            continue
        odd_count = sum(1 for n in ticket if n % 2 == 1)
        if odd_count not in ALLOWED_ODD_COUNTS:
            continue
        if sum(1 for n in ticket if n > BIG_THRESHOLD) < MIN_BIG_COUNT:
            continue
        prime_count = sum(1 for n in ticket if n in PRIMES_SET)
        if not (MIN_PRIME_COUNT <= prime_count <= MAX_PRIME_COUNT):
            continue
        consecutive_pairs = sum(
            1 for i in range(TICKET_SIZE - 1) if ticket[i + 1] - ticket[i] == 1
        )
        if consecutive_pairs > MAX_CONSECUTIVE_PAIRS:
            continue
        results.append(ticket)
        if len(results) >= num_tickets:
            break

    return results, analysis


# --- Helpers ------------------------------------------------------------------


def ticket_stats(ticket: Iterable[int]) -> dict[str, int]:
    """Per-ticket diagnostics (sum, odd/even, big/small, prime, consecutive)."""
    t = sorted(ticket)
    return {
        "sum": sum(t),
        "odd_count": sum(1 for n in t if n % 2 == 1),
        "even_count": sum(1 for n in t if n % 2 == 0),
        "big_count": sum(1 for n in t if n > BIG_THRESHOLD),
        "small_count": sum(1 for n in t if n <= BIG_THRESHOLD),
        "prime_count": sum(1 for n in t if n in PRIMES_SET),
        "consecutive_pairs": sum(
            1 for i in range(len(t) - 1) if t[i + 1] - t[i] == 1
        ),
    }
