"""Unit tests for history_engine (v5.0 — Z-Score + dynamic sum)."""

import random
import unittest

from src.generator.history_engine import (
    POOL_MAX,
    POOL_MIN,
    STATIC_FALLBACK_ANALYSIS,
    STATIC_SUM_MAX,
    STATIC_SUM_MIN,
    analyze,
)


def _all_pool(): return set(range(POOL_MIN, POOL_MAX + 1))


class TestZScoreLayering(unittest.TestCase):
    def test_partition_covers_all(self):
        draws = [[1, 2, 3, 4, 5, 6], [10, 20, 30, 40, 41, 42]]
        a = analyze(draws, rng=random.Random(1))
        self.assertEqual(set(a.hot) | set(a.warm) | set(a.cold), _all_pool())
        self.assertEqual(
            len(a.hot) + len(a.warm) + len(a.cold), POOL_MAX - POOL_MIN + 1
        )

    def test_thresholds_use_zscore(self):
        # 30 draws of identical [1..6] → 1-6 gap 0, others gap 30
        draws = [[1, 2, 3, 4, 5, 6]] * 30
        a = analyze(draws, hot_sigma_factor=0.5, cold_sigma_factor=1.5,
                    rng=random.Random(1))
        for n in (1, 2, 3, 4, 5, 6):
            self.assertIn(n, a.hot)
        # never-seen numbers must NOT be hot (they're warm/cold by definition)
        self.assertNotIn(49, a.hot)
        # mean / std exposed for transparency
        self.assertGreater(a.gap_mean, 0)
        self.assertGreater(a.gap_std, 0)

    def test_hot_threshold_floor(self):
        # If σ is huge, μ - 0.5σ could go negative; ensure floor of 2
        draws = [[1, 2, 3, 4, 5, 6]] + [[10, 20, 30, 40, 41, 42]] * 30
        a = analyze(draws, hot_threshold_floor=2, rng=random.Random(1))
        self.assertGreaterEqual(a.hot_threshold, 2.0)


class TestDynamicSumRange(unittest.TestCase):
    def test_sma_centered(self):
        # 10 draws all summing to ~150 → SMA ≈ 150 → range [120, 180]
        draws = [[10, 20, 25, 30, 30, 35]] * 10  # sum = 150
        a = analyze(draws, sum_sma_window=10, sum_range_pad=30,
                    rng=random.Random(1))
        self.assertEqual(a.sum_min_dynamic, 120)
        self.assertEqual(a.sum_max_dynamic, 180)

    def test_sum_clamp_lo(self):
        # very low sum draws → SMA ≈ 21 → lo would be -9; clamp to 90
        draws = [[1, 2, 3, 4, 5, 6]] * 10
        a = analyze(draws, sum_sma_window=10, sum_range_pad=30,
                    rng=random.Random(1))
        self.assertEqual(a.sum_min_dynamic, 90)

    def test_sum_clamp_hi(self):
        # very high sum draws → SMA huge → hi clamped to 210
        draws = [[44, 45, 46, 47, 48, 49]] * 10  # sum = 279
        a = analyze(draws, sum_sma_window=10, sum_range_pad=30,
                    rng=random.Random(1))
        self.assertEqual(a.sum_max_dynamic, 210)


class TestTailExclusion(unittest.TestCase):
    def test_overheated(self):
        draws = [
            [7, 17, 27, 37, 1, 2],
            [7, 17, 27, 37, 3, 4],
            [7, 17, 27, 37, 5, 6],
        ]
        a = analyze(draws, overheat_recent_periods=3, overheat_min_count=4,
                    rng=random.Random(1))
        self.assertIn(7, a.overheated_tails)
        self.assertIn(7, a.exclude_tails)

    def test_dormant(self):
        draws = [[1, 2, 3, 4, 10, 11]] * 12
        a = analyze(draws, dormant_periods=10, rng=random.Random(1))
        for t in (5, 6, 7, 8, 9):
            self.assertIn(t, a.dormant_tails)
            self.assertIn(t, a.exclude_tails)

    def test_default_overheat_threshold_triggers_on_realistic_concentration(self):
        # v6.10: 新 default `overheat_min_count=3` 應在「單尾數 3 期出 3 次」時觸發。
        # 對應 README/UI 的「適度集中即觸發」設計目標。
        draws = [
            [3, 13, 23, 1, 2, 4],   # tail 3 出 3 次
            [33, 5, 6, 7, 8, 9],    # tail 3 再出 1 次 → 累計 4(其中 ≥ 3)
            [10, 11, 12, 14, 15, 16],
        ]
        a = analyze(draws, rng=random.Random(1))  # 用 DEFAULTS
        self.assertIn(3, a.overheated_tails,
                      f"new default should flag tail=3 as overheated, got {a.overheated_tails}")


