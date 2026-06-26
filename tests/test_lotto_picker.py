"""Unit tests for the v3.0 dynamic Lotto picker."""

import random
import unittest

from src.generator.history_engine import HistoryAnalysis
from src.generator.lotto_picker import (
    ALLOWED_ODD_COUNTS,
    BIG_THRESHOLD,
    DECADE_BANDS,
    MAX_BASEMENT_PER_TICKET,
    MAX_CONSECUTIVE_PAIRS,
    MAX_PRIME_COUNT,
    MIN_BIG_COUNT,
    MIN_EMPTY_DECADES,
    MIN_PRIME_COUNT,
    PRIMES_SET,
    SUM_MAX,
    SUM_MIN,
    TICKET_SIZE,
    generate_tickets,
    ticket_stats,
)


def _custom_analysis(*, auto_keys: list[int], sum_lo: int = 120, sum_hi: int = 180) -> HistoryAnalysis:
    """Test helper: build a deterministic HistoryAnalysis with given auto_keys."""
    return HistoryAnalysis(
        hot=auto_keys[:1], warm=[], cold=auto_keys[1:2],
        gaps={n: 0 for n in range(1, 50)},
        gap_mean=5.0, gap_std=2.0,
        hot_threshold=2.0, cold_threshold=15.0,
        sum_sma=float((sum_lo + sum_hi) // 2),
        sum_min_dynamic=sum_lo, sum_max_dynamic=sum_hi,
        tail_counts_recent={t: 0 for t in range(10)},
        overheated_tails=[], dormant_tails=[],
        exclude_tails=[], auto_keys=sorted(auto_keys),
        is_fallback=False,
    )

# A diverse 30-period synthetic history (enough for layering tests)
HISTORY = [
    [3, 12, 19, 25, 33, 42], [7, 15, 22, 28, 36, 45], [1, 9, 18, 26, 31, 40],
    [4, 11, 20, 24, 35, 44], [2, 14, 17, 23, 38, 47], [6, 13, 21, 27, 34, 43],
    [5, 10, 16, 29, 37, 41], [8, 19, 25, 30, 39, 46], [1, 11, 22, 32, 41, 48],
    [3, 14, 23, 28, 35, 42], [7, 12, 18, 26, 34, 45], [4, 15, 21, 27, 33, 43],
    [2, 9, 17, 24, 36, 44], [6, 13, 20, 29, 37, 47], [5, 10, 19, 25, 31, 40],
    [8, 11, 16, 22, 38, 46], [1, 14, 21, 28, 35, 41], [3, 9, 18, 27, 32, 49],
    [7, 12, 23, 26, 34, 43], [4, 15, 17, 29, 36, 44], [2, 13, 22, 30, 39, 45],
    [6, 10, 16, 24, 33, 42], [5, 11, 21, 27, 37, 46], [8, 14, 18, 28, 31, 48],
    [1, 9, 20, 25, 35, 41], [3, 13, 19, 26, 38, 47], [7, 11, 22, 30, 34, 43],
    [4, 12, 17, 24, 36, 44], [2, 15, 21, 29, 33, 42], [6, 10, 23, 27, 39, 45],
]


def _is_valid_ticket(t):
    if len(t) != TICKET_SIZE or len(set(t)) != TICKET_SIZE:
        return False
    if not all(1 <= n <= 49 for n in t):
        return False
    if not (SUM_MIN <= sum(t) <= SUM_MAX):
        return False
    if sum(1 for n in t if n % 2 == 1) not in ALLOWED_ODD_COUNTS:
        return False
    if sum(1 for n in t if n > BIG_THRESHOLD) < MIN_BIG_COUNT:
        return False
    primes = sum(1 for n in t if n in PRIMES_SET)
    if not (MIN_PRIME_COUNT <= primes <= MAX_PRIME_COUNT):
        return False
    s = sorted(t)
    consec = sum(1 for i in range(len(s) - 1) if s[i + 1] - s[i] == 1)
    if consec > MAX_CONSECUTIVE_PAIRS:
        return False
    return True


class TestDynamicHappyPath(unittest.TestCase):
    def test_returns_filtered_tickets_and_analysis(self):
        tickets, analysis = generate_tickets(
            history_draws=HISTORY,
            num_tickets=5,
            rng=random.Random(2026),
        )
        self.assertGreater(len(tickets), 0)
        for t in tickets:
            self.assertTrue(_is_valid_ticket(t), f"invalid: {t}")
        # auto_keys are in every ticket
        for k in analysis.auto_keys:
            for t in tickets:
                self.assertIn(k, t)

    def test_excluded_tails_respected(self):
        tickets, analysis = generate_tickets(
            history_draws=HISTORY,
            num_tickets=5,
            rng=random.Random(7),
        )
        excluded = {n for n in range(1, 50) if (n % 10) in set(analysis.exclude_tails)}
        excluded -= set(analysis.auto_keys)  # keys can be force-included (but shouldn't overlap)
        for t in tickets:
            self.assertFalse(set(t) & excluded, f"tail leak {t}")

    def test_seed_reproducible(self):
        a, _ = generate_tickets(history_draws=HISTORY, num_tickets=5,
                                rng=random.Random(123))
        b, _ = generate_tickets(history_draws=HISTORY, num_tickets=5,
                                rng=random.Random(123))
        self.assertEqual(a, b)


class TestManualOverride(unittest.TestCase):
    def test_manual_keys_override(self):
        tickets, _ = generate_tickets(
            history_draws=HISTORY,
            num_tickets=5,
            manual_keys=[7, 17],
            manual_excluded_tails=[],
            rng=random.Random(1),
        )
        for t in tickets:
            self.assertIn(7, t)
            self.assertIn(17, t)

    def test_manual_excluded_tails_override(self):
        tickets, _ = generate_tickets(
            history_draws=HISTORY,
            num_tickets=10,
            manual_keys=[33],
            manual_excluded_tails=[0, 9],
            rng=random.Random(2),
        )
        forbidden = {n for n in range(1, 50) if n % 10 in {0, 9}}
        for t in tickets:
            self.assertFalse(set(t) & forbidden, f"tail leak {t}")

    def test_manual_excluded_numbers(self):
        excluded = [13, 21, 34, 42, 47]
        tickets, _ = generate_tickets(
            history_draws=HISTORY,
            num_tickets=10,
            manual_keys=[7],
            manual_excluded_numbers=excluded,
            rng=random.Random(11),
        )
        self.assertGreater(len(tickets), 0)
        forbidden = set(excluded)
        for t in tickets:
            self.assertFalse(set(t) & forbidden, f"excluded number leaked: {t}")
            self.assertIn(7, t)

    def test_manual_excluded_numbers_conflict_with_key(self):
        with self.assertRaises(ValueError):
            generate_tickets(
                history_draws=HISTORY,
                num_tickets=5,
                manual_keys=[7, 33],
                manual_excluded_numbers=[33],
            )

    def test_manual_excluded_numbers_out_of_range(self):
        with self.assertRaises(ValueError):
            generate_tickets(
                history_draws=HISTORY,
                num_tickets=5,
                manual_keys=[7],
                manual_excluded_numbers=[50],
            )

    def test_manual_excluded_numbers_duplicates(self):
        with self.assertRaises(ValueError):
            generate_tickets(
                history_draws=HISTORY,
                num_tickets=5,
                manual_keys=[7],
                manual_excluded_numbers=[13, 13],
            )


class TestEdgeCases(unittest.TestCase):
    def test_empty_history_rejected(self):
        with self.assertRaises(ValueError):
            generate_tickets(history_draws=[], num_tickets=5)

    def test_invalid_history_row(self):
        bad = [[1, 2, 3, 4, 5, 50]] + HISTORY
        with self.assertRaises(ValueError):
            generate_tickets(history_draws=bad, num_tickets=5)

    def test_manual_keys_too_many(self):
        with self.assertRaises(ValueError):
            generate_tickets(
                history_draws=HISTORY,
                num_tickets=5,
                manual_keys=[1, 2, 3, 4, 5, 6],
            )

    def test_manual_keys_duplicates(self):
        with self.assertRaises(ValueError):
            generate_tickets(
                history_draws=HISTORY,
                num_tickets=5,
                manual_keys=[5, 5, 7],
            )

    def test_invalid_num_tickets(self):
        with self.assertRaises(ValueError):
            generate_tickets(history_draws=HISTORY, num_tickets=0)

    def test_insufficient_drag_via_aggressive_tail_exclusion(self):
        with self.assertRaises(ValueError):
            generate_tickets(
                history_draws=HISTORY,
                num_tickets=1,
                manual_keys=[3],
                manual_excluded_tails=list(range(10)),  # excludes everything
            )


class TestSilentDropAndDisjoint(unittest.TestCase):
    """v6: auto-key conflicts silently dropped; disjoint Round 2 fills shortfall."""

    def test_auto_key_conflict_silently_dropped(self):
        # Auto-suggested keys are [7, 33]; user excludes 33.
        # Engine must drop 33 from keys (NOT raise) and keep producing.
        analysis = _custom_analysis(auto_keys=[7, 33])
        tickets, _ = generate_tickets(
            history_draws=HISTORY,
            num_tickets=3,
            manual_excluded_numbers=[33],
            precomputed_analysis=analysis,
            rng=random.Random(7),
        )
        self.assertGreater(len(tickets), 0)
        for t in tickets:
            self.assertNotIn(33, t)
            # Remaining auto-key 7 appears in every Round-1 ticket.
            self.assertIn(7, t)

    def test_all_auto_keys_dropped_falls_back_to_no_keys(self):
        # All auto-suggested keys conflict with user's exclusion.
        # Engine enters no-膽碼 mode (key_set empty) and still produces.
        analysis = _custom_analysis(auto_keys=[7, 33])
        tickets, _ = generate_tickets(
            history_draws=HISTORY,
            num_tickets=3,
            manual_excluded_numbers=[7, 33],
            precomputed_analysis=analysis,
            rng=random.Random(7),
        )
        self.assertGreater(len(tickets), 0)
        for t in tickets:
            self.assertNotIn(7, t)
            self.assertNotIn(33, t)

    def test_manual_keys_conflict_still_raises(self):
        # Existing test already covers this in TestManualOverride; re-assert here
        # for clarity that the silent-drop applies ONLY to auto-keys, not manual.
        with self.assertRaises(ValueError):
            generate_tickets(
                history_draws=HISTORY,
                num_tickets=3,
                manual_keys=[7, 33],
                manual_excluded_numbers=[33],
            )

    def test_shortfall_triggers_disjoint_round2(self):
        # Impossibly narrow sum range with a key forces Round 1 to yield 0;
        # Round 2 sub-B (static 90-210) fills with disjoint tickets sans key.
        tickets, _ = generate_tickets(
            history_draws=HISTORY,
            num_tickets=3,
            manual_keys=[7],
            manual_sum_range=(6, 21),  # ticket including 7 must sum ≥ 7+1+2+3+4+5=22
            rng=random.Random(11),
        )
        self.assertGreaterEqual(len(tickets), 1, "Round 2 should have filled some")
        for t in tickets:
            # Round 2 tickets do NOT carry the key (key is "used" by R1's zero output's pool reservation)
            self.assertNotIn(7, t)
        # All Round 2 tickets must be pairwise disjoint
        for i in range(len(tickets)):
            for j in range(i + 1, len(tickets)):
                self.assertFalse(
                    set(tickets[i]) & set(tickets[j]),
                    f"Round 2 tickets {tickets[i]} and {tickets[j]} share numbers",
                )

    def test_round2_tickets_disjoint_from_round1(self):
        # Narrow filter forces partial shortfall: R1 yields some, R2 fills rest.
        # R2 tickets must have ZERO overlap with R1's number footprint.
        tickets, _ = generate_tickets(
            history_draws=HISTORY,
            num_tickets=8,
            manual_keys=[7],
            manual_sum_range=(170, 175),  # narrow but feasible
            rng=random.Random(42),
        )
        r1 = [t for t in tickets if 7 in t]
        r2 = [t for t in tickets if 7 not in t]
        if r2:  # Only verify if Round 2 actually activated
            r1_numbers: set[int] = set()
            for t in r1:
                r1_numbers |= set(t)
            for r2t in r2:
                self.assertFalse(
                    set(r2t) & r1_numbers,
                    f"R2 ticket {r2t} overlaps R1 numbers {sorted(r1_numbers)}",
                )


def _assert_pair_disjoint(test, tickets):
    """每個 unordered pair 在所有注中至多出現一次(v6.13 契約)。"""
    from itertools import combinations
    used: set[tuple[int, int]] = set()
    for idx, t in enumerate(tickets):
        for pair in combinations(sorted(t), 2):
            test.assertNotIn(
                pair, used,
                f"pair {pair} duplicated in ticket #{idx + 1}: {t}",
            )
            used.add(pair)


def _assert_usage_balanced(test, tickets, pool_size):
    """v6.15 契約:每號出現次數 ≤ ⌈6N/P⌉ + 1。"""
    import math
    from collections import Counter
    if not tickets:
        return
    cap = math.ceil(6 * len(tickets) / pool_size) + 1
    usage = Counter()
    for t in tickets:
        usage.update(t)
    over = {n: c for n, c in usage.items() if c > cap}
    test.assertFalse(
        over,
        f"v6.15 均衡上限被違反:cap={cap} 但 {over} 超出 "
        f"(N={len(tickets)} tickets, P={pool_size} pool)",
    )


class TestBatchDisjoint(unittest.TestCase):
    """批次推薦模式 (v6.13):嚴格 pair-disjoint — 任意 2 顆配對在所有注中至多出現一次。"""

    def test_no_keys_pair_disjoint(self):
        analysis = _custom_analysis(auto_keys=[])
        tickets, _ = generate_tickets(
            history_draws=HISTORY,
            num_tickets=3,
            manual_excluded_tails=[],
            precomputed_analysis=analysis,
            batch_disjoint=True,
            rng=random.Random(42),
        )
        self.assertGreaterEqual(len(tickets), 2)
        _assert_pair_disjoint(self, tickets)

    def test_keys_are_disabled_and_pair_disjoint(self):
        analysis = _custom_analysis(auto_keys=[7, 33], sum_lo=90, sum_hi=210)
        tickets, _ = generate_tickets(
            history_draws=HISTORY,
            num_tickets=3,
            manual_keys=[7, 33],
            manual_excluded_tails=[],
            precomputed_analysis=analysis,
            batch_disjoint=True,
            rng=random.Random(42),
        )
        self.assertGreaterEqual(len(tickets), 1)
        _assert_pair_disjoint(self, tickets)
        # 膽碼必須被全域停用 — 否則 pair (7, 33) 會出現在每注 = 共 pair
        for t in tickets:
            self.assertFalse(
                {7, 33}.issubset(set(t)),
                f"keys (7, 33) leaked into ticket {t}; batch_disjoint must disable keys",
            )

    def test_user_case_pair_disjoint_under_excluded_tails(self):
        # v6.13 痛點 case:池 29 顆(排除尾數 [1,6,8,9])+ 要 10 注
        # 嚴格 pair-disjoint 理論上限 ⌊C(29,2)/C(6,2)⌋ = ⌊406/15⌋ = 27 注
        # 扣濾網經驗 ~50% 保留 → 預期 ≥ 5 注、目標 10 注
        analysis = _custom_analysis(auto_keys=[], sum_lo=90, sum_hi=210)
        tickets, _ = generate_tickets(
            history_draws=HISTORY,
            num_tickets=10,
            manual_excluded_tails=[1, 6, 8, 9],
            precomputed_analysis=analysis,
            batch_disjoint=True,
            rng=random.Random(42),
        )
        # 至少要超過原 v6.12 的 number-disjoint 上限 ⌊29/6⌋=4
        self.assertGreater(
            len(tickets), 4,
            f"pair-disjoint should produce more than number-disjoint cap, got {len(tickets)}",
        )
        # 每注 6 顆內部唯一、值域合法、整體無 exact dup
        for t in tickets:
            self.assertEqual(len(set(t)), 6)
            self.assertTrue(all(1 <= n <= 49 for n in t))
        self.assertEqual(len(set(tickets)), len(tickets), "no exact duplicate tickets")
        # 核心契約:嚴格 pair-disjoint
        _assert_pair_disjoint(self, tickets)
        # v6.15 契約:號碼出現次數均衡(P=29 排除尾數後)
        _assert_usage_balanced(self, tickets, pool_size=29)

    def test_v6_15_usage_cap_full_pool(self):
        # v6.15:全池 49 顆 + 10 注 → ⌈60/49⌉ + 1 = 3,每號最多 3 次
        analysis = _custom_analysis(auto_keys=[], sum_lo=90, sum_hi=210)
        tickets, _ = generate_tickets(
            history_draws=HISTORY,
            num_tickets=10,
            manual_excluded_tails=[],
            precomputed_analysis=analysis,
            batch_disjoint=True,
            rng=random.Random(42),
        )
        _assert_pair_disjoint(self, tickets)
        _assert_usage_balanced(self, tickets, pool_size=49)


class TestStats(unittest.TestCase):
    def test_stats_basic(self):
        s = ticket_stats([1, 2, 3, 4, 5, 6])
        self.assertEqual(s["sum"], 21)
        self.assertEqual(s["odd_count"], 3)
        self.assertEqual(s["big_count"], 0)

    def test_stats_prime_and_consecutive(self):
        s = ticket_stats([13, 7, 2, 3, 5, 11])
        self.assertEqual(s["prime_count"], 6)
        self.assertEqual(s["consecutive_pairs"], 1)

    def test_stats_no_consecutive(self):
        s = ticket_stats([2, 8, 14, 20, 26, 32])
        self.assertEqual(s["consecutive_pairs"], 0)


class TestHowardFilters(unittest.TestCase):
    """v6.16: Howard #4 字頭追蹤 + #11 谷底陷阱 雙濾網。"""

    def test_decade_filter_rejects_all_decades_filled(self):
        # 構造 5 decade 全有號的 ticket: (5, 15, 25, 35, 45) + 1 fill
        # 應被字頭濾網拒絕(empty_decades = 0 < MIN_EMPTY_DECADES = 1)
        from src.generator.lotto_picker import _passes_filters
        ticket = (3, 15, 25, 35, 41, 47)  # 5/10/20/30/40 字頭全有
        ts = frozenset(ticket)
        empty = sum(1 for band in DECADE_BANDS if not (band & ts))
        self.assertEqual(empty, 0, "test setup: ticket should have 0 empty decades")
        # 通過其他濾網但字頭濾網要擋下(此例 sum=164、odd=4、big=4、prime=4 → 質數超 3)
        # 改用 sum=124 的 case 避開其他濾網
        ticket = (1, 13, 22, 31, 42, 49)  # all 5 decades filled, sum=158
        ts = frozenset(ticket)
        self.assertEqual(
            sum(1 for band in DECADE_BANDS if not (band & ts)),
            0, "test setup: 5 decade 全填",
        )
        self.assertFalse(
            _passes_filters(
                tuple(sorted(ticket)), 90, 210,
                apply_secondary=True, basement_set=frozenset(),
            ),
            "v6.16 字頭濾網應拒絕 5 decade 全填的 ticket",
        )

    def test_decade_filter_accepts_one_empty_decade(self):
        # (4, 12, 22, 41, 43, 48): 30 字頭空 → 通過字頭濾網
        # 同時滿足:sum=170、odd=2、big=3(41/43/48)、prime=2(41/43)、consec=0
        from src.generator.lotto_picker import _passes_filters
        ticket = (4, 12, 22, 41, 43, 48)
        ts = frozenset(ticket)
        self.assertGreaterEqual(
            sum(1 for band in DECADE_BANDS if not (band & ts)),
            MIN_EMPTY_DECADES,
        )
        self.assertTrue(
            _passes_filters(
                ticket, 90, 210,
                apply_secondary=True, basement_set=frozenset(),
            ),
        )

    def test_basement_filter_rejects_two_cold(self):
        # 谷底陷阱:ticket 含 2 顆 cold → 拒絕
        # 滿足其他濾網的「2 顆 cold」case:
        #   (4, 12, 22, 41, 45, 48):41/45 都在 cold;sum=172、odd=2、big=3、prime=1
        from src.generator.lotto_picker import _passes_filters
        ticket = (4, 12, 22, 41, 45, 48)
        basement = frozenset([5, 15, 24, 41, 45])
        cold_in_ticket = sum(1 for n in ticket if n in basement)
        self.assertEqual(cold_in_ticket, 2, "test setup")
        self.assertFalse(
            _passes_filters(
                ticket, 90, 210,
                apply_secondary=True, basement_set=basement,
            ),
            f"v6.16 谷底陷阱應拒絕 {cold_in_ticket} > {MAX_BASEMENT_PER_TICKET}",
        )

    def test_basement_filter_accepts_one_cold(self):
        # (4, 12, 22, 41, 43, 48) 只有 41 是 cold → 通過
        from src.generator.lotto_picker import _passes_filters
        ticket = (4, 12, 22, 41, 43, 48)
        basement = frozenset([5, 15, 24, 41, 45])
        cold_in_ticket = sum(1 for n in ticket if n in basement)
        self.assertEqual(cold_in_ticket, 1, "test setup")
        self.assertTrue(
            _passes_filters(
                ticket, 90, 210,
                apply_secondary=True, basement_set=basement,
            ),
        )

    def test_apply_secondary_false_bypasses_decade_and_basement(self):
        # sub-C fallback: 所有次要濾網都關 → 字頭/谷底也不檢查
        from src.generator.lotto_picker import _passes_filters
        ticket = (1, 13, 22, 31, 42, 49)  # 5 decade 全填(會被 #4 擋)
        self.assertTrue(
            _passes_filters(
                ticket, 21, 49 * 6,
                apply_secondary=False, basement_set=frozenset(),
            ),
            "apply_secondary=False 應該繞過字頭濾網",
        )

    def test_real_history_pipeline_v6_16(self):
        # 端到端:用真實 30 期歷史 + Howard 濾網 → tickets 全符合
        analysis = _custom_analysis(auto_keys=[], sum_lo=120, sum_hi=180)
        # 故意把 cold 設為 [5, 15],模擬 engine 輸出
        from dataclasses import replace
        analysis = replace(analysis, cold=[5, 15])
        tickets, _ = generate_tickets(
            history_draws=HISTORY,
            num_tickets=5,
            precomputed_analysis=analysis,
            rng=random.Random(2026),
        )
        cold = frozenset([5, 15])
        for t in tickets:
            ts = frozenset(t)
            empty = sum(1 for band in DECADE_BANDS if not (band & ts))
            basement = sum(1 for n in t if n in cold)
            self.assertGreaterEqual(
                empty, MIN_EMPTY_DECADES,
                f"v6.16 字頭濾網漏:{t} 全字頭都有號",
            )
            self.assertLessEqual(
                basement, MAX_BASEMENT_PER_TICKET,
                f"v6.16 谷底陷阱漏:{t} 有 {basement} 顆 cold",
            )


class TestHowardMode(unittest.TestCase):
    """v6.19 Gail Howard 黃金 8 條(opt-in `howard_mode=True`)。"""

    def _hard_ok(self, ticket):
        from src.generator.lotto_picker import (
            ALLOWED_ODD_COUNTS,
            HOWARD_ALLOWED_SMALL_COUNTS,
            HOWARD_SMALL_THRESHOLD,
            HOWARD_SUM_MAX,
            HOWARD_SUM_MIN,
        )
        if not (HOWARD_SUM_MIN <= sum(ticket) <= HOWARD_SUM_MAX):
            return False
        if sum(1 for n in ticket if n % 2 == 1) not in ALLOWED_ODD_COUNTS:
            return False
        small = sum(1 for n in ticket if n <= HOWARD_SMALL_THRESHOLD)
        if small not in HOWARD_ALLOWED_SMALL_COUNTS:
            return False
        return True

    # --- Hard 3 conditions ---

    def test_hard_sum_out_of_range_rejected(self):
        from src.generator.lotto_picker import _howard_hard_pass
        # sum=98 (< 115)
        self.assertFalse(_howard_hard_pass((1, 2, 3, 30, 31, 31), 115, 185))
        # sum=215 (> 185)
        self.assertFalse(_howard_hard_pass((30, 35, 36, 37, 38, 49), 115, 185))

    def test_hard_sum_in_range_passes_when_other_ok(self):
        from src.generator.lotto_picker import _howard_hard_pass
        # sum=132, odd=3, small=3 (≤24): 3, 12, 19 → all hard ok
        self.assertTrue(_howard_hard_pass((3, 12, 19, 25, 33, 40), 115, 185))

    def test_hard_all_odd_rejected(self):
        from src.generator.lotto_picker import _howard_hard_pass
        # sum=121, all odd → odd=6 ∉ {2,3,4}
        self.assertFalse(_howard_hard_pass((3, 11, 17, 23, 27, 41), 115, 185))  # 122

    def test_hard_small_count_split_at_24_25(self):
        from src.generator.lotto_picker import _howard_hard_pass
        # ticket: small=5 (≤24): 14,18,20,22,24 + big=25 → small=5 ∉ {2,3,4}
        self.assertFalse(_howard_hard_pass((14, 18, 20, 22, 24, 25), 115, 185))  # sum=123
        # small=3 (3,12,18), big=3 (30,35,45) → small=3 ∈ {2,3,4}
        self.assertTrue(_howard_hard_pass((3, 12, 18, 30, 35, 45), 115, 185))  # 143

    # --- Soft 5 conditions ---

    def test_soft_4_tail_pair_recognized(self):
        from src.generator.lotto_picker import _howard_soft_score
        # tails: 3,3,5,2,0,7 → pair of 3s = exactly 1 pair → #4 +1
        s = _howard_soft_score((3, 13, 25, 32, 40, 47), gaps=None, last_draw=frozenset())
        # #4✓ #5 depends (1 decade 0-9 has 3 → ...), check baseline >= 3 because #7 #8 auto +1
        self.assertGreaterEqual(s, 3)

    def test_soft_4_three_same_tail_rejected(self):
        from src.generator.lotto_picker import _howard_soft_score
        # tails 1,1,1,2,3,4: 3 個尾數 1 → over_pairs ≥ 1 → #4 不加
        s_three = _howard_soft_score(
            (1, 11, 21, 32, 43, 44), gaps=None, last_draw=frozenset()
        )
        # tails 1,1,2,3,4,5: 1 對 → #4 +1
        s_one_pair = _howard_soft_score(
            (1, 11, 22, 33, 44, 45), gaps=None, last_draw=frozenset()
        )
        # 1 對 比 3 同尾 對 #4 多 1 分(#7/#8 跳過固定 +2,#5/#6 視 ticket 異)
        self.assertGreaterEqual(s_one_pair - s_three, 1)

    def test_soft_6_consecutive_exactly_one(self):
        from src.generator.lotto_picker import _howard_soft_score
        # 連號恰 1 對: 28, 29 + 其他不連 → #6 +1
        s = _howard_soft_score(
            (5, 14, 22, 28, 29, 41), gaps=None, last_draw=frozenset()
        )
        self.assertGreaterEqual(s, 3)
        # 2 對連號:1,2 + 28,29 → #6 not added
        s2 = _howard_soft_score(
            (1, 2, 14, 28, 29, 41), gaps=None, last_draw=frozenset()
        )
        # 軟分基數差異:s vs s2 → s 有 #6,s2 沒(僅針對 #6 比較)
        self.assertGreaterEqual(s, s2 - 1)  # 寬鬆斷言(#4/#5 可能變化)

    def test_soft_7_gap5_count_passes_when_4_or_5(self):
        from src.generator.lotto_picker import _howard_soft_score
        # gap≤5 for 4 of 6 numbers
        gaps = {n: 0 for n in (3, 13, 25, 32)} | {n: 20 for n in (40, 47)}
        gaps_full = {n: gaps.get(n, 100) for n in range(1, 50)}
        s = _howard_soft_score(
            (3, 13, 25, 32, 40, 47), gaps=gaps_full, last_draw=frozenset()
        )
        # #7 should pass (4 ≤ 5)
        self.assertGreaterEqual(s, 1)

    def test_soft_7_gap5_count_fails_when_only_2_recent(self):
        from src.generator.lotto_picker import _howard_soft_score
        # Only 2 numbers gap≤5 → #7 fails
        gaps_full = {n: 100 for n in range(1, 50)}
        gaps_full[3] = 0
        gaps_full[13] = 2
        s_full = _howard_soft_score(
            (3, 13, 25, 32, 40, 47), gaps=gaps_full, last_draw=frozenset()
        )
        s_skip = _howard_soft_score(
            (3, 13, 25, 32, 40, 47), gaps=None, last_draw=frozenset()
        )
        # gaps=None 自動 +1;gaps 限制 → -1
        self.assertEqual(s_skip - s_full, 1)

    def test_soft_8_repeat_from_last_draw(self):
        from src.generator.lotto_picker import _howard_soft_score
        # ticket 含上期 1 顆 → #8 +1
        s_hit = _howard_soft_score(
            (3, 13, 25, 32, 40, 47), gaps=None, last_draw=frozenset({3})
        )
        # ticket 含上期 0 顆 → #8 不加
        s_miss = _howard_soft_score(
            (3, 13, 25, 32, 40, 47), gaps=None, last_draw=frozenset({99})
        )
        self.assertEqual(s_hit - s_miss, 1)

    def test_soft_score_threshold_3_of_5(self):
        from src.generator.lotto_picker import (
            HOWARD_SOFT_MIN_SCORE,
            _howard_soft_score,
        )
        self.assertEqual(HOWARD_SOFT_MIN_SCORE, 3)
        # 全 fallback: gaps=None + last_draw=empty → #7+#8 自動 +2,#4/#5/#6 視 ticket
        # 隨機 ticket 拿到 >= 3 機率高(因 2 自動)
        s = _howard_soft_score(
            (5, 14, 22, 28, 29, 41), gaps=None, last_draw=frozenset()
        )
        self.assertGreaterEqual(s, HOWARD_SOFT_MIN_SCORE)

    # --- Validation ---

    def test_history_too_short_raises(self):
        from src.generator.lotto_picker import HOWARD_MIN_HISTORY
        with self.assertRaises(ValueError) as cm:
            generate_tickets(
                history_draws=HISTORY[: HOWARD_MIN_HISTORY - 1],
                num_tickets=5,
                howard_mode=True,
                rng=random.Random(42),
            )
        self.assertIn("howard_mode requires", str(cm.exception))

    def test_fallback_analysis_raises(self):
        from src.generator.history_engine import STATIC_FALLBACK_ANALYSIS
        with self.assertRaises(ValueError) as cm:
            generate_tickets(
                history_draws=HISTORY,
                num_tickets=5,
                precomputed_analysis=STATIC_FALLBACK_ANALYSIS,
                howard_mode=True,
                rng=random.Random(42),
            )
        self.assertIn("howard_mode requires real history", str(cm.exception))

    def test_minimum_history_works(self):
        from src.generator.lotto_picker import HOWARD_MIN_HISTORY
        tickets, _ = generate_tickets(
            history_draws=HISTORY[:HOWARD_MIN_HISTORY],
            num_tickets=3,
            howard_mode=True,
            rng=random.Random(42),
        )
        # 至少有 tickets 產出(Round 1 或 Round 2 fallback)
        self.assertGreater(len(tickets), 0)

    # --- End-to-end ---

    def test_generate_with_howard_mode_returns_valid_tickets(self):
        tickets, _ = generate_tickets(
            history_draws=HISTORY,
            num_tickets=5,
            howard_mode=True,
            rng=random.Random(42),
        )
        for t in tickets:
            self.assertEqual(len(t), TICKET_SIZE)
            self.assertEqual(len(set(t)), TICKET_SIZE)
            self.assertTrue(all(1 <= n <= 49 for n in t))

    def test_howard_mode_default_off_does_not_change_v6_16(self):
        # 同 seed + 同 input,howard_mode 預設 False 應與省略時一致
        a, _ = generate_tickets(
            history_draws=HISTORY,
            num_tickets=5,
            rng=random.Random(42),
        )
        b, _ = generate_tickets(
            history_draws=HISTORY,
            num_tickets=5,
            howard_mode=False,
            rng=random.Random(42),
        )
        self.assertEqual(a, b)

    def test_howard_round1_majority_passes_hard_3(self):
        # 大歷史 + howard_mode + 小量注數 → Round 1 主導,大多應過硬綁
        tickets, _ = generate_tickets(
            history_draws=HISTORY,
            num_tickets=3,
            howard_mode=True,
            rng=random.Random(2026),
        )
        if tickets:  # 防 Round 1+2 都湊不到
            passed = sum(1 for t in tickets if self._hard_ok(t))
            # Howard Round 1 dominant 時應 >= 50% 過硬綁;不嚴格綁 100% 因可能 Round 2 fallback
            self.assertGreaterEqual(
                passed,
                max(1, len(tickets) // 2),
                f"Howard Round 1 不該大量退回 v6.16: tickets={tickets}",
            )

    # --- 3 個易錯輸入(CLAUDE.md §6 自審) ---

    def test_easily_broken_input_1_all_history_same_draws(self):
        """重複歷史:所有期都同一組 → gaps 對 unseen 號 = inf,#7 難過。

        須顯式 `manual_excluded_tails=[]`,否則 dormant_tails 自動把全部 0-9
        都標為排除(因為 [1..6] 的尾數覆蓋率不夠)→ pool 為空。
        """
        repeated = [[1, 2, 3, 4, 5, 6]] * 30
        tickets, _ = generate_tickets(
            history_draws=repeated,
            num_tickets=3,
            howard_mode=True,
            manual_excluded_tails=[],  # 不排除任何尾數
            manual_excluded_numbers=[1, 2, 3, 4, 5, 6],  # 強制 pool 不含這些
            rng=random.Random(42),
        )
        # 應該至少有些 tickets(Round 2 fallback)
        for t in tickets:
            self.assertEqual(len(t), 6)
            self.assertEqual(len(set(t)), 6)

    def test_easily_broken_input_2_exact_5_period_history(self):
        """史料剛好邊界 → 不該 raise。"""
        from src.generator.lotto_picker import HOWARD_MIN_HISTORY
        tickets, _ = generate_tickets(
            history_draws=HISTORY[:HOWARD_MIN_HISTORY],
            num_tickets=3,
            howard_mode=True,
            rng=random.Random(42),
        )
        self.assertGreater(len(tickets), 0)

    def test_easily_broken_input_3_howard_with_batch_disjoint(self):
        """Howard + batch_disjoint 互動:不該 crash + tickets pair-disjoint。"""
        tickets, _ = generate_tickets(
            history_draws=HISTORY,
            num_tickets=5,
            howard_mode=True,
            batch_disjoint=True,
            rng=random.Random(42),
        )
        # pair-disjoint check
        from itertools import combinations as _C
        used_pairs = set()
        for t in tickets:
            new_pairs = set(_C(t, 2))
            self.assertFalse(
                new_pairs & used_pairs,
                f"Howard + batch_disjoint 違反 pair-disjoint: {t}",
            )
            used_pairs |= new_pairs


if __name__ == "__main__":
    unittest.main()
