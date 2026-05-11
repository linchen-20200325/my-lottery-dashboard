"""Unit tests for analytics.metrics (v5.0 backtest indicators)."""

import csv
import tempfile
import unittest
from pathlib import Path

from src.analytics.metrics import (
    TOTAL_COMBINATIONS,
    compression_rate,
    survival_rate,
)


class TestCompressionRate(unittest.TestCase):
    """compression_rate walks all C(49,6); ~14M combos. Cache the result."""

    @classmethod
    def setUpClass(cls):
        cls.result = compression_rate()

    def test_total_matches_math(self):
        # C(49, 6) = 13_983_816
        self.assertEqual(self.result["total_combinations"], 13_983_816)
        self.assertEqual(TOTAL_COMBINATIONS, 13_983_816)

    def test_compression_is_meaningful(self):
        # Five filters together should reject the bulk of combos
        self.assertLess(self.result["compression_ratio"], 0.5)
        self.assertGreater(self.result["compression_ratio"], 0.001)

    def test_arithmetic_consistency(self):
        r = self.result
        self.assertEqual(r["survived"] + r["rejected"], r["total_combinations"])


class TestSurvivalRate(unittest.TestCase):
    def test_with_synthetic_csv(self):
        rows = [
            {"n1": 5, "n2": 12, "n3": 18, "n4": 25, "n5": 33, "n6": 42},
            {"n1": 1, "n2": 2, "n3": 3, "n4": 4, "n5": 5, "n6": 6},  # likely killed
        ]
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, newline="") as f:
            w = csv.DictWriter(f, fieldnames=["n1", "n2", "n3", "n4", "n5", "n6"])
            w.writeheader()
            w.writerows(rows)
            p = Path(f.name)
        try:
            r = survival_rate(p)
            self.assertEqual(r["draws_total"], 2)
            self.assertEqual(r["survived"] + r["killed"], r["draws_total"])
            self.assertGreaterEqual(r["survival_rate"], 0)
            self.assertLessEqual(r["survival_rate"], 1)
        finally:
            p.unlink()

    def test_empty_csv_rejected(self):
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as f:
            f.write("n1,n2,n3,n4,n5,n6\n")
            p = Path(f.name)
        try:
            with self.assertRaises(ValueError):
                survival_rate(p)
        finally:
            p.unlink()


if __name__ == "__main__":
    unittest.main()
