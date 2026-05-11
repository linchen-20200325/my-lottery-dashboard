"""Lotto 6/49 quantitative ticket generator (4-phase filter model).

Stdlib-only by design (no pandas/numpy). Each call is stateless and depends
solely on t-1 inputs — no historical database is consulted.

Pipeline:
    Phase 1  Pool reduction   : universe = {1..49} \\ previous_draw \\ tail_matches
    Phase 2  Pillar & drag    : enforce key_nums; drag = (drag_nums ∩ pool) - key_nums
    Phase 3  Matrix shuffling : random.shuffle(list(combinations(drag, needed)))
    Phase 4  Filters          : sum 120-180, odd_count ∈ {2,3,4}, big(>31)_count ≥ 3
"""

from __future__ import annotations

import random
from itertools import combinations
from typing import Iterable

POOL_MIN, POOL_MAX = 1, 49
TICKET_SIZE = 6
SUM_MIN, SUM_MAX = 120, 180
ALLOWED_ODD_COUNTS: frozenset[int] = frozenset({2, 3, 4})
BIG_THRESHOLD = 31
MIN_BIG_COUNT = 3
MAX_KEY_NUMS = 5
MIN_KEY_NUMS = 1


# --- Validation ---------------------------------------------------------------


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


# --- Core algorithm -----------------------------------------------------------


def generate_tickets(
    previous_draw: Iterable[int],
    exclude_tails: Iterable[int],
    key_nums: Iterable[int],
    drag_nums: Iterable[int] | None = None,
    num_tickets: int = 5,
    rng: random.Random | None = None,
) -> list[tuple[int, ...]]:
    """Produce up to `num_tickets` filtered 6-number combinations.

    Raises:
        ValueError on any invalid input or unsatisfiable configuration.
    """
    # --- Coerce & validate ---
    prev = _ensure_int_list("previous_draw", previous_draw)
    tails = _ensure_int_list("exclude_tails", exclude_tails)
    keys = _ensure_int_list("key_nums", key_nums)

    if len(prev) != TICKET_SIZE:
        raise ValueError(
            f"previous_draw must have exactly {TICKET_SIZE} numbers, got {len(prev)}"
        )
    _validate_range("previous_draw", prev, POOL_MIN, POOL_MAX)
    _validate_unique("previous_draw", prev)

    _validate_range("exclude_tails", tails, 0, 9)
    _validate_unique("exclude_tails", tails)

    _validate_range("key_nums", keys, POOL_MIN, POOL_MAX)
    _validate_unique("key_nums", keys)
    if not (MIN_KEY_NUMS <= len(keys) <= MAX_KEY_NUMS):
        raise ValueError(
            f"key_nums must contain {MIN_KEY_NUMS} to {MAX_KEY_NUMS} numbers"
        )

    if not isinstance(num_tickets, int) or isinstance(num_tickets, bool):
        raise ValueError("num_tickets must be an integer")
    if num_tickets < 1:
        raise ValueError("num_tickets must be >= 1")

    rng = rng if rng is not None else random.Random()

    # --- Phase 1: pool reduction ---
    tail_set = set(tails)
    pool: set[int] = {
        n for n in range(POOL_MIN, POOL_MAX + 1)
        if n not in set(prev) and (n % 10) not in tail_set
    }

    # --- Phase 2: pillar & drag ---
    key_set = set(keys)
    # Keys always survive Phase 1 ("絕對優先權")
    if drag_nums is None:
        drag_candidates: set[int] = pool - key_set
    else:
        drag_list = _ensure_int_list("drag_nums", drag_nums)
        _validate_range("drag_nums", drag_list, POOL_MIN, POOL_MAX)
        _validate_unique("drag_nums", drag_list)
        drag_candidates = (set(drag_list) & pool) - key_set

    needed = TICKET_SIZE - len(keys)
    if len(drag_candidates) < needed:
        raise ValueError(
            f"insufficient drag candidates after Phase 1: "
            f"need {needed}, available {len(drag_candidates)}"
        )

    # --- Phase 3: matrix shuffling ---
    drag_sorted = sorted(drag_candidates)
    all_combos = list(combinations(drag_sorted, needed))
    rng.shuffle(all_combos)

    # --- Phase 4: multi-factor filters ---
    results: list[tuple[int, ...]] = []
    for combo in all_combos:
        ticket = tuple(sorted(key_set.union(combo)))
        if not (SUM_MIN <= sum(ticket) <= SUM_MAX):
            continue
        odd_count = sum(1 for n in ticket if n % 2 == 1)
        if odd_count not in ALLOWED_ODD_COUNTS:
            continue
        if sum(1 for n in ticket if n > BIG_THRESHOLD) < MIN_BIG_COUNT:
            continue
        results.append(ticket)
        if len(results) >= num_tickets:
            break

    return results


# --- Helpers ------------------------------------------------------------------


def ticket_stats(ticket: Iterable[int]) -> dict[str, int]:
    """Per-ticket diagnostics (sum, odd/even, big/small counts)."""
    t = list(ticket)
    return {
        "sum": sum(t),
        "odd_count": sum(1 for n in t if n % 2 == 1),
        "even_count": sum(1 for n in t if n % 2 == 0),
        "big_count": sum(1 for n in t if n > BIG_THRESHOLD),
        "small_count": sum(1 for n in t if n <= BIG_THRESHOLD),
    }
