"""Unit tests for analytics.backtest (v6.24 B6 — 雙樂透參數化)。"""

import csv
import random
import tempfile
import unittest
from pathlib import Path

from src.analytics.backtest import backtest, _assert_newest_first
from src.generator.domain import LOTTO649, POWERBALL


def _make_csv(dom, n: int = 40, seed: int = 5) -> Path:
    """合成 newest-first CSV(draw_date 遞減),主號 ∈ dom 池。"""
    rng = random.Random(seed)
    rows = []
    for i in range(n):
        nums = sorted(rng.sample(range(dom.pool_min, dom.pool_max + 1), 6))
        rows.append({
            "draw_date": f"2026/02/{n - i:02d}",
            **{f"n{j + 1}": nums[j] for j in range(6)},
        })
    f = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, newline="")
    w = csv.DictWriter(
        f, fieldnames=["draw_date", "n1", "n2", "n3", "n4", "n5", "n6"]
    )
    w.writeheader()
    w.writerows(rows)
    f.close()
    return Path(f.name)


class TestBacktestLotto(unittest.TestCase):
    def test_produces_tickets_and_roi(self):
        p = _make_csv(LOTTO649)
        try:
            r = backtest(p, tickets_per_draw=3, lookback=10, seed=1, dom=LOTTO649)
            self.assertGreater(r["tickets_generated"], 0)
            self.assertIsNotNone(r["payout_twd"])
            self.assertIsNotNone(r["roi_percent"])
            self.assertEqual(r["cost_twd"], r["tickets_generated"] * 50)
        finally:
            p.unlink()


class TestBacktestPowerball(unittest.TestCase):
    def test_no_fabricated_payout(self):
        # 威力彩無 honest 名目獎金表 → payout/net/roi 必為 None(§1 不捏造)
        p = _make_csv(POWERBALL)
        try:
            r = backtest(p, tickets_per_draw=3, lookback=10, seed=1, dom=POWERBALL)
            self.assertGreater(r["tickets_generated"], 0)
            self.assertIsNone(r["payout_twd"])
            self.assertIsNone(r["net_twd"])
            self.assertIsNone(r["roi_percent"])
            self.assertIsInstance(r["hit_distribution"], dict)
        finally:
            p.unlink()


class TestBacktestOptions(unittest.TestCase):
    """v6.25 — 回測選項:幾組 / 不重複 / 霍華德 / 幾期。"""

    def test_max_periods_limits_window(self):
        p = _make_csv(LOTTO649, n=60)
        try:
            r = backtest(p, lookback=20, seed=1, dom=LOTTO649, max_periods=8)
            self.assertEqual(r["periods_requested"], 8)
            self.assertLessEqual(r["draws_evaluated"], 8)
            # 不限 → 全部可評估期 = 60-20-1
            r_all = backtest(p, lookback=20, seed=1, dom=LOTTO649)
            self.assertEqual(r_all["periods_requested"], 39)
        finally:
            p.unlink()

    def test_max_periods_zero_raises(self):
        p = _make_csv(LOTTO649, n=40)
        try:
            with self.assertRaises(ValueError):
                backtest(p, dom=LOTTO649, max_periods=0)
        finally:
            p.unlink()

    def test_options_and_per_draw_distribution(self):
        p = _make_csv(LOTTO649, n=60)
        sp = {"hot_sigma_factor": 0.5, "sum_sma_window": 10, "sum_range_pad": 30}
        try:
            r = backtest(
                p, tickets_per_draw=4, lookback=20, seed=1, dom=LOTTO649,
                batch_disjoint=True, howard_mode=True, max_periods=10,
                signal_params=sp,
            )
            self.assertGreater(r["tickets_generated"], 0)
            # 每期最佳命中分佈:各期數加總 ≤ 已評估期數
            ddist = r["draws_hit_distribution"]
            self.assertIsInstance(ddist, dict)
            self.assertLessEqual(sum(ddist.values()), r["draws_evaluated"])
        finally:
            p.unlink()

    def test_sample_of_generated_tickets(self):
        # result 帶「最新一期實際選出的注」範例(讓 UI 眼見每期重選號)
        p = _make_csv(LOTTO649, n=60)
        try:
            r = backtest(p, tickets_per_draw=4, lookback=20, seed=1,
                         dom=LOTTO649, max_periods=10)
            sample = r["sample"]
            self.assertIsInstance(sample, dict)
            self.assertEqual(len(sample["target"]), 6)
            self.assertGreaterEqual(len(sample["tickets"]), 1)
            self.assertLessEqual(len(sample["tickets"]), 5)
            self.assertEqual(len(sample["tickets"]), len(sample["hits"]))
            for t, h in zip(sample["tickets"], sample["hits"]):
                self.assertEqual(len(t), 6)
                self.assertEqual(h, len(set(t) & set(sample["target"])))
        finally:
            p.unlink()

    def test_powerball_ignores_howard_no_crash(self):
        p = _make_csv(POWERBALL, n=50)
        try:
            r = backtest(
                p, tickets_per_draw=3, lookback=20, seed=1, dom=POWERBALL,
                batch_disjoint=True, howard_mode=True, max_periods=8,
            )
            self.assertGreater(r["tickets_generated"], 0)
            self.assertIsNone(r["payout_twd"])  # 威力彩仍不捏造 payout
        finally:
            p.unlink()


class TestNewestFirstGuard(unittest.TestCase):
    def test_oldest_first_raises(self):
        # lookahead 護網:oldest-first 應 raise
        with self.assertRaises(ValueError):
            _assert_newest_first(["2026/01/01", "2026/01/05", "2026/01/09"])

    def test_newest_first_ok(self):
        _assert_newest_first(["2026/01/09", "2026/01/05", "2026/01/01"])  # no raise


if __name__ == "__main__":
    unittest.main()
