"""Unit tests for src.ui._view_base (純 helper,無 streamlit 依賴)。"""

import random
import unittest
from datetime import datetime

from src.ui._view_base import (
    analysis_rng,
    expand_tails_to_numbers,
    freshness_warning,
    upload_provenance,
)


class TestExpandTails(unittest.TestCase):
    def test_lotto_pool(self):
        self.assertEqual(
            expand_tails_to_numbers([1, 6], 1, 49),
            [1, 6, 11, 16, 21, 26, 31, 36, 41, 46],
        )

    def test_powerball_pool(self):
        # 1-38 池,尾數 0 → 10,20,30(38 內無 40)
        self.assertEqual(expand_tails_to_numbers([0], 1, 38), [10, 20, 30])

    def test_empty_returns_empty(self):
        self.assertEqual(expand_tails_to_numbers([], 1, 49), [])
        self.assertEqual(expand_tails_to_numbers(set(), 1, 49), [])

    def test_set_input_accepted(self):
        self.assertEqual(expand_tails_to_numbers({7}, 1, 38), [7, 17, 27, 37])


class TestAnalysisRng(unittest.TestCase):
    def test_seeded_is_deterministic(self):
        # seed != 0 → 與同 seed 的 random.Random 等價
        self.assertEqual(
            analysis_rng(42).random(), random.Random(42).random()
        )

    def test_zero_is_unseeded_random(self):
        rng = analysis_rng(0)
        self.assertIsInstance(rng, random.Random)
        # 無種子:應可正常產生 [0,1) 浮點(不保證值,只驗契約)
        self.assertTrue(0.0 <= rng.random() < 1.0)


class TestUploadProvenance(unittest.TestCase):
    def test_json_has_null_dates(self):
        prov = upload_provenance("<upload:x.json>", 12)
        self.assertEqual(prov.source, "<upload:x.json>")
        self.assertEqual(prov.n_rows, 12)
        self.assertIsNone(prov.as_of)
        self.assertIsNone(prov.earliest)
        self.assertIsInstance(prov.fetched_at, datetime)


class TestFreshnessWarning(unittest.TestCase):
    def test_missing_file_returns_none(self):
        # 不存在的 CSV → latest_csv_date None → 不發 warning
        self.assertIsNone(
            freshness_warning("/nonexistent/path.csv", frozenset({1, 4}))
        )


if __name__ == "__main__":
    unittest.main()
