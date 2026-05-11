"""Unit tests for history_engine (v3.0 Phase 1)."""

import random
import unittest

from src.generator.history_engine import (
    DEFAULTS,
    HistoryAnalysis,
    POOL_MAX,
    POOL_MIN,
    analyze,
)


def _all_pool(): return set(range(POOL_MIN, POOL_MAX + 1))


class TestGapLayering(unittest.TestCase):
    def test_hot_means_appearing_in_recent(self):
        # newest first; number 7 appears in latest → gap 0
        draws = [
            [7, 12, 18, 25, 33, 42],
            [1, 2, 3, 4, 5, 6],
            [10, 11, 13, 14, 15, 16],
        ]
        a = analyze(draws, rng=random.Random(1))
        self.assertIn(7, a.hot)
        self.assertIn(12, a.hot)

    def test_cold_means_never_seen(self):
        # 49 never appears anywhere → gap = len(draws) > warm_max → cold
        draws = [[1, 2, 3, 4, 5, 6]] * 20
        a = analyze(draws, hot_max_gap=2, warm_max_gap=14, rng=random.Random(1))
        self.assertIn(49, a.cold)

    def test_partition_covers_all(self):
        draws = [[1, 2, 3, 4, 5, 6], [10, 20, 30, 40, 41, 42]]
        a = analyze(draws, rng=random.Random(1))
        union = set(a.hot) | set(a.warm) | set(a.cold)
        self.assertEqual(union, _all_pool())
        # no overlap
        self.assertEqual(
            len(a.hot) + len(a.warm) + len(a.cold), POOL_MAX - POOL_MIN + 1
        )


class TestTailExclusion(unittest.TestCase):
    def test_overheated_tail_detected(self):
        # tail 7 appears 4 times in last 3 draws (each draw has 7, 17, 27, 37)
        draws = [
            [7, 17, 27, 37, 1, 2],
            [7, 17, 27, 37, 3, 4],
            [7, 17, 27, 37, 5, 6],
        ]
        a = analyze(
            draws, overheat_recent_periods=3, overheat_min_count=4,
            rng=random.Random(1),
        )
        self.assertIn(7, a.overheated_tails)
        self.assertIn(7, a.exclude_tails)

    def test_dormant_tail_detected(self):
        # build 12 draws all containing only numbers with tail 0 / 1 / 2 / 3 / 4
        draws = [[1, 2, 3, 4, 10, 11]] * 12
        a = analyze(draws, dormant_periods=10, rng=random.Random(1))
        # tails 5,6,7,8,9 never appear → all dormant
        for t in (5, 6, 7, 8, 9):
            self.assertIn(t, a.dormant_tails)
            self.assertIn(t, a.exclude_tails)


class TestAutoKeys(unittest.TestCase):
    def test_one_hot_one_cold(self):
        draws = [
            [1, 2, 3, 4, 5, 6],           # hot pool: 1-6 (after 1 draw)
            [40, 41, 42, 43, 44, 45],
        ] + [[10, 11, 12, 13, 14, 15]] * 18  # 20 draws total
        a = analyze(draws, rng=random.Random(7))
        self.assertEqual(len(a.auto_keys), 2)
        # at least one must be in hot, one in cold
        in_hot = any(k in a.hot for k in a.auto_keys)
        in_cold = any(k in a.cold for k in a.auto_keys)
        self.assertTrue(in_hot)
        self.assertTrue(in_cold)


class TestValidation(unittest.TestCase):
    def test_empty_draws_rejected(self):
        with self.assertRaises(ValueError):
            analyze([], rng=random.Random(1))

    def test_bad_thresholds_rejected(self):
        draws = [[1, 2, 3, 4, 5, 6]]
        with self.assertRaises(ValueError):
            analyze(draws, hot_max_gap=10, warm_max_gap=5, rng=random.Random(1))


class TestReproducibility(unittest.TestCase):
    def test_same_seed_same_keys(self):
        draws = [[1, 2, 3, 4, 5, 6], [40, 41, 42, 43, 44, 45]] * 10
        a1 = analyze(draws, rng=random.Random(99))
        a2 = analyze(draws, rng=random.Random(99))
        self.assertEqual(a1.auto_keys, a2.auto_keys)


if __name__ == "__main__":
    unittest.main()
