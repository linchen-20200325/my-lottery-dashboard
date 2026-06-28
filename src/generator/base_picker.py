"""Shared ticket-generator core (v6.23 B4b — SSOT base for both pickers).

抽出大樂透 / 威力彩兩選號器 ~90% copy-paste 的共用骨架:
  - 3 個逐位元組相同 validator(`ensure_int_list`/`validate_range`/`validate_unique`)
    + 池邊界參數化 `validate_history`/`validate_num_tickets`
  - Phase 2 pool/雙膽建構 `resolve_pool_and_keys`
  - 基礎 5 濾網 `passes_base_filters`(sum + 奇偶/大小/質數/連號;DR-3 單一實作)
  - 批次 pair-disjoint 骨架 `generate_batch_disjoint`(v6.13/v6.15)

留作各 picker plug-in 的差異(REFACTOR_AUDIT §5.2「抽共用、留差異」):
  - 大樂透 Howard 黃金 8 條 + 字頭/谷底 → 透過 `passes_base_filters(extra=...)`
    的 `extra` hook 注入(generate_tickets 編排留 `lotto_picker`)
  - 威力彩第二區 `_resolve_bonus` → 後置步驟,留 `powerball_picker`

**DR-3 修復**:5 濾網(質數/大小/奇偶/連號)單一實作於 `passes_base_filters`,
改一處即兩邊同步(原本埋在大樂透 Howard 擴充裡,改質數檢查要改兩處)。

Stdlib only:`random` + `itertools` + `collections` + `math`(CLAUDE.md §8.4)。
"""

from __future__ import annotations

import math
import random
from collections import Counter
from itertools import combinations
from typing import Callable, Iterable, Sequence


# --- Validation helpers(兩 picker 逐位元組相同)-------------------------------


def ensure_int_list(name: str, values: Iterable[int]) -> list[int]:
    out: list[int] = []
    for v in values:
        if isinstance(v, bool) or not isinstance(v, int):
            raise ValueError(f"{name} must contain integers only (got {v!r})")
        out.append(v)
    return out


def validate_range(name: str, values: list[int], lo: int, hi: int) -> None:
    for v in values:
        if not (lo <= v <= hi):
            raise ValueError(f"{name} value {v} out of range [{lo}, {hi}]")


def validate_unique(name: str, values: list[int]) -> None:
    if len(set(values)) != len(values):
        raise ValueError(f"{name} must not contain duplicates")


def validate_history(
    draws: Sequence[Sequence[int]], *, pool_min: int, pool_max: int, ticket_size: int
) -> None:
    if not draws:
        raise ValueError("history_draws must not be empty")
    for i, d in enumerate(draws):
        if len(d) != ticket_size:
            raise ValueError(f"history_draws[{i}] must have 6 numbers")
        ints = ensure_int_list(f"history_draws[{i}]", d)
        validate_range(f"history_draws[{i}]", ints, pool_min, pool_max)
        validate_unique(f"history_draws[{i}]", ints)


def validate_num_tickets(num_tickets: int) -> None:
    if not isinstance(num_tickets, int) or isinstance(num_tickets, bool):
        raise ValueError("num_tickets must be an integer")
    if num_tickets < 1:
        raise ValueError("num_tickets must be >= 1")


# --- Phase 2:pool + 雙膽建構(兩 picker 僅池邊界不同)-------------------------


