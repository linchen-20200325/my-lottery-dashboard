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

import math
import random
from collections import Counter
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


def _passes_filters(
    ticket: tuple[int, ...],
    s_lo: int,
    s_hi: int,
    *,
    apply_secondary: bool,
) -> bool:
    """Apply the v5.0 §6 五大濾網. `apply_secondary=False` ⇒ sum-only (Round 3 fallback)."""
    if not (s_lo <= sum(ticket) <= s_hi):
        return False
    if not apply_secondary:
        return True
    odd_count = sum(1 for n in ticket if n % 2 == 1)
    if odd_count not in ALLOWED_ODD_COUNTS:
        return False
    if sum(1 for n in ticket if n > BIG_THRESHOLD) < MIN_BIG_COUNT:
        return False
    prime_count = sum(1 for n in ticket if n in PRIMES_SET)
    if not (MIN_PRIME_COUNT <= prime_count <= MAX_PRIME_COUNT):
        return False
    consecutive_pairs = sum(
        1 for i in range(TICKET_SIZE - 1) if ticket[i + 1] - ticket[i] == 1
    )
    if consecutive_pairs > MAX_CONSECUTIVE_PAIRS:
        return False
    return True


def _generate_batch_disjoint(
    *,
    pool: set[int],
    key_set: set[int],
    s_lo: int,
    s_hi: int,
    num_tickets: int,
    rng: random.Random,
) -> list[tuple[int, ...]]:
    """批次覆蓋模式(v6.15):嚴格 pair-disjoint + 均衡硬上限。

    v6.13:任意 2 顆配對在所有注中至多出現一次。
    v6.15:在 v6.13 基礎上加「每號出現次數 ≤ ⌈6N/P⌉ + 1」的均衡硬上限
            (P = 有效池大小;+1 為使用者明示允許的容差);防止 pair-disjoint
            雖然不重複但某號 0 次、某號 5 次的高方差分佈。

    理論上限 = ⌊C(pool, 2) / C(6, 2)⌋(扣濾網實際更少)。

    三相 filter 漸進降級,每相內嚴格 pair-disjoint + 均衡 cap:
    - sub-A: dynamic sum (s_lo, s_hi) + full 5 filters
    - sub-B: static [SUM_MIN, SUM_MAX] + full 5 filters
    - sub-C: 無 sum 邊界 + 無次要濾網

    湊不到 num_tickets 直接 return,呼叫端負責 warn。
    """
    results: list[tuple[int, ...]] = []
    seen: set[tuple[int, ...]] = set()
    used_pairs: set[tuple[int, int]] = set()
    usage: Counter[int] = Counter()
    # v6.15 均衡硬上限:每號出現 ≤ ⌈6N/P⌉ + 1(容差 1)
    max_per_number = math.ceil(TICKET_SIZE * num_tickets / len(pool)) + 1

    drag_candidates = pool - key_set
    needed = TICKET_SIZE - len(key_set)
    if len(drag_candidates) < needed:
        return results  # caller already validated drag pool size; defensive
    all_combos = list(combinations(sorted(drag_candidates), needed))
    rng.shuffle(all_combos)

    sub_rounds = (
        ((s_lo, s_hi), True),
        ((SUM_MIN, SUM_MAX), True),
        ((TICKET_SIZE * POOL_MIN, TICKET_SIZE * POOL_MAX), False),
    )
    for (sub_lo, sub_hi), apply_full in sub_rounds:
        if len(results) >= num_tickets:
            break
        for combo in all_combos:
            if len(results) >= num_tickets:
                break
            ticket = tuple(sorted(key_set.union(combo)))
            if ticket in seen:
                continue
            if any(usage[n] >= max_per_number for n in ticket):
                continue  # v6.15 均衡硬上限
            if not _passes_filters(ticket, sub_lo, sub_hi, apply_secondary=apply_full):
                continue
            new_pairs = set(combinations(ticket, 2))
            if new_pairs & used_pairs:  # 嚴格 pair-disjoint: 任一共 pair 即拒
                continue
            results.append(ticket)
            seen.add(ticket)
            used_pairs |= new_pairs
            usage.update(ticket)

    return results


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
    manual_excluded_numbers: Iterable[int] | None = None,
    manual_sum_range: tuple[int, int] | None = None,
    # Pre-computed analysis (UI passes a cached analysis to avoid re-running)
    precomputed_analysis: HistoryAnalysis | None = None,
    # Batch-disjoint mode: drag numbers are globally unique across tickets.
    batch_disjoint: bool = False,
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

    # Manual per-number exclusion (UI clickable grid)
    excl_nums: list[int] = []
    if manual_excluded_numbers is not None:
        excl_nums = _ensure_int_list("manual_excluded_numbers", manual_excluded_numbers)
        _validate_range("manual_excluded_numbers", excl_nums, POOL_MIN, POOL_MAX)
        _validate_unique("manual_excluded_numbers", excl_nums)
        pool -= set(excl_nums)

    if manual_keys is not None:
        keys = _ensure_int_list("manual_keys", manual_keys)
        _validate_range("manual_keys", keys, POOL_MIN, POOL_MAX)
        _validate_unique("manual_keys", keys)
        if not (MIN_KEY_NUMS <= len(keys) <= MAX_KEY_NUMS):
            raise ValueError(
                f"manual_keys must contain {MIN_KEY_NUMS}-{MAX_KEY_NUMS} numbers"
            )
        key_set = set(keys)
        # Manual conflict → explicit user error (UI also catches this upstream).
        if manual_excluded_numbers is not None:
            conflict = key_set & set(excl_nums)
            if conflict:
                raise ValueError(
                    f"keys {sorted(conflict)} conflict with manual_excluded_numbers"
                )
    else:
        # Auto-key path: silently drop any auto-suggested key that the user
        # has excluded. Empty key_set is tolerated (no-膽碼 fallback mode).
        keys = list(analysis.auto_keys)
        if len(keys) > MAX_KEY_NUMS:
            raise ValueError(
                f"auto_keys yielded {len(keys)} > max {MAX_KEY_NUMS}"
            )
        key_set = set(keys) - set(excl_nums)
        keys = sorted(key_set)

    drag_candidates = pool - key_set
    needed = TICKET_SIZE - len(key_set)
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

    # --- Batch-disjoint branch ---
    if batch_disjoint:
        # Strict batch mode: disable keys entirely so all 6 numbers are
        # disjoint across tickets.
        key_set = set()
        tickets = _generate_batch_disjoint(
            pool=pool,
            key_set=key_set,
            s_lo=s_lo,
            s_hi=s_hi,
            num_tickets=num_tickets,
            rng=rng,
        )
        # §4.2 不變量斷言（與 main return 同規格）
        for t in tickets:
            assert (
                len(t) == TICKET_SIZE
                and len(set(t)) == TICKET_SIZE
                and all(POOL_MIN <= n <= POOL_MAX for n in t)
            ), f"ticket invariant violated (batch-disjoint): {t}"
        return tickets, analysis

    # Round 1: standard 5-filter cascade with ticket-level uniqueness.
    results: list[tuple[int, ...]] = []
    seen: set[tuple[int, ...]] = set()
    for combo in all_combos:
        if len(results) >= num_tickets:
            break
        ticket = tuple(sorted(key_set.union(combo)))
        if ticket in seen:
            continue
        if not _passes_filters(ticket, s_lo, s_hi, apply_secondary=True):
            continue
        results.append(ticket)
        seen.add(ticket)

    # Round 2 (disjoint fallback): only triggers when Round 1 fell short.
    # Each new ticket's 6 numbers must NOT overlap with ANY prior ticket's
    # numbers. Three sub-rounds progressively relax the sum/secondary filters:
    #   sub-A: dynamic sum + full 5 filters
    #   sub-B: static 90-210     + full 5 filters
    #   sub-C: no sum bounds     + no secondary filters
    # Trade-off: Round 2 tickets cannot include keys (keys are "used" already
    # by Round 1 tickets). This is the documented cost of the disjoint mode.
    if len(results) < num_tickets:
        used_numbers: set[int] = set()
        for t in results:
            used_numbers |= set(t)
        remaining = pool - used_numbers
        if len(remaining) >= TICKET_SIZE:
            round2_combos = list(combinations(sorted(remaining), TICKET_SIZE))
            rng.shuffle(round2_combos)
            sub_rounds = (
                ((s_lo, s_hi), True),
                ((SUM_MIN, SUM_MAX), True),
                ((TICKET_SIZE * POOL_MIN, TICKET_SIZE * POOL_MAX), False),
            )
            for (sub_lo, sub_hi), apply_full in sub_rounds:
                if len(results) >= num_tickets:
                    break
                for combo in round2_combos:
                    if len(results) >= num_tickets:
                        break
                    combo_set = set(combo)
                    if combo_set & used_numbers:
                        continue
                    ticket = tuple(sorted(combo))
                    if ticket in seen:
                        continue
                    if not _passes_filters(ticket, sub_lo, sub_hi, apply_secondary=apply_full):
                        continue
                    results.append(ticket)
                    seen.add(ticket)
                    used_numbers |= combo_set

    # §4.2 不變量斷言：每注必為 6 顆唯一、值域 [POOL_MIN, POOL_MAX]
    for t in results:
        assert (
            len(t) == TICKET_SIZE
            and len(set(t)) == TICKET_SIZE
            and all(POOL_MIN <= n <= POOL_MAX for n in t)
        ), f"ticket invariant violated: {t}"

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
