"""DomainConfig 對帳測試 — 鎖定 SSOT 與四檔現役常數一致。

本測試是 `src/generator/domain.py` 的「漂移偵測器」:只要有人改了
engine/picker 的領域常數卻忘了同步 domain.py(或反之),這裡立刻紅燈。
在 B4 把 engine/picker 切換為 import 自 domain 之前,這層對帳保證切換零風險。
"""

from __future__ import annotations

import dataclasses
import unittest

from src.generator import domain
from src.generator import history_engine as he
from src.generator import lotto_picker as lp
from src.generator import powerball_engine as pe
from src.generator import powerball_picker as pp


class TestLotto649Reconcile(unittest.TestCase):
    cfg = domain.LOTTO649

    def test_pool_matches_history_engine(self):
        self.assertEqual(self.cfg.pool_min, he.POOL_MIN)
        self.assertEqual(self.cfg.pool_max, he.POOL_MAX)
        self.assertEqual(self.cfg.ticket_size, he.TICKET_SIZE)
        self.assertEqual(self.cfg.tails_range_n, len(he.TAILS_RANGE))

    def test_defaults_dict_identical(self):
        self.assertEqual(self.cfg.defaults, he.DEFAULTS)

    def test_static_sum_matches(self):
        self.assertEqual(self.cfg.static_sum_min, he.STATIC_SUM_MIN)
        self.assertEqual(self.cfg.static_sum_max, he.STATIC_SUM_MAX)

    def test_picker_constants_match(self):
        self.assertEqual(self.cfg.big_threshold, lp.BIG_THRESHOLD)
        self.assertEqual(self.cfg.min_big_count, lp.MIN_BIG_COUNT)
        self.assertEqual(self.cfg.min_key_nums, lp.MIN_KEY_NUMS)
        self.assertEqual(self.cfg.max_key_nums, lp.MAX_KEY_NUMS)
        self.assertEqual(self.cfg.min_prime_count, lp.MIN_PRIME_COUNT)
        self.assertEqual(self.cfg.max_prime_count, lp.MAX_PRIME_COUNT)
        self.assertEqual(self.cfg.max_consecutive_pairs, lp.MAX_CONSECUTIVE_PAIRS)
        self.assertEqual(self.cfg.allowed_odd_counts, lp.ALLOWED_ODD_COUNTS)
        self.assertEqual(self.cfg.primes_set, lp.PRIMES_SET)

    def test_special_is_documented_rule(self):
        # 大樂透特別號 ∈ [1,49](台彩規則,CLAUDE.md §3.2 #2)。
        # 目前 loader 未驗證(DR-1),B3 wiring 時將以此 range 補上。
        self.assertEqual((self.cfg.special_min, self.cfg.special_max), (1, 49))


class TestPowerballReconcile(unittest.TestCase):
    cfg = domain.POWERBALL

    def test_pool_matches_engine(self):
        self.assertEqual(self.cfg.pool_min, pe.MAIN_POOL_MIN)
        self.assertEqual(self.cfg.pool_max, pe.MAIN_POOL_MAX)
        self.assertEqual(self.cfg.ticket_size, pe.TICKET_SIZE)
        self.assertEqual(self.cfg.tails_range_n, len(pe.TAILS_RANGE))

    def test_special_matches_bonus_pool(self):
        self.assertEqual(self.cfg.special_min, pe.BONUS_POOL_MIN)
        self.assertEqual(self.cfg.special_max, pe.BONUS_POOL_MAX)

    def test_defaults_dict_identical(self):
        self.assertEqual(self.cfg.defaults, pe.DEFAULTS)

    def test_static_sum_matches(self):
        self.assertEqual(self.cfg.static_sum_min, pe.STATIC_SUM_MIN)
        self.assertEqual(self.cfg.static_sum_max, pe.STATIC_SUM_MAX)

    def test_picker_constants_match(self):
        self.assertEqual(self.cfg.big_threshold, pp.BIG_THRESHOLD)
        self.assertEqual(self.cfg.min_big_count, pp.MIN_BIG_COUNT)
        self.assertEqual(self.cfg.min_key_nums, pp.MIN_KEY_NUMS)
        self.assertEqual(self.cfg.max_key_nums, pp.MAX_KEY_NUMS)
        self.assertEqual(self.cfg.min_prime_count, pp.MIN_PRIME_COUNT)
        self.assertEqual(self.cfg.max_prime_count, pp.MAX_PRIME_COUNT)
        self.assertEqual(self.cfg.max_consecutive_pairs, pp.MAX_CONSECUTIVE_PAIRS)
        self.assertEqual(self.cfg.allowed_odd_counts, pp.ALLOWED_ODD_COUNTS)
        self.assertEqual(self.cfg.primes_set, pp.PRIMES_SET)


class TestFrozenHashable(unittest.TestCase):
    def test_hashable_for_cache_key(self):
        # 必須可 hash(作 @st.cache_data key);REFACTOR_AUDIT §7 紅線。
        self.assertIsInstance(hash(domain.LOTTO649), int)
        self.assertIsInstance(hash(domain.POWERBALL), int)
        self.assertNotEqual(hash(domain.LOTTO649), hash(domain.POWERBALL))

    def test_frozen_immutable(self):
        with self.assertRaises(dataclasses.FrozenInstanceError):
            domain.LOTTO649.pool_max = 99  # type: ignore[misc]

    def test_defaults_returns_fresh_dict(self):
        # property 每次回新 dict,改動不污染下一次取用。
        d = domain.LOTTO649.defaults
        d["sum_range_pad"] = -999
        self.assertEqual(domain.LOTTO649.defaults["sum_range_pad"], 30)


if __name__ == "__main__":
    unittest.main()
