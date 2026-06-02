"""威力彩 engine 單元測試 — 第一區 Z-Score + 第二區 gap pick。"""

from __future__ import annotations

import random
import unittest

from src.generator.powerball_engine import (
    BONUS_POOL_MAX,
    BONUS_POOL_MIN,
    MAIN_POOL_MAX,
    MAIN_POOL_MIN,
    STATIC_FALLBACK_ANALYSIS,
    PowerballAnalysis,
    analyze,
)


def _synthetic_draws(n: int = 30, seed: int = 42) -> list[list[int]]:
    rng = random.Random(seed)
    return [
        sorted(rng.sample(range(MAIN_POOL_MIN, MAIN_POOL_MAX + 1), 6))
        for _ in range(n)
    ]


def _synthetic_specials(n: int = 30, seed: int = 43) -> list[int]:
    rng = random.Random(seed)
    return [rng.randint(BONUS_POOL_MIN, BONUS_POOL_MAX) for _ in range(n)]


class TestAnalyzeBasics(unittest.TestCase):

    def test_returns_powerball_analysis_with_required_fields(self):
        draws = _synthetic_draws()
        specials = _synthetic_specials()
        a = analyze(draws, specials, rng=random.Random(1))
        self.assertIsInstance(a, PowerballAnalysis)
        self.assertFalse(a.is_fallback)
        # 第一區
        self.assertEqual(
            set(a.hot) | set(a.warm) | set(a.cold),
            set(range(MAIN_POOL_MIN, MAIN_POOL_MAX + 1)),
        )
        self.assertGreaterEqual(a.sum_min_dynamic, 80)
        self.assertLessEqual(a.sum_max_dynamic, 154)
        # 第二區
        self.assertIn(a.bonus_auto_pick, range(BONUS_POOL_MIN, BONUS_POOL_MAX + 1))
        self.assertEqual(
            set(a.bonus_hot) | set(a.bonus_cold),
            set(range(BONUS_POOL_MIN, BONUS_POOL_MAX + 1)),
        )

    def test_empty_draws_raises(self):
        with self.assertRaises(ValueError):
            analyze([], [], rng=random.Random(1))

    def test_negative_sigma_raises(self):
        with self.assertRaises(ValueError):
            analyze(_synthetic_draws(), _synthetic_specials(),
                    hot_sigma_factor=-0.1, rng=random.Random(1))

    def test_static_fallback_is_marked(self):
        self.assertTrue(STATIC_FALLBACK_ANALYSIS.is_fallback)
        self.assertEqual(STATIC_FALLBACK_ANALYSIS.sum_min_dynamic, 90)
        self.assertEqual(STATIC_FALLBACK_ANALYSIS.sum_max_dynamic, 144)


class TestZScoreLayering(unittest.TestCase):

    def test_hot_threshold_floor(self):
        draws = _synthetic_draws()
        a = analyze(draws, [], rng=random.Random(1))
        # hot_threshold floor 是 2.0
        self.assertGreaterEqual(a.hot_threshold, 2.0)

    def test_pool_partition_disjoint(self):
        draws = _synthetic_draws()
        a = analyze(draws, [], rng=random.Random(1))
        for n in range(MAIN_POOL_MIN, MAIN_POOL_MAX + 1):
            buckets = sum([n in a.hot, n in a.warm, n in a.cold])
            self.assertEqual(buckets, 1, f"number {n} in {buckets} buckets")


class TestBonusAnalyze(unittest.TestCase):

    def test_empty_specials_returns_full_hot_fallback(self):
        a = analyze(_synthetic_draws(), [], rng=random.Random(1))
        self.assertEqual(
            sorted(a.bonus_hot),
            list(range(BONUS_POOL_MIN, BONUS_POOL_MAX + 1)),
        )
        self.assertIn(a.bonus_auto_pick,
                      range(BONUS_POOL_MIN, BONUS_POOL_MAX + 1))

    def test_recent_number_is_hot(self):
        # specials newest-first: 5 出現在最近一期
        specials = [5, 1, 2, 3, 4, 6, 7, 8, 1, 2]
        a = analyze(_synthetic_draws(), specials, rng=random.Random(1))
        self.assertEqual(a.bonus_gaps[5], 0)
        self.assertIn(5, a.bonus_hot)

    def test_never_seen_is_cold(self):
        # 6 從未出現 → gap = len(specials) → 高於 mean → cold
        specials = [1, 2, 3, 4, 5, 7, 8, 1, 2, 3]
        a = analyze(_synthetic_draws(), specials, rng=random.Random(1))
        self.assertIn(6, a.bonus_cold)
        self.assertNotIn(6, a.bonus_hot)


class TestAutoKeys(unittest.TestCase):

    def test_auto_keys_within_pool(self):
        a = analyze(_synthetic_draws(), _synthetic_specials(), rng=random.Random(1))
        for k in a.auto_keys:
            self.assertTrue(MAIN_POOL_MIN <= k <= MAIN_POOL_MAX)
        self.assertLessEqual(len(a.auto_keys), 2)


if __name__ == "__main__":
    unittest.main()
