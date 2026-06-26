"""Unit tests for the v6.20 abbreviated wheel (4保3 covering)."""

import unittest
from itertools import combinations

from src.generator.abbreviated_wheel import (
    WHEEL_12_4_OF_4_3,
    WHEEL_GUARANTEE_P,
    WHEEL_GUARANTEE_T,
    WHEEL_SIZE,
    WHEEL_TICKET_COUNT,
    pick_abbreviated_wheel,
)


class TestWheelInvariant(unittest.TestCase):
    """4保3 數學不變量:暴搜 C(12,4)=495 個 4-subset。"""

    def test_constant_dimensions(self):
        self.assertEqual(len(WHEEL_12_4_OF_4_3), WHEEL_TICKET_COUNT)
        for line in WHEEL_12_4_OF_4_3:
            self.assertEqual(len(line), 6)
            self.assertEqual(len(set(line)), 6)
            self.assertTrue(all(0 <= i < WHEEL_SIZE for i in line))

    def test_4_in_4_guarantee_3_exhaustive(self):
        """For every 4-subset of {0..11}, ≥1 line has intersection ≥3."""
        blocks = [set(line) for line in WHEEL_12_4_OF_4_3]
        for t in combinations(range(WHEEL_SIZE), WHEEL_GUARANTEE_T):
            tset = set(t)
            best = max(len(b & tset) for b in blocks)
            self.assertGreaterEqual(
                best, WHEEL_GUARANTEE_P,
                f"4-subset {t} not covered: best intersection = {best}",
            )


class TestPickHappyPath(unittest.TestCase):
    def test_returns_8_tickets_size_6(self):
        pool = [3, 7, 11, 15, 19, 22, 27, 31, 36, 40, 44, 48]
        tickets = pick_abbreviated_wheel(pool)
        self.assertEqual(len(tickets), WHEEL_TICKET_COUNT)
        for t in tickets:
            self.assertEqual(len(t), 6)
            self.assertEqual(len(set(t)), 6)
            self.assertTrue(all(n in pool for n in t))
            self.assertEqual(list(t), sorted(t))

    def test_no_seed_deterministic(self):
        pool = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]
        a = pick_abbreviated_wheel(pool)
        b = pick_abbreviated_wheel(pool)
        self.assertEqual(a, b)

    def test_seed_reproducible(self):
        pool = [5, 10, 15, 20, 25, 30, 35, 40, 45, 1, 8, 17]
        a = pick_abbreviated_wheel(pool, seed=42)
        b = pick_abbreviated_wheel(pool, seed=42)
        self.assertEqual(a, b)

    def test_different_seeds_differ(self):
        pool = [1, 5, 9, 13, 17, 21, 25, 29, 33, 37, 41, 45]
        a = pick_abbreviated_wheel(pool, seed=1)
        b = pick_abbreviated_wheel(pool, seed=999)
        self.assertNotEqual(a, b)

    def test_4_in_4_guarantee_real_pool(self):
        """Pool 排序後,任挑 4 號模擬中獎,至少一注命中 ≥3。"""
        pool = sorted([2, 8, 13, 19, 24, 28, 33, 37, 41, 44, 47, 49])
        tickets = pick_abbreviated_wheel(pool)
        ticket_sets = [set(t) for t in tickets]
        for winning in combinations(pool, 4):
            best = max(len(set(winning) & ts) for ts in ticket_sets)
            self.assertGreaterEqual(
                best, 3, f"4-winning {winning} uncovered: best = {best}"
            )


class TestFailLoud(unittest.TestCase):
    """§1 Fail Loud:輸入違憲一律 raise。"""

    def test_too_few_raises(self):
        with self.assertRaises(ValueError) as cm:
            pick_abbreviated_wheel([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11])
        self.assertIn("12", str(cm.exception))

    def test_too_many_raises(self):
        with self.assertRaises(ValueError):
            pick_abbreviated_wheel(list(range(1, 14)))

    def test_duplicate_raises(self):
        with self.assertRaises(ValueError) as cm:
            pick_abbreviated_wheel([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 1])
        self.assertIn("duplicate", str(cm.exception).lower())

    def test_out_of_range_low_raises(self):
        with self.assertRaises(ValueError):
            pick_abbreviated_wheel([0, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12])

    def test_out_of_range_high_raises(self):
        with self.assertRaises(ValueError):
            pick_abbreviated_wheel([50, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12])

    def test_non_int_raises(self):
        with self.assertRaises(TypeError):
            pick_abbreviated_wheel([1.5, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12])

    def test_bool_rejected_as_int(self):
        """bool 是 int 子類,但語意上不該過(防 True/False 偽裝成 1/0)。"""
        with self.assertRaises(TypeError):
            pick_abbreviated_wheel([True, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12])

    def test_non_sequence_raises(self):
        with self.assertRaises(TypeError):
            pick_abbreviated_wheel(set(range(1, 13)))


class TestEdgeCases(unittest.TestCase):
    """3 個最易壞的輸入。"""

    def test_pool_at_boundaries(self):
        """池含 1 與 49 邊界值。"""
        pool = [1, 2, 3, 4, 5, 6, 7, 8, 9, 47, 48, 49]
        tickets = pick_abbreviated_wheel(pool)
        flat = {n for t in tickets for n in t}
        self.assertIn(1, flat)
        self.assertIn(49, flat)

    def test_pool_unsorted_input_canonicalized(self):
        """打亂順序輸入,不影響保證(內部會 sort)。"""
        pool_unsorted = [49, 1, 25, 13, 37, 7, 19, 31, 43, 4, 16, 28]
        pool_sorted = sorted(pool_unsorted)
        a = pick_abbreviated_wheel(pool_unsorted)
        b = pick_abbreviated_wheel(pool_sorted)
        self.assertEqual(a, b)

    def test_winning_at_pool_edges_still_covered(self):
        """中獎號全在池的「邊角」(最小+最大)— 易壞輸入。"""
        pool = sorted([1, 2, 3, 4, 25, 26, 27, 28, 46, 47, 48, 49])
        tickets = pick_abbreviated_wheel(pool)
        ticket_sets = [set(t) for t in tickets]
        winning = (1, 2, 48, 49)
        best = max(len(set(winning) & ts) for ts in ticket_sets)
        self.assertGreaterEqual(best, 3)


if __name__ == "__main__":
    unittest.main()
