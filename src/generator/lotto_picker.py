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
    Phase 4'  Howard mode       : (v6.19, opt-in) Gail Howard《Lottery Master
                                  Guide》黃金 8 條:#1/#2/#3 硬綁,#4-#8 軟分
                                  ≥ 3/5;Round 2/3 fallback 退回 v6.16 五大濾網。

Stdlib only: `random` + `itertools` (+ `collections`/`statistics` via engine).
"""

from __future__ import annotations

import random
from collections import Counter
from itertools import combinations
from typing import Iterable, Sequence

from src.generator.base_picker import (
    generate_batch_disjoint as _base_generate_batch_disjoint,
    passes_base_filters as _passes_base_filters,
    resolve_pool_and_keys as _resolve_pool_and_keys,
    validate_history as _base_validate_history,
    validate_num_tickets as _validate_num_tickets,
)
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
from src.generator.domain import LOTTO649 as _DOM

# Static fallback sum range (used when history unavailable; v5.0 §2)
SUM_MIN, SUM_MAX = STATIC_SUM_MIN, STATIC_SUM_MAX
# v6.22(B3+):基礎濾網/診斷常數源自 DomainConfig.LOTTO649(SSOT)。ticket_stats
# (每注診斷)與 _passes_filters(濾網)共用同一來源,杜絕門檻漂移;值不變,
# tests/test_domain.py 對帳鎖定 DomainConfig == 現役常數。
ALLOWED_ODD_COUNTS: frozenset = _DOM.allowed_odd_counts
BIG_THRESHOLD = _DOM.big_threshold
MIN_BIG_COUNT = _DOM.min_big_count
MAX_KEY_NUMS = _DOM.max_key_nums
MIN_KEY_NUMS = _DOM.min_key_nums

PRIMES_SET: frozenset = _DOM.primes_set
MIN_PRIME_COUNT = _DOM.min_prime_count
MAX_PRIME_COUNT = _DOM.max_prime_count
MAX_CONSECUTIVE_PAIRS = _DOM.max_consecutive_pairs

# v6.16 Howard #4 字頭追蹤(Decade Tracking)
# Source: Gail Howard, "Lottery Master Guide"
# 實測 577 期大樂透歷史命中率 87.0%(2026-06-23 sanity check):
# 至少 1 個字頭區間完全空(無號碼)是強統計事實 → 設為硬濾網。
# 威力彩 6/38 同規則僅 54.1% 命中 → §1 Fail Loud 拒用弱訊號當硬規則,只大樂透啟用。
DECADE_BANDS: tuple[frozenset[int], ...] = (
    frozenset(range(1, 10)),    # 單字頭 1-9
    frozenset(range(10, 20)),   # 一字頭
    frozenset(range(20, 30)),   # 二字頭
    frozenset(range(30, 40)),   # 三字頭
    frozenset(range(40, 50)),   # 四字頭
)
MIN_EMPTY_DECADES = 1

# v6.16 Howard #11 谷底陷阱(Bottom of the Barrel)
# 極冷號定義重用 engine `analysis.cold`(動態 μ + 1.5σ),不引入新 magic number。
# 實測 577 期大樂透命中率 85.8% ≤ 1 顆 cold(2026-06-23 sanity check)。
MAX_BASEMENT_PER_TICKET = 1

# v6.19 Howard 黃金 8 條(opt-in `howard_mode=True` 啟用)
# Source: Gail Howard《Lottery Master Guide》& 《Lotto Wheel Five to Win》
# 大樂透 6/49 域翻譯;#2 沿用 v6.16 `ALLOWED_ODD_COUNTS`、#5 配 v6.16
# `MIN_EMPTY_DECADES` 雙向夾擊、#11 谷底陷阱仍生效雙重保險(已驗證不衝突)。
# 倖存率估算:hard 3 條 ~40% × soft >= 3/5 ~50% ≈ 20%(實測待 backtest 確認)。
HOWARD_SUM_MIN = 115                                # #1 總和下界
HOWARD_SUM_MAX = 185                                # #1 總和上界
HOWARD_SMALL_THRESHOLD = 24                         # #3 切分:n <= 24 算小, n >= 25 算大
HOWARD_ALLOWED_SMALL_COUNTS: frozenset = frozenset({2, 3, 4})  # #3
HOWARD_EXACT_TAIL_PAIRS = 1                         # #4 同尾恰 1 對
HOWARD_MAX_EMPTY_DECADES = 2                        # #5 字頭空 1-2 個(下界用 v6.16 MIN_EMPTY_DECADES)
HOWARD_EXACT_CONSEC_PAIRS = 1                       # #6 連號恰 1 對
HOWARD_GAP5_THRESHOLD = 5                           # #7「近期出過」= gap <= 5
HOWARD_GAP5_ALLOWED_COUNTS: frozenset = frozenset({4, 5})  # #7 4-5 顆
HOWARD_REPEAT_FROM_LAST = 1                         # #8 上期含 1 顆
HOWARD_SOFT_MIN_SCORE = 3                           # 5 條軟分 >= 3 才通過
HOWARD_MIN_HISTORY = 5                              # 史料 < 5 期禁用 Howard


# --- Validation helpers(委派 base_picker;SSOT v6.23 B4b)----------------------


def _validate_history(draws: Sequence[Sequence[int]]) -> None:
    _base_validate_history(
        draws, pool_min=POOL_MIN, pool_max=POOL_MAX, ticket_size=TICKET_SIZE,
    )


def _howard_hard_pass(ticket: tuple[int, ...], s_lo: int, s_hi: int) -> bool:
    """v6.19 Howard 黃金 8 條 #1/#2/#3 硬綁。

    呼叫端負責把 s_lo/s_hi 設成 SMA±30 clamp 到 [HOWARD_SUM_MIN, HOWARD_SUM_MAX]。
    """
    if not (s_lo <= sum(ticket) <= s_hi):
        return False
    odd_count = sum(1 for n in ticket if n % 2 == 1)
    if odd_count not in ALLOWED_ODD_COUNTS:
        return False
    small_count = sum(1 for n in ticket if n <= HOWARD_SMALL_THRESHOLD)
    if small_count not in HOWARD_ALLOWED_SMALL_COUNTS:
        return False
    return True


def _howard_soft_score(
    ticket: tuple[int, ...],
    gaps: dict[int, int] | None,
    last_draw: frozenset[int],
) -> int:
    """v6.19 Howard #4-#8 軟分,返回 0-5。

    史料訊號不可得時自動 +1(`gaps=None` ⇒ #7 跳過;`last_draw=frozenset()` ⇒ #8 跳過)。
    呼叫端負責先驗證史料充足性(`HOWARD_MIN_HISTORY`)。
    """
    score = 0
    # #4 同尾恰 1 對:exactly 1 個尾數出現 2 次,其餘尾數都唯一(禁 ≥ 3 同尾)
    tail_counter = Counter(n % 10 for n in ticket)
    pair_tails = sum(1 for c in tail_counter.values() if c == 2)
    over_pairs = sum(1 for c in tail_counter.values() if c >= 3)
    if pair_tails == HOWARD_EXACT_TAIL_PAIRS and over_pairs == 0:
        score += 1
    # #5 字頭空 1-2 個(下界沿用 v6.16 MIN_EMPTY_DECADES=1)
    ticket_set = frozenset(ticket)
    empty_decades = sum(1 for band in DECADE_BANDS if not (band & ticket_set))
    if MIN_EMPTY_DECADES <= empty_decades <= HOWARD_MAX_EMPTY_DECADES:
        score += 1
    # #6 連號恰 1 對
    consec = sum(
        1 for i in range(TICKET_SIZE - 1) if ticket[i + 1] - ticket[i] == 1
    )
    if consec == HOWARD_EXACT_CONSEC_PAIRS:
        score += 1
    # #7 4-5 顆 gap <= 5(史料不足時 gaps=None → 自動 +1)
    if gaps is None:
        score += 1
    else:
        recent = sum(
            1 for n in ticket if gaps.get(n, 10**9) <= HOWARD_GAP5_THRESHOLD
        )
        if recent in HOWARD_GAP5_ALLOWED_COUNTS:
            score += 1
    # #8 連莊:上期含 1 顆(last_draw 空 frozenset → 自動 +1)
    if not last_draw:
        score += 1
    else:
        repeat = sum(1 for n in ticket if n in last_draw)
        if repeat == HOWARD_REPEAT_FROM_LAST:
            score += 1
    return score


def _decade_basement_ok(
    ticket: tuple[int, ...], basement_set: frozenset[int]
) -> bool:
    """大樂透附加濾網(v6.16 #4 字頭 + #11 谷底);作 base_picker `extra` hook。"""
    # v6.16 Howard #4: 至少 MIN_EMPTY_DECADES 個字頭區間完全空
    ticket_set = frozenset(ticket)
    empty = sum(1 for band in DECADE_BANDS if not (band & ticket_set))
    if empty < MIN_EMPTY_DECADES:
        return False
    # v6.16 Howard #11 谷底陷阱: ticket ∩ cold 顆數 ≤ MAX_BASEMENT_PER_TICKET
    if basement_set and sum(1 for n in ticket if n in basement_set) > MAX_BASEMENT_PER_TICKET:
        return False
    return True


def _passes_filters(
    ticket: tuple[int, ...],
    s_lo: int,
    s_hi: int,
    *,
    apply_secondary: bool,
    basement_set: frozenset[int] = frozenset(),
    howard_mode: bool = False,
    howard_gaps: dict[int, int] | None = None,
    howard_last_draw: frozenset[int] = frozenset(),
) -> bool:
    """Apply v6.16 七大濾網 (Howard #4 + #11 加入),或 v6.19 Howard 黃金 8 條。

    `apply_secondary=False` ⇒ sum-only (Round 3 fallback);所有次要濾網
    (奇偶/大小/質數/連號/字頭/谷底/Howard)全部關閉。

    `howard_mode=True` ⇒ #1/#2/#3 硬綁 + #4-#8 軟分 ≥ HOWARD_SOFT_MIN_SCORE;
    谷底陷阱(v6.16 #11)仍生效雙重保險。

    非 Howard 路徑:基礎 5 濾網委派 `base_picker.passes_base_filters`,字頭+谷底
    以 `extra` hook 注入(v6.23 B4b;DR-3 — 質數等濾網單一實作,改一處兩邊同步)。
    """
    if howard_mode and apply_secondary:
        if not _howard_hard_pass(ticket, s_lo, s_hi):
            return False
        if _howard_soft_score(ticket, howard_gaps, howard_last_draw) < HOWARD_SOFT_MIN_SCORE:
            return False
        # v6.16 谷底陷阱仍啟用(plan: 雙重保險,不衝突)
        if basement_set and sum(1 for n in ticket if n in basement_set) > MAX_BASEMENT_PER_TICKET:
            return False
        return True

    return _passes_base_filters(
        ticket, s_lo, s_hi, apply_secondary=apply_secondary, cfg=_DOM,
        extra=lambda t: _decade_basement_ok(t, basement_set),
    )


def _generate_batch_disjoint(
    *,
    pool: set[int],
    key_set: set[int],
    s_lo: int,
    s_hi: int,
    num_tickets: int,
    rng: random.Random,
    basement_set: frozenset[int] = frozenset(),
    howard_mode: bool = False,
    howard_gaps: dict[int, int] | None = None,
    howard_last_draw: frozenset[int] = frozenset(),
    fallback_s_lo: int | None = None,
    fallback_s_hi: int | None = None,
) -> list[tuple[int, ...]]:
    """批次覆蓋模式(v6.15):嚴格 pair-disjoint + 均衡硬上限。

    v6.13:任意 2 顆配對在所有注中至多出現一次。
    v6.15:在 v6.13 基礎上加「每號出現次數 ≤ ⌈6N/P⌉ + 1」的均衡硬上限
            (P = 有效池大小;+1 為使用者明示允許的容差);防止 pair-disjoint
            雖然不重複但某號 0 次、某號 5 次的高方差分佈。
    v6.19:加 Howard 模式:sub-A 套 Howard 8 條,sub-B/C/D 退回 v6.16。

    理論上限 = ⌊C(pool, 2) / C(6, 2)⌋(扣濾網實際更少)。

    Sub-round 漸進降級(每相內嚴格 pair-disjoint + 均衡 cap):
    - Howard 模式 4 相: Howard / v6.16 dynamic / v6.16 static / sum-only
    - v6.16  模式 3 相: dynamic sum + 5 filters / static + 5 filters / sum-only

    湊不到 num_tickets 直接 return,呼叫端負責 warn。
    """
    # 委派 base_picker.generate_batch_disjoint(v6.23 B4b);sub_rounds 編碼漸進降級。
    # 每相 filter_kwargs 透傳給 _passes_filters:(sub_lo, sub_hi, kwargs)。
    common = dict(
        basement_set=basement_set, howard_mode=False,
        howard_gaps=None, howard_last_draw=frozenset(),
    )
    if howard_mode:
        fb_lo = fallback_s_lo if fallback_s_lo is not None else SUM_MIN
        fb_hi = fallback_s_hi if fallback_s_hi is not None else SUM_MAX
        sub_rounds = (
            (s_lo, s_hi, dict(                          # sub-A: Howard
                apply_secondary=True, basement_set=basement_set,
                howard_mode=True, howard_gaps=howard_gaps,
                howard_last_draw=howard_last_draw,
            )),
            (fb_lo, fb_hi, dict(apply_secondary=True, **common)),      # sub-B: v6.16 dynamic
            (SUM_MIN, SUM_MAX, dict(apply_secondary=True, **common)),  # sub-C: v6.16 static
            (TICKET_SIZE * POOL_MIN, TICKET_SIZE * POOL_MAX,
             dict(apply_secondary=False, **common)),                  # sub-D: sum-only
        )
    else:
        sub_rounds = (
            (s_lo, s_hi, dict(apply_secondary=True, **common)),
            (SUM_MIN, SUM_MAX, dict(apply_secondary=True, **common)),
            (TICKET_SIZE * POOL_MIN, TICKET_SIZE * POOL_MAX,
             dict(apply_secondary=False, **common)),
        )
    return _base_generate_batch_disjoint(
        pool=pool, key_set=key_set, num_tickets=num_tickets, rng=rng,
        ticket_size=TICKET_SIZE, sub_rounds=sub_rounds, passes=_passes_filters,
    )


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
    # v6.19 Howard 黃金 8 條(opt-in)— 史料 < HOWARD_MIN_HISTORY 或 fallback raise
    howard_mode: bool = False,
    rng: random.Random | None = None,
) -> tuple[list[tuple[int, ...]], HistoryAnalysis]:
    """Produce up to `num_tickets` filtered combinations + analysis snapshot.

    Manual overrides — when provided — supersede dynamic signals; this is the
    surface that v5.0 §2 graceful-degradation path uses (UI substitutes
    STATIC_FALLBACK_ANALYSIS via `precomputed_analysis`).

    `howard_mode=True` 啟用 Gail Howard 黃金 8 條(v6.19):#1/#2/#3 硬綁 +
    #4-#8 軟分 ≥ 3/5;sum 範圍 SMA±30 clamp 到 [115, 185];Round 2/3 fallback
    自動退回 v6.16 五大濾網。**呼叫端必須**保證 `len(history_draws) >=
    HOWARD_MIN_HISTORY` 且 `analysis.is_fallback=False`,否則 raise(§1 Fail
    Loud — UI 必須先檢查再傳入)。

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
            hot_sigma_factor=hot_sigma_factor,
            cold_sigma_factor=cold_sigma_factor,
            sum_sma_window=sum_sma_window,
            sum_range_pad=sum_range_pad,
            overheat_recent_periods=overheat_recent_periods,
            overheat_min_count=overheat_min_count,
            dormant_periods=dormant_periods,
            rng=rng,
        )

    # --- v6.19 Howard mode validation (§1 Fail Loud) ---
    if howard_mode:
        if len(history_draws) < HOWARD_MIN_HISTORY:
            raise ValueError(
                f"howard_mode requires >= {HOWARD_MIN_HISTORY} history rows "
                f"(got {len(history_draws)}); UI must force howard_mode=False"
            )
        if analysis.is_fallback:
            raise ValueError(
                "howard_mode requires real history (analysis.is_fallback=True); "
                "UI must force howard_mode=False"
            )

    # --- Phase 2: pool + dynamic 雙膽（委派 base_picker;SSOT v6.23 B4b）---
    pool, key_set = _resolve_pool_and_keys(
        analysis,
        pool_min=POOL_MIN,
        pool_max=POOL_MAX,
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

    # --- Phase 4: five filters (or Howard 8 條 when howard_mode=True) ---
    v616_s_lo, v616_s_hi = analysis.sum_min_dynamic, analysis.sum_max_dynamic
    if manual_sum_range is not None:
        s_lo, s_hi = manual_sum_range
        if not (isinstance(s_lo, int) and isinstance(s_hi, int)):
            raise ValueError("manual_sum_range must be (int, int)")
        if s_lo > s_hi:
            raise ValueError("manual_sum_range lo must be <= hi")
    elif howard_mode:
        # v6.19 Howard #1: SMA±pad clamp 到 [HOWARD_SUM_MIN, HOWARD_SUM_MAX]
        h_lo = max(HOWARD_SUM_MIN, int(round(analysis.sum_sma - sum_range_pad)))
        h_hi = min(HOWARD_SUM_MAX, int(round(analysis.sum_sma + sum_range_pad)))
        if h_lo > h_hi:
            # SMA outside [115, 185] → collapse to nearest Howard boundary
            h_lo = h_hi = (
                HOWARD_SUM_MAX if analysis.sum_sma > HOWARD_SUM_MAX else HOWARD_SUM_MIN
            )
        s_lo, s_hi = h_lo, h_hi
    else:
        s_lo, s_hi = v616_s_lo, v616_s_hi

    # v6.16 Howard #11 谷底陷阱:極冷號集合來自 engine analysis.cold
    basement_set = frozenset(analysis.cold)

    # v6.19 Howard #7/#8 signals
    howard_gaps = dict(analysis.gaps) if howard_mode else None
    howard_last_draw = frozenset(history_draws[0]) if howard_mode else frozenset()

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
            basement_set=basement_set,
            howard_mode=howard_mode,
            howard_gaps=howard_gaps,
            howard_last_draw=howard_last_draw,
            fallback_s_lo=v616_s_lo,
            fallback_s_hi=v616_s_hi,
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
    # v6.19: 若 howard_mode=True 則套 Howard 8 條,否則沿用 v6.16 五大濾網。
    results: list[tuple[int, ...]] = []
    seen: set[tuple[int, ...]] = set()
    for combo in all_combos:
        if len(results) >= num_tickets:
            break
        ticket = tuple(sorted(key_set.union(combo)))
        if ticket in seen:
            continue
        if not _passes_filters(
            ticket, s_lo, s_hi,
            apply_secondary=True, basement_set=basement_set,
            howard_mode=howard_mode,
            howard_gaps=howard_gaps,
            howard_last_draw=howard_last_draw,
        ):
            continue
        results.append(ticket)
        seen.add(ticket)

    # Round 2 (disjoint fallback): only triggers when Round 1 fell short.
    # Each new ticket's 6 numbers must NOT overlap with ANY prior ticket's
    # numbers. Three sub-rounds progressively relax the sum/secondary filters:
    #   sub-A: dynamic sum + full 5 filters       (Howard 模式下用 v6.16 dynamic)
    #   sub-B: static 90-210     + full 5 filters
    #   sub-C: no sum bounds     + no secondary filters
    # v6.19: Howard 模式下 Round 2 一律退回 v6.16(plan 規定);keep 谷底陷阱。
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
            # v6.19:Howard 模式下 sub-A 改用 v616_s_lo/hi(本 round 已退回 v6.16)
            fallback_lo, fallback_hi = (
                (v616_s_lo, v616_s_hi) if howard_mode else (s_lo, s_hi)
            )
            sub_rounds = (
                ((fallback_lo, fallback_hi), True),
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
                    if not _passes_filters(
                        ticket, sub_lo, sub_hi,
                        apply_secondary=apply_full, basement_set=basement_set,
                    ):
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