def resolve_pool_and_keys(
    analysis,
    *,
    pool_min: int,
    pool_max: int,
    ticket_size: int,
    min_key_nums: int,
    max_key_nums: int,
    manual_excluded_tails: Iterable[int] | None,
    manual_excluded_numbers: Iterable[int] | None,
    manual_keys: Iterable[int] | None,
) -> tuple[set[int], set[int]]:
    """回傳 `(pool, key_set)`。manual 覆寫優先於 `analysis` 動態訊號(§3)。

    Raises ValueError on conflict / out-of-range / 拖碼池不足(訊息與兩 picker
    原本逐字相同)。
    """
    if manual_excluded_tails is not None:
        excl = ensure_int_list("manual_excluded_tails", manual_excluded_tails)
        validate_range("manual_excluded_tails", excl, 0, 9)
        validate_unique("manual_excluded_tails", excl)
        tail_set = set(excl)
    else:
        tail_set = set(analysis.exclude_tails)

    pool: set[int] = {
        n for n in range(pool_min, pool_max + 1) if (n % 10) not in tail_set
    }

    excl_nums: list[int] = []
    if manual_excluded_numbers is not None:
        excl_nums = ensure_int_list("manual_excluded_numbers", manual_excluded_numbers)
        validate_range("manual_excluded_numbers", excl_nums, pool_min, pool_max)
        validate_unique("manual_excluded_numbers", excl_nums)
        pool -= set(excl_nums)

    if manual_keys is not None:
        keys = ensure_int_list("manual_keys", manual_keys)
        validate_range("manual_keys", keys, pool_min, pool_max)
        validate_unique("manual_keys", keys)
        if not (min_key_nums <= len(keys) <= max_key_nums):
            raise ValueError(
                f"manual_keys must contain {min_key_nums}-{max_key_nums} numbers"
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
        if len(keys) > max_key_nums:
            raise ValueError(
                f"auto_keys yielded {len(keys)} > max {max_key_nums}"
            )
        key_set = set(keys) - set(excl_nums)

    drag_candidates = pool - key_set
    needed = ticket_size - len(key_set)
    if len(drag_candidates) < needed:
        raise ValueError(
            f"insufficient drag candidates: need {needed}, "
            f"available {len(drag_candidates)} (after excluding tails {sorted(tail_set)})"
        )
    return pool, key_set


# --- 基礎 5 濾網(DR-3 單一實作)----------------------------------------------


def passes_base_filters(
    ticket: tuple[int, ...],
    s_lo: int,
    s_hi: int,
    *,
    apply_secondary: bool,
    cfg,
    extra: Callable[[tuple[int, ...]], bool] | None = None,
) -> bool:
    """sum ∈ [s_lo, s_hi] + 奇偶/大小/質數/連號(濾網常數來自 `cfg`=DomainConfig)。

    `apply_secondary=False` ⇒ sum-only(fallback);次要濾網全關。
    `extra` ⇒ 領域附加濾網 hook(大樂透字頭+谷底);僅 `apply_secondary=True` 時呼叫。
    """
    if not (s_lo <= sum(ticket) <= s_hi):
        return False
    if not apply_secondary:
        return True
    odd_count = sum(1 for n in ticket if n % 2 == 1)
    if odd_count not in cfg.allowed_odd_counts:
        return False
    if sum(1 for n in ticket if n > cfg.big_threshold) < cfg.min_big_count:
        return False
    prime_count = sum(1 for n in ticket if n in cfg.primes_set)
    if not (cfg.min_prime_count <= prime_count <= cfg.max_prime_count):
        return False
    consecutive_pairs = sum(
        1 for i in range(cfg.ticket_size - 1) if ticket[i + 1] - ticket[i] == 1
    )
    if consecutive_pairs > cfg.max_consecutive_pairs:
        return False
    if extra is not None and not extra(ticket):
        return False
    return True


# --- 批次 pair-disjoint 骨架(v6.13/v6.15)------------------------------------


def generate_batch_disjoint(
    *,
    pool: set[int],
    key_set: set[int],
    num_tickets: int,
    rng: random.Random,
    ticket_size: int,
    sub_rounds: Sequence[tuple[int, int, dict]],
    passes: Callable[..., bool],
) -> list[tuple[int, ...]]:
    """嚴格 pair-disjoint(任 2 顆配對至多出現一次)+ 均衡硬上限(每號 ≤ ⌈6N/P⌉+1)。

    `sub_rounds`:`(sub_lo, sub_hi, filter_kwargs)` 序列,呼叫端用以編碼漸進降級
    (Howard / v6.16 dynamic / static / sum-only)。
    `passes`:領域 `_passes_filters`,以 `passes(ticket, sub_lo, sub_hi, **kwargs)` 呼叫。

    湊不到 `num_tickets` 直接 return,呼叫端負責 warn。
    """
    results: list[tuple[int, ...]] = []
    seen: set[tuple[int, ...]] = set()
    used_pairs: set[tuple[int, int]] = set()
    usage: Counter[int] = Counter()
    # v6.15 均衡硬上限:每號出現 ≤ ⌈6N/P⌉ + 1(容差 1)
    max_per_number = math.ceil(ticket_size * num_tickets / len(pool)) + 1

    drag_candidates = pool - key_set
    needed = ticket_size - len(key_set)
    if len(drag_candidates) < needed:
        return results  # caller already validated drag pool size; defensive
    all_combos = list(combinations(sorted(drag_candidates), needed))
    rng.shuffle(all_combos)

    for sub_lo, sub_hi, kwargs in sub_rounds:
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
            if not passes(ticket, sub_lo, sub_hi, **kwargs):
                continue
            new_pairs = set(combinations(ticket, 2))
            if new_pairs & used_pairs:  # 嚴格 pair-disjoint: 任一共 pair 即拒
                continue
            results.append(ticket)
            seen.add(ticket)
            used_pairs |= new_pairs
            usage.update(ticket)

    return results
