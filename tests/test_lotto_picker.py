"""Unit tests for the v3.0 dynamic Lotto picker."""

import random
import unittest

from src.generator.history_engine import HistoryAnalysis
from src.generator.lotto_picker import (
    ALLOWED_ODD_COUNTS,
    BIG_THRESHOLD,
    MAX_CONSECUTIVE_PAIRS,
    MAX_PRIME_COUNT,
    MIN_BIG_COUNT,
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


class TestBatchDisjoint(unittest.TestCase):
    """批次推薦模式：除膽碼外，注間號碼完全不重複。"""

    def test_no_keys_all_numbers_disjoint(self):
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
        for i in range(len(tickets)):
            for j in range(i + 1, len(tickets)):
                self.assertFalse(set(tickets[i]) & set(tickets[j]))

    def test_two_keys_allowed_and_only_drag_is_disjoint(self):
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
        for t in tickets:
            self.assertIn(7, t)
            self.assertIn(33, t)
        for i in range(len(tickets)):
            for j in range(i + 1, len(tickets)):
                drag_i = set(tickets[i]) - {7, 33}
                drag_j = set(tickets[j]) - {7, 33}
                self.assertFalse(drag_i & drag_j)


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


if __name__ == "__main__":
    unittest.main()
