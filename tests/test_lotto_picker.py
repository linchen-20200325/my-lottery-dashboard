"""Unit tests for the 4-phase Lotto picker. Stdlib only (unittest)."""

import random
import unittest

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
    prime_count = sum(1 for n in t if n in PRIMES_SET)
    if not (MIN_PRIME_COUNT <= prime_count <= MAX_PRIME_COUNT):
        return False
    sorted_t = sorted(t)
    consec = sum(
        1 for i in range(len(sorted_t) - 1) if sorted_t[i + 1] - sorted_t[i] == 1
    )
    if consec > MAX_CONSECUTIVE_PAIRS:
        return False
    return True


class TestHappyPath(unittest.TestCase):
    def test_generates_filtered_tickets(self):
        tickets = generate_tickets(
            previous_draw=[5, 12, 18, 25, 33, 42],
            exclude_tails=[],
            key_nums=[7, 17, 27],
            num_tickets=5,
            rng=random.Random(42),
        )
        self.assertEqual(len(tickets), 5)
        for t in tickets:
            self.assertTrue(_is_valid_ticket(t), f"invalid ticket: {t}")
            self.assertIn(7, t)
            self.assertIn(17, t)
            self.assertIn(27, t)

    def test_excluded_tails_respected(self):
        tickets = generate_tickets(
            previous_draw=[1, 2, 3, 4, 5, 6],
            exclude_tails=[0, 9],  # exclude 9,10,19,20,29,30,39,40,49
            key_nums=[33, 35],
            num_tickets=10,
            rng=random.Random(1),
        )
        excluded = {n for n in range(1, 50) if n % 10 in {0, 9}}
        for t in tickets:
            self.assertFalse(set(t) & excluded, f"tail leak in {t}")

    def test_seed_is_reproducible(self):
        kw = dict(
            previous_draw=[5, 12, 18, 25, 33, 42],
            exclude_tails=[],
            key_nums=[7, 17, 27],
            num_tickets=5,
        )
        a = generate_tickets(**kw, rng=random.Random(123))
        b = generate_tickets(**kw, rng=random.Random(123))
        self.assertEqual(a, b)


class TestEdgeCases(unittest.TestCase):
    def test_previous_draw_wrong_length(self):
        with self.assertRaises(ValueError):
            generate_tickets(
                previous_draw=[1, 2, 3],
                exclude_tails=[],
                key_nums=[7],
                num_tickets=1,
            )

    def test_previous_draw_out_of_range(self):
        with self.assertRaises(ValueError):
            generate_tickets(
                previous_draw=[1, 2, 3, 4, 5, 50],
                exclude_tails=[],
                key_nums=[7],
                num_tickets=1,
            )

    def test_key_nums_too_many(self):
        with self.assertRaises(ValueError):
            generate_tickets(
                previous_draw=[5, 12, 18, 25, 33, 42],
                exclude_tails=[],
                key_nums=[1, 2, 3, 4, 5, 6],
                num_tickets=1,
            )

    def test_key_nums_zero(self):
        with self.assertRaises(ValueError):
            generate_tickets(
                previous_draw=[5, 12, 18, 25, 33, 42],
                exclude_tails=[],
                key_nums=[],
                num_tickets=1,
            )

    def test_insufficient_drag(self):
        with self.assertRaises(ValueError):
            generate_tickets(
                previous_draw=[5, 12, 18, 25, 33, 42],
                exclude_tails=[],
                key_nums=[7],
                drag_nums=[8, 9],
                num_tickets=1,
            )

    def test_invalid_num_tickets(self):
        with self.assertRaises(ValueError):
            generate_tickets(
                previous_draw=[5, 12, 18, 25, 33, 42],
                exclude_tails=[],
                key_nums=[7],
                num_tickets=0,
            )

    def test_duplicates_rejected(self):
        with self.assertRaises(ValueError):
            generate_tickets(
                previous_draw=[5, 5, 18, 25, 33, 42],
                exclude_tails=[],
                key_nums=[7],
                num_tickets=1,
            )

    def test_non_int_rejected(self):
        with self.assertRaises(ValueError):
            generate_tickets(
                previous_draw=[5, 12, 18, 25, 33, "42"],
                exclude_tails=[],
                key_nums=[7],
                num_tickets=1,
            )

    def test_returns_fewer_when_filters_too_strict(self):
        # Exclude tails 0..9 → drag pool is empty
        # We expect a ValueError before reaching shuffle/filters
        with self.assertRaises(ValueError):
            generate_tickets(
                previous_draw=[5, 12, 18, 25, 33, 42],
                exclude_tails=list(range(10)),
                key_nums=[7],
                num_tickets=5,
            )


class TestStats(unittest.TestCase):
    def test_stats_sum(self):
        s = ticket_stats([1, 2, 3, 4, 5, 6])
        self.assertEqual(s["sum"], 21)
        self.assertEqual(s["odd_count"], 3)
        self.assertEqual(s["even_count"], 3)
        self.assertEqual(s["big_count"], 0)
        self.assertEqual(s["small_count"], 6)

    def test_stats_prime_and_consecutive(self):
        # ticket {2,3,5,7,11,13}: all primes (6) ; pairs (2,3) only → 1
        s = ticket_stats([13, 7, 2, 3, 5, 11])
        self.assertEqual(s["prime_count"], 6)
        self.assertEqual(s["consecutive_pairs"], 1)

    def test_stats_no_consecutive(self):
        s = ticket_stats([2, 8, 14, 20, 26, 32])
        self.assertEqual(s["consecutive_pairs"], 0)


class TestNewFilters(unittest.TestCase):
    def test_all_tickets_pass_prime_bounds(self):
        tickets = generate_tickets(
            previous_draw=[5, 12, 18, 25, 33, 42],
            exclude_tails=[],
            key_nums=[7, 17, 27],
            num_tickets=10,
            rng=random.Random(2026),
        )
        for t in tickets:
            primes = sum(1 for n in t if n in PRIMES_SET)
            self.assertGreaterEqual(primes, MIN_PRIME_COUNT, f"too few primes: {t}")
            self.assertLessEqual(primes, MAX_PRIME_COUNT, f"too many primes: {t}")

    def test_all_tickets_respect_consecutive_cap(self):
        tickets = generate_tickets(
            previous_draw=[5, 12, 18, 25, 33, 42],
            exclude_tails=[],
            key_nums=[7, 17, 27],
            num_tickets=10,
            rng=random.Random(99),
        )
        for t in tickets:
            sorted_t = sorted(t)
            pairs = sum(
                1
                for i in range(len(sorted_t) - 1)
                if sorted_t[i + 1] - sorted_t[i] == 1
            )
            self.assertLessEqual(
                pairs, MAX_CONSECUTIVE_PAIRS, f"too many consecutive in {t}"
            )


if __name__ == "__main__":
    unittest.main()
