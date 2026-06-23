"""威力彩 picker 單元測試 — 五大濾網重校 + bonus 解析。"""

from __future__ import annotations

import random
import unittest

from src.generator.powerball_engine import (
    BONUS_POOL_MAX,
    BONUS_POOL_MIN,
    MAIN_POOL_MAX,
    MAIN_POOL_MIN,
)
from src.generator.powerball_picker import (
    ALLOWED_ODD_COUNTS,
    BIG_THRESHOLD,
    MAX_CONSECUTIVE_PAIRS,
    MAX_PRIME_COUNT,
    MIN_BIG_COUNT,
    MIN_PRIME_COUNT,
    PRIMES_SET,
    generate_tickets,
    ticket_stats,
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


class TestPrimesSet(unittest.TestCase):

    def test_primes_capped_at_38(self):
        # 大樂透 PRIMES 含 41/43/47；威力彩必須裁掉
        self.assertNotIn(41, PRIMES_SET)
        self.assertNotIn(43, PRIMES_SET)
        self.assertNotIn(47, PRIMES_SET)
        # 必須含 37（< 38）
        self.assertIn(37, PRIMES_SET)

    def test_big_threshold_is_19(self):
        self.assertEqual(BIG_THRESHOLD, 19)


class TestGenerateBasics(unittest.TestCase):

    def test_returns_triple(self):
        tickets, bonus, analysis = generate_tickets(
            _synthetic_draws(), _synthetic_specials(),
            num_tickets=3, rng=random.Random(1),
        )
        self.assertIsInstance(tickets, list)
        self.assertIsInstance(bonus, int)
        self.assertTrue(BONUS_POOL_MIN <= bonus <= BONUS_POOL_MAX)

    def test_tickets_pass_all_filters(self):
        tickets, _, _ = generate_tickets(
            _synthetic_draws(), _synthetic_specials(),
            num_tickets=5, rng=random.Random(7),
        )
        for t in tickets:
            self.assertEqual(len(t), 6)
            for n in t:
                self.assertTrue(MAIN_POOL_MIN <= n <= MAIN_POOL_MAX)
            stats = ticket_stats(t)
            self.assertIn(stats["odd_count"], ALLOWED_ODD_COUNTS)
            self.assertGreaterEqual(stats["big_count"], MIN_BIG_COUNT)
            self.assertTrue(
                MIN_PRIME_COUNT <= stats["prime_count"] <= MAX_PRIME_COUNT
            )
            self.assertLessEqual(stats["consecutive_pairs"], MAX_CONSECUTIVE_PAIRS)

    def test_empty_history_raises(self):
        with self.assertRaises(ValueError):
            generate_tickets([], [], num_tickets=1, rng=random.Random(1))

    def test_invalid_num_tickets(self):
        with self.assertRaises(ValueError):
            generate_tickets(
                _synthetic_draws(), [], num_tickets=0, rng=random.Random(1),
            )


class TestManualBonus(unittest.TestCase):

    def test_manual_bonus_used(self):
        _, bonus, _ = generate_tickets(
            _synthetic_draws(), _synthetic_specials(),
            manual_bonus=7, rng=random.Random(1),
        )
        self.assertEqual(bonus, 7)

    def test_manual_bonus_out_of_range_raises(self):
        with self.assertRaises(ValueError):
            generate_tickets(
                _synthetic_draws(), _synthetic_specials(),
                manual_bonus=9, rng=random.Random(1),
            )

    def test_manual_bonus_zero_raises(self):
        with self.assertRaises(ValueError):
            generate_tickets(
                _synthetic_draws(), _synthetic_specials(),
                manual_bonus=0, rng=random.Random(1),
            )


class TestManualKeysAndExclusions(unittest.TestCase):

    def test_manual_keys_present_in_every_ticket(self):
        tickets, _, _ = generate_tickets(
            _synthetic_draws(), _synthetic_specials(),
            num_tickets=3, manual_keys=[7],
            rng=random.Random(1),
        )
        for t in tickets:
            self.assertIn(7, t)

    def test_manual_keys_out_of_pool_raises(self):
        with self.assertRaises(ValueError):
            generate_tickets(
                _synthetic_draws(), _synthetic_specials(),
                manual_keys=[40], rng=random.Random(1),
            )

    def test_excluded_number_never_appears(self):
        tickets, _, _ = generate_tickets(
            _synthetic_draws(), _synthetic_specials(),
            num_tickets=5, manual_excluded_numbers=[5, 17],
            rng=random.Random(1),
        )
        for t in tickets:
            self.assertNotIn(5, t)
            self.assertNotIn(17, t)


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
    """批次推薦模式 (v6.13):嚴格 pair-disjoint。"""

    def test_batch_disjoint_no_keys_pair_disjoint(self):
        tickets, _, _ = generate_tickets(
            _synthetic_draws(), _synthetic_specials(),
            num_tickets=3, manual_keys=None,
            batch_disjoint=True, rng=random.Random(3),
        )
        self.assertGreaterEqual(len(tickets), 2)
        _assert_pair_disjoint(self, tickets)

    def test_batch_disjoint_disables_keys(self):
        tickets, _, _ = generate_tickets(
            _synthetic_draws(), _synthetic_specials(),
            num_tickets=3, manual_keys=[7, 17],
            manual_sum_range=(80, 154),
            batch_disjoint=True, rng=random.Random(11),
        )
        self.assertGreaterEqual(len(tickets), 1)
        _assert_pair_disjoint(self, tickets)
        # 膽碼必須被全域停用 — 否則 pair (7, 17) 會出現在每注
        for t in tickets:
            self.assertFalse(
                {7, 17}.issubset(set(t)),
                f"keys (7, 17) leaked into ticket {t}",
            )

    def test_pair_disjoint_under_excluded_tails(self):
        # v6.13: 排除 4 個尾數 → pool 從 38 砍到約 30;
        # 嚴格 pair-disjoint 理論上限 ⌊C(30,2)/C(6,2)⌋ = ⌊435/15⌋ = 29 注
        tickets, _, _ = generate_tickets(
            _synthetic_draws(), _synthetic_specials(),
            num_tickets=8,
            manual_excluded_tails=[1, 6, 8, 9],
            batch_disjoint=True, rng=random.Random(42),
        )
        self.assertGreaterEqual(len(tickets), 1)
        for t in tickets:
            self.assertEqual(len(set(t)), 6)
            self.assertTrue(all(1 <= n <= 38 for n in t))
        self.assertEqual(len(set(tickets)), len(tickets), "no exact duplicate tickets")
        _assert_pair_disjoint(self, tickets)
        # v6.15:排除尾數 [1,6,8,9] 對 38 池 → 剩 30 顆(尾 1/6/8/9 各 3~4 顆)
        # 實際池大小由 38 − 排除尾數佔位數決定;這裡留鬆綁,測 base case
        _assert_usage_balanced(self, tickets, pool_size=30)

    def test_v6_15_usage_cap_full_pool(self):
        # v6.15:全池 38 顆 + 8 注 → ⌈48/38⌉ + 1 = 3,每號最多 3 次
        tickets, _, _ = generate_tickets(
            _synthetic_draws(), _synthetic_specials(),
            num_tickets=8, manual_keys=None,
            batch_disjoint=True, rng=random.Random(42),
        )
        _assert_pair_disjoint(self, tickets)
        _assert_usage_balanced(self, tickets, pool_size=38)


if __name__ == "__main__":
    unittest.main()
