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


class TestNewestFirstGuard(unittest.TestCase):
    def test_oldest_first_raises(self):
        # lookahead 護網:oldest-first 應 raise
        with self.assertRaises(ValueError):
            _assert_newest_first(["2026/01/01", "2026/01/05", "2026/01/09"])

    def test_newest_first_ok(self):
        _assert_newest_first(["2026/01/09", "2026/01/05", "2026/01/01"])  # no raise


if __name__ == "__main__":
    unittest.main()
