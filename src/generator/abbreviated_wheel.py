"""Lotto 6/49 abbreviated wheel — 精簡包牌 (v6.20).

Implements a (v=12, k=6, t=4; p=3) lottery covering design — aka "4保3":
given a 12-number pool, if any 4 of the 6 winning numbers fall within the pool,
at least one ticket in the wheel contains at least 3 of those 4.

Design: hard-coded 8-ticket wheel, derived via randomized-greedy set-cover
(500 restarts; tests/test_abbreviated_wheel.py verifies all C(12,4)=495
four-subsets exhaustively).

Notes:
    - 8 tickets is the greedy upper bound; the theoretical minimum L(12,6,4,3)
      may be 6 or 7 but requires exhaustive ILP search to confirm — out of scope.
    - Cost: 8 × NT$ 50 = NT$ 400 per wheel.
    - This module does NOT apply v6.16 or Howard filters — the wheel's guarantee
      is a *mathematical property*, distinct from statistical filters. Mixing
      would weaken the covering guarantee.

Stdlib only: `random` + `itertools`.
"""

from __future__ import annotations

import random
from typing import Sequence

from src.generator.history_engine import POOL_MAX, POOL_MIN, TICKET_SIZE

WHEEL_SIZE = 12                                         # 池大小
WHEEL_TICKET_COUNT = 8                                  # 注數(greedy 上限)
WHEEL_GUARANTEE_T = 4                                   # 4 個中獎號在池內
WHEEL_GUARANTEE_P = 3                                   # 保證至少 3 個在某注

# 8-ticket wheel indexed over positions 0..11.
# Each tuple is sorted indices into a sorted pool.
# Source: greedy set-cover on (12,6,4;3) lotto design, seed=0 fixed for repro.
# Verified by tests/test_abbreviated_wheel.py over all 495 four-subsets.
WHEEL_12_4_OF_4_3: tuple[tuple[int, ...], ...] = (
    (0, 1, 2, 3, 4, 5),
    (0, 6, 7, 8, 9, 10),
    (1, 2, 3, 6, 7, 11),
    (4, 5, 8, 9, 10, 11),
    (1, 2, 4, 5, 6, 7),
    (3, 4, 5, 8, 9, 10),
    (0, 1, 8, 9, 10, 11),
    (0, 1, 2, 4, 5, 11),
)


def _validate_pool(pool: Sequence[int]) -> None:
    """Fail Loud: enforce 12 unique ints ∈ [1, 49]."""
    if not isinstance(pool, (list, tuple)):
        raise TypeError(f"pool must be list/tuple, got {type(pool).__name__}")
    if len(pool) != WHEEL_SIZE:
        raise ValueError(
            f"abbreviated wheel requires exactly {WHEEL_SIZE} numbers, got {len(pool)}"
        )
    for n in pool:
        if not isinstance(n, int) or isinstance(n, bool):
            raise TypeError(f"pool element must be int, got {n!r}")
        if not (POOL_MIN <= n <= POOL_MAX):
            raise ValueError(
                f"pool element {n} out of range [{POOL_MIN}, {POOL_MAX}]"
            )
    if len(set(pool)) != WHEEL_SIZE:
        raise ValueError(f"pool contains duplicates: {sorted(pool)}")


def pick_abbreviated_wheel(
    pool: Sequence[int],
    seed: int | None = None,
) -> list[tuple[int, ...]]:
    """Return 8 tickets covering a 12-number pool with 4保3 guarantee.

    Args:
        pool: 12 unique ints ∈ [1, 49].
        seed: optional RNG seed; shuffles pool→wheel position mapping for
              variety. Same seed → same output (reproducibility).

    Returns:
        List of 8 sorted 6-tuples. Each tuple is a valid lotto ticket.

    Raises:
        ValueError / TypeError: pool fails §1 Fail Loud validation.
    """
    _validate_pool(pool)

    ordered = sorted(pool)                              # canonical order first
    if seed is not None:
        rng = random.Random(seed)
        rng.shuffle(ordered)                            # in-place permutation

    tickets = []
    for line in WHEEL_12_4_OF_4_3:
        ticket = tuple(sorted(ordered[i] for i in line))
        # invariant: 6 unique ints in pool range
        assert len(ticket) == TICKET_SIZE
        assert len(set(ticket)) == TICKET_SIZE
        assert all(POOL_MIN <= n <= POOL_MAX for n in ticket)
        tickets.append(ticket)
    return tickets
