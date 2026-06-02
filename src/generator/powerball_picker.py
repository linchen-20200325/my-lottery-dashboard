"""威力彩 ticket generator (v6.0) — 五大濾網重校至 1-38 池 + 第二區獨立選號。

Pipeline 沿用 lotto649 v5.0 五階段，差異：
  - POOL_MAX 38（vs 49）
  - PRIMES_SET 裁切 ≤ 38（去掉 41/43/47）
  - BIG_THRESHOLD 19（vs 31；38//2）
  - 和值動態 clamp [80, 154]（vs [90, 210]）
  - 第二區 1-8 池透過 `manual_bonus` 覆寫或回傳 `analysis.bonus_auto_pick`

Stdlib only：`random` + `itertools`。
"""

from __future__ import annotations

import random
from itertools import combinations
from typing import Iterable, Sequence

from src.generator.powerball_engine import (
    BONUS_POOL_MAX,
    BONUS_POOL_MIN,
    DEFAULTS,
    MAIN_POOL_MAX,
    MAIN_POOL_MIN,
    STATIC_SUM_MAX,
    STATIC_SUM_MIN,
    TICKET_SIZE,
    PowerballAnalysis,
    analyze,
)

SUM_MIN, SUM_MAX = STATIC_SUM_MIN, STATIC_SUM_MAX
ALLOWED_ODD_COUNTS: frozenset = frozenset({2, 3, 4})
BIG_THRESHOLD = 19           # 38//2 — 「大數 > 19」≥ 3 顆
MIN_BIG_COUNT = 3
MAX_KEY_NUMS = 5
MIN_KEY_NUMS = 1

