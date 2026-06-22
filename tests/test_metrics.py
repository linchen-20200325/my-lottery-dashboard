"""Unit tests for analytics.metrics (v5.0 backtest indicators)."""

import csv
import tempfile
import unittest
from pathlib import Path

from src.analytics.metrics import (
    TOTAL_COMBINATIONS,
    compression_rate,
    compression_rate_monte_carlo,
    reconcile_compression,
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


class TestMonteCarloReconcile(unittest.TestCase):
    """憲法 §4.3 第二種算法對帳:exact ↔ Monte Carlo 在容差內一致。

    複用 TestCompressionRate.setUpClass 快取的 exact 結果(~30-60s)避免重算。
    Monte Carlo 50k 樣本 std error ≈ 0.0016(p=0.15),5% 容差很寬裕。
    """

    @classmethod
    def setUpClass(cls):
        # exact 全列舉約 30-60s,reuse 給多個測試避免重算
        cls.exact = compression_rate()
        cls.mc = compression_rate_monte_carlo(n_samples=50_000, seed=2026)

    def test_monte_carlo_estimate_in_range(self):
        # 抽樣估算應落在 [0, 1] 區間
        self.assertGreaterEqual(self.mc["estimated_ratio"], 0.0)
        self.assertLessEqual(self.mc["estimated_ratio"], 1.0)

    def test_reconcile_passes_default_tolerance(self):
        # 重用 cls.exact 避免再跑 30-60s 全列舉
        result = reconcile_compression(
            n_samples=50_000, seed=2026, exact_result=self.exact,
        )
        self.assertTrue(
            result["passed"],
            f"reconcile failed: exact={result['exact_ratio']:.6f}, "
            f"mc={result['monte_carlo_ratio']:.6f}, "
            f"rel_diff={result['rel_diff']:.4f}",
        )

    def test_zero_tolerance_fails(self):
        # 容差設 0 → 抽樣絕不可能精確等於列舉值,必 FAIL
        result = reconcile_compression(
            n_samples=10_000, seed=42, rel_tol=0.0,
            exact_result=self.exact,
        )
        self.assertFalse(result["passed"])

    def test_estimate_close_to_exact(self):
        # 直接比對:50k 樣本下 |exact - mc| 應 < 1%(實測通常 < 0.5%)
        diff = abs(
            float(self.exact["compression_ratio"])
            - self.mc["estimated_ratio"]
        )
        self.assertLess(diff, 0.01)


if __name__ == "__main__":
    unittest.main()
