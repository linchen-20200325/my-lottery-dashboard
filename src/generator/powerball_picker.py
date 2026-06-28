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

from src.generator.base_picker import (
    generate_batch_disjoint as _base_generate_batch_disjoint,
    passes_base_filters as _passes_base_filters,
    resolve_pool_and_keys as _resolve_pool_and_keys,
    validate_history as _base_validate_history,
    validate_num_tickets as _validate_num_tickets,
)
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
from src.generator.domain import POWERBALL as _DOM

SUM_MIN, SUM_MAX = STATIC_SUM_MIN, STATIC_SUM_MAX
# v6.22(B3+):基礎濾網/診斷常數源自 DomainConfig.POWERBALL(SSOT);ticket_stats
# 與 _passes_filters 共用同一來源(值不變,test_domain 對帳鎖定)。
ALLOWED_ODD_COUNTS: frozenset = _DOM.allowed_odd_counts
BIG_THRESHOLD = _DOM.big_threshold        # 38//2 — 「大數 > 19」≥ 3 顆
MIN_BIG_COUNT = _DOM.min_big_count
MAX_KEY_NUMS = _DOM.max_key_nums
MIN_KEY_NUMS = _DOM.min_key_nums

# 1-38 池內質數(裁掉大樂透的 41/43/47)
PRIMES_SET: frozenset = _DOM.primes_set
MIN_PRIME_COUNT = _DOM.min_prime_count
MAX_PRIME_COUNT = _DOM.max_prime_count
MAX_CONSECUTIVE_PAIRS = _DOM.max_consecutive_pairs


# --- Validation / 濾網 / 批次骨架(委派 base_picker;SSOT v6.23 B4b)-----------


def _validate_history(draws: Sequence[Sequence[int]]) -> None:
    _base_validate_history(
        draws, pool_min=MAIN_POOL_MIN, pool_max=MAIN_POOL_MAX, ticket_size=TICKET_SIZE,
    )


def _passes_filters(
    ticket: tuple[int, ...],
    s_lo: int,
    s_hi: int,
    *,
    apply_secondary: bool,
) -> bool:
    """威力彩 §6 五大濾網（base_picker 單一實作,濾網常數來自 DomainConfig）。"""
    return _passes_base_filters(
        ticket, s_lo, s_hi, apply_secondary=apply_secondary, cfg=_DOM,
    )


def _generate_batch_disjoint(
    *,
    pool: set[int],
    key_set: set[int],
    s_lo: int,
    s_hi: int,
    num_tickets: int,
    rng: random.Random,
) -> list[tuple[int, ...]]:
    """批次 pair-disjoint(v6.13/v6.15);三相漸進降級委派 base 骨架。

    - sub-A: dynamic sum (s_lo, s_hi) + 五濾網
    - sub-B: static [SUM_MIN, SUM_MAX] + 五濾網
    - sub-C: 無 sum 邊界 + 無次要濾網
    """
    sub_rounds = (
        (s_lo, s_hi, dict(apply_secondary=True)),
        (SUM_MIN, SUM_MAX, dict(apply_secondary=True)),
        (TICKET_SIZE * MAIN_POOL_MIN, TICKET_SIZE * MAIN_POOL_MAX,
         dict(apply_secondary=False)),
    )
    return _base_generate_batch_disjoint(
        pool=pool, key_set=key_set, num_tickets=num_tickets, rng=rng,
        ticket_size=TICKET_SIZE, sub_rounds=sub_rounds, passes=_passes_filters,
    )


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
    batch_disjoint: bool = False,
    rng: random.Random | None = None,
) -> tuple[list[tuple[int, ...]], int, PowerballAnalysis]:
    """產生最多 `num_tickets` 注（第一區）+ 第二區單顆特別號 + 訊號快照。

    回傳：(tickets, bonus_pick, analysis)
    Raises ValueError on invalid input or unsatisfiable configuration.
    """
    _validate_history(history_draws)
    _validate_num_tickets(num_tickets)

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

    # --- Phase 2: 第一區 pool + 雙膽（委派 base_picker;SSOT v6.23 B4b）---
    pool, key_set = _resolve_pool_and_keys(
        analysis,
        pool_min=MAIN_POOL_MIN,
        pool_max=MAIN_POOL_MAX,
        ticket_size=TICKET_SIZE,
        min_key_nums=MIN_KEY_NUMS,
        max_key_nums=MAX_KEY_NUMS,
        manual_excluded_tails=manual_excluded_tails,
        manual_excluded_numbers=manual_excluded_numbers,
        manual_keys=manual_keys,
    )

    # --- Phase 3: matrix shuffling ---
    drag_candidates = pool - key_set
    needed = TICKET_SIZE - len(key_set)
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

    # --- 批次覆蓋模式分支 ---
    if batch_disjoint:
        # 嚴格批次模式：停用膽碼，確保 6 號全域互斥。
        key_set = set()
        tickets = _generate_batch_disjoint(
            pool=pool,
            key_set=key_set,
            s_lo=s_lo,
            s_hi=s_hi,
            num_tickets=num_tickets,
            rng=rng,
        )
        bonus_pick = _resolve_bonus(manual_bonus, analysis)
        # §4.2 不變量斷言（與 main return 同規格）
        for t in tickets:
            assert (
                len(t) == TICKET_SIZE
                and len(set(t)) == TICKET_SIZE
                and all(MAIN_POOL_MIN <= n <= MAIN_POOL_MAX for n in t)
            ), f"ticket invariant violated (batch-disjoint): {t}"
        assert BONUS_POOL_MIN <= bonus_pick <= BONUS_POOL_MAX, \
            f"bonus_pick {bonus_pick} out of [1,8]"
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

    # §4.2 不變量斷言：每注必為 6 顆唯一、第一區 [1,38]、第二區 [1,8]
    for t in results:
        assert (
            len(t) == TICKET_SIZE
            and len(set(t)) == TICKET_SIZE
            and all(MAIN_POOL_MIN <= n <= MAIN_POOL_MAX for n in t)
        ), f"ticket invariant violated: {t}"
    assert BONUS_POOL_MIN <= bonus_pick <= BONUS_POOL_MAX, \
        f"bonus_pick {bonus_pick} out of [1,8]"

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