# 1-38 池內質數：去掉大樂透的 41/43/47
PRIMES_SET: frozenset = frozenset(
    {2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37}
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
        _validate_range(f"history_draws[{i}]", ints, MAIN_POOL_MIN, MAIN_POOL_MAX)
        _validate_unique(f"history_draws[{i}]", ints)


def _passes_filters(
    ticket: tuple[int, ...],
    s_lo: int,
    s_hi: int,
    *,
    apply_secondary: bool,
) -> bool:
    """威力彩 §6 五大濾網（與大樂透同形、參數重校）。"""
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


def _ticket_pairs(ticket: tuple[int, ...]) -> set[frozenset[int]]:
    return {frozenset(p) for p in combinations(ticket, 2)}


def _generate_pair_disjoint(
    *,
    pool: set[int],
    key_set: set[int],
    s_lo: int,
    s_hi: int,
    num_tickets: int,
    pair_overlap_max: int,
    rng: random.Random,
) -> list[tuple[int, ...]]:
    """漸進放寬 pair-disjoint（同 lotto649 v5.1 演算法、池參數差異吸收）。"""
    results: list[tuple[int, ...]] = []
    seen: set[tuple[int, ...]] = set()
    used_pairs: set[frozenset[int]] = set()

    drag_candidates = pool - key_set
    needed = TICKET_SIZE - len(key_set)
    if len(drag_candidates) < needed:
        return results
    all_combos = list(combinations(sorted(drag_candidates), needed))

    for sub_round in range(pair_overlap_max + 1):
        if len(results) >= num_tickets:
            break
        rng.shuffle(all_combos)
        for combo in all_combos:
            if len(results) >= num_tickets:
                break
            ticket = tuple(sorted(key_set.union(combo)))
            if ticket in seen:
                continue
            if not _passes_filters(ticket, s_lo, s_hi, apply_secondary=True):
                continue
            ticket_pairs = _ticket_pairs(ticket)
            if len(ticket_pairs & used_pairs) > sub_round:
                continue
            results.append(ticket)
            seen.add(ticket)
            used_pairs |= ticket_pairs

    return results


# --- Core algorithm -----------------------------------------------------------


def generate_tickets(
    history_draws: Sequence[Sequence[int]],
    history_specials: Sequence[int] | None = None,
    num_tickets: int = 5,
    *,
    hot_sigma_factor: float = DEFAULTS["hot_sigma_factor"],
    cold_sigma_factor: float = DEFAULTS["cold_sigma_factor"],
    sum_sma_window: int = DEFAULTS["sum_sma_window"],
    sum_range_pad: int = DEFAULTS["sum_range_pad"],
    overheat_recent_periods: int = DEFAULTS["overheat_recent_periods"],
    overheat_min_count: int = DEFAULTS["overheat_min_count"],
    dormant_periods: int = DEFAULTS["dormant_periods"],
    manual_keys: Iterable[int] | None = None,
    manual_excluded_tails: Iterable[int] | None = None,
    manual_excluded_numbers: Iterable[int] | None = None,
    manual_sum_range: tuple[int, int] | None = None,
    manual_bonus: int | None = None,
    precomputed_analysis: PowerballAnalysis | None = None,
    pair_disjoint: bool = False,
    pair_overlap_max: int = 0,
    rng: random.Random | None = None,
) -> tuple[list[tuple[int, ...]], int, PowerballAnalysis]:
    """產生最多 `num_tickets` 注（第一區）+ 第二區單顆特別號 + 訊號快照。

    回傳：(tickets, bonus_pick, analysis)
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
            specials=history_specials,
            hot_sigma_factor=hot_sigma_factor,
            cold_sigma_factor=cold_sigma_factor,
            sum_sma_window=sum_sma_window,
            sum_range_pad=sum_range_pad,
            overheat_recent_periods=overheat_recent_periods,
            overheat_min_count=overheat_min_count,
            dormant_periods=dormant_periods,
            rng=rng,
        )

    # --- Phase 2: 第一區 pool + 雙膽 ---
    if manual_excluded_tails is not None:
        excl = _ensure_int_list("manual_excluded_tails", manual_excluded_tails)
        _validate_range("manual_excluded_tails", excl, 0, 9)
        _validate_unique("manual_excluded_tails", excl)
        tail_set = set(excl)
    else:
        tail_set = set(analysis.exclude_tails)

    pool: set[int] = {
        n for n in range(MAIN_POOL_MIN, MAIN_POOL_MAX + 1)
        if (n % 10) not in tail_set
    }

    excl_nums: list[int] = []
    if manual_excluded_numbers is not None:
        excl_nums = _ensure_int_list("manual_excluded_numbers", manual_excluded_numbers)
        _validate_range("manual_excluded_numbers", excl_nums, MAIN_POOL_MIN, MAIN_POOL_MAX)
        _validate_unique("manual_excluded_numbers", excl_nums)
        pool -= set(excl_nums)

    if manual_keys is not None:
        keys = _ensure_int_list("manual_keys", manual_keys)
        _validate_range("manual_keys", keys, MAIN_POOL_MIN, MAIN_POOL_MAX)
        _validate_unique("manual_keys", keys)
        if not (MIN_KEY_NUMS <= len(keys) <= MAX_KEY_NUMS):
            raise ValueError(
                f"manual_keys must contain {MIN_KEY_NUMS}-{MAX_KEY_NUMS} numbers"
            )
        key_set = set(keys)
        if manual_excluded_numbers is not None:
            conflict = key_set & set(excl_nums)
            if conflict:
                raise ValueError(
                    f"keys {sorted(conflict)} conflict with manual_excluded_numbers"
                )
    else:
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

    # --- Phase 4: 五大濾網 ---
    if manual_sum_range is not None:
        s_lo, s_hi = manual_sum_range
        if not (isinstance(s_lo, int) and isinstance(s_hi, int)):
            raise ValueError("manual_sum_range must be (int, int)")
        if s_lo > s_hi:
            raise ValueError("manual_sum_range lo must be <= hi")
    else:
        s_lo, s_hi = analysis.sum_min_dynamic, analysis.sum_max_dynamic

    # --- Pair-disjoint 分支 ---
    if pair_disjoint:
        if not isinstance(pair_overlap_max, int) or isinstance(pair_overlap_max, bool):
            raise ValueError("pair_overlap_max must be a non-negative integer")
        if pair_overlap_max < 0:
            raise ValueError("pair_overlap_max must be >= 0")
        if len(key_set) > 1:
            raise ValueError(
                f"pair_disjoint mode requires ≤ 1 key (got {len(key_set)})"
            )
        tickets = _generate_pair_disjoint(
            pool=pool,
            key_set=key_set,
            s_lo=s_lo,
            s_hi=s_hi,
            num_tickets=num_tickets,
            pair_overlap_max=pair_overlap_max,
            rng=rng,
        )
        bonus_pick = _resolve_bonus(manual_bonus, analysis)
        return tickets, bonus_pick, analysis

    # Round 1: 標準五濾網 + 去重
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

    # Round 2: number-disjoint fallback（三層漸進放寬）
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
                ((TICKET_SIZE * MAIN_POOL_MIN, TICKET_SIZE * MAIN_POOL_MAX), False),
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

    bonus_pick = _resolve_bonus(manual_bonus, analysis)
    return results, bonus_pick, analysis


def _resolve_bonus(
    manual_bonus: int | None, analysis: PowerballAnalysis
) -> int:
    """第二區覆寫：manual_bonus 優先，否則 analysis.bonus_auto_pick。"""
    if manual_bonus is not None:
        if (isinstance(manual_bonus, bool)
                or not isinstance(manual_bonus, int)):
            raise ValueError("manual_bonus must be an integer")
        if not (BONUS_POOL_MIN <= manual_bonus <= BONUS_POOL_MAX):
            raise ValueError(
                f"manual_bonus {manual_bonus} out of range "
                f"[{BONUS_POOL_MIN}, {BONUS_POOL_MAX}]"
            )
        return manual_bonus
    return analysis.bonus_auto_pick


# --- Helpers ------------------------------------------------------------------


def ticket_stats(ticket: Iterable[int]) -> dict[str, int]:
    """單注診斷（與大樂透同形、BIG_THRESHOLD 改 19、PRIMES_SET 改裁切版）。"""
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