class TestAutoKeys(unittest.TestCase):
    def test_one_hot_one_cold(self):
        # 50-draw history with sharp bimodal gaps; lower cold_sigma so a
        # plain bimodal distribution still produces non-empty cold
        draws = [[1, 2, 3, 4, 5, 6]] + [[10, 20, 30, 40, 41, 42]] * 49
        a = analyze(draws, cold_sigma_factor=0.5, rng=random.Random(7))
        self.assertGreaterEqual(len(a.auto_keys), 2)
        self.assertTrue(any(k in a.hot for k in a.auto_keys))
        self.assertTrue(any(k in a.cold for k in a.auto_keys))

    def test_single_key_when_cold_empty(self):
        # uniform history → cold may be empty under default 1.5σ
        draws = [[1, 2, 3, 4, 5, 6]] * 10
        a = analyze(draws, rng=random.Random(7))
        # at minimum 1 key (hot side); never zero
        self.assertGreaterEqual(len(a.auto_keys), 1)


class TestValidation(unittest.TestCase):
    def test_empty_rejected(self):
        with self.assertRaises(ValueError):
            analyze([], rng=random.Random(1))

    def test_single_row_rejected(self):
        # A2 (v6.9) — single-row history degenerates to zero variance;
        # explicit ValueError prevents silent all-hot/all-cold output.
        with self.assertRaises(ValueError) as ctx:
            analyze([[1, 2, 3, 4, 5, 6]], rng=random.Random(1))
        self.assertIn(">= 2 rows", str(ctx.exception))

    def test_two_rows_accepted(self):
        # >= 2 rows is the minimum for meaningful Z-score
        a = analyze(
            [[1, 2, 3, 4, 5, 6], [10, 11, 12, 13, 14, 15]],
            rng=random.Random(1),
        )
        self.assertFalse(a.is_fallback)

    def test_negative_sigma_rejected(self):
        draws = [[1, 2, 3, 4, 5, 6], [10, 11, 12, 13, 14, 15]]
        with self.assertRaises(ValueError):
            analyze(draws, hot_sigma_factor=-0.5, rng=random.Random(1))

    def test_inverted_clamp_rejected(self):
        draws = [[1, 2, 3, 4, 5, 6], [10, 11, 12, 13, 14, 15]]
        with self.assertRaises(ValueError):
            analyze(draws, sum_clamp_lo=200, sum_clamp_hi=100,
                    rng=random.Random(1))


class TestStaticFallback(unittest.TestCase):
    def test_fallback_constant_marked(self):
        self.assertTrue(STATIC_FALLBACK_ANALYSIS.is_fallback)
        self.assertEqual(STATIC_FALLBACK_ANALYSIS.sum_min_dynamic, STATIC_SUM_MIN)
        self.assertEqual(STATIC_FALLBACK_ANALYSIS.sum_max_dynamic, STATIC_SUM_MAX)
        self.assertEqual(STATIC_FALLBACK_ANALYSIS.exclude_tails, [])

    def test_normal_analysis_not_fallback(self):
        # >= 2 draws required since v6.9 single-row guard
        a = analyze(
            [[1, 2, 3, 4, 5, 6], [40, 41, 42, 43, 44, 45]],
            rng=random.Random(1),
        )
        self.assertFalse(a.is_fallback)


class TestReproducibility(unittest.TestCase):
    def test_same_seed_same_keys(self):
        draws = [[1, 2, 3, 4, 5, 6], [40, 41, 42, 43, 44, 45]] * 10
        a1 = analyze(draws, rng=random.Random(99))
        a2 = analyze(draws, rng=random.Random(99))
        self.assertEqual(a1.auto_keys, a2.auto_keys)


if __name__ == "__main__":
    unittest.main()
