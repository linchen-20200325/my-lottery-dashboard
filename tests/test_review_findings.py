"""v6.3 — Code Review 三大風險修復測試（TDD 紅燈 → 綠燈規格）.

對應修復：
  1. `backtest()` 對 oldest-first CSV 應 raise ValueError（newest-first 不變量）
  2. `_canon_date()` 應拒絕不存在的日期（2/30、13/05 等）
  3. `powerball_engine.analyze()` 應對歷史 specials 中超界值 raise ValueError
"""

from __future__ import annotations

import csv
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from src.analytics.backtest import backtest
from src.generator.powerball_engine import analyze as pb_analyze
from src.scraper.lotto649_downloader import _canon_date


def _write_csv(path: Path, rows: list[dict]) -> None:
    fields = ["draw_term", "draw_date", "n1", "n2", "n3",
              "n4", "n5", "n6", "special"]
    with path.open("w", encoding="utf-8", newline="") as fp:
        w = csv.DictWriter(fp, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


class TestBacktestNewestFirstInvariant(unittest.TestCase):
    """Risk 1：backtest 假設 CSV newest-first；oldest-first 必須 raise。"""

    def _make_rows(self, oldest_first: bool) -> list[dict]:
        rows = []
        for i in range(35):
            rows.append({
                "draw_term": f"114{999000 + i:06d}",
                "draw_date": f"2026/01/{i + 1:02d}",
                "n1": 1 + (i % 3), "n2": 7, "n3": 12,
                "n4": 19, "n5": 28, "n6": 35,
                "special": 4,
            })
        return rows if oldest_first else list(reversed(rows))

    def test_oldest_first_csv_raises(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "lotto649.csv"
            _write_csv(path, self._make_rows(oldest_first=True))
            with self.assertRaises(ValueError) as ctx:
                backtest(path, tickets_per_draw=2, lookback=30, seed=1)
            self.assertIn("newest-first", str(ctx.exception))

    def test_newest_first_csv_passes_invariant(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "lotto649.csv"
            _write_csv(path, self._make_rows(oldest_first=False))
            # 不應 raise（這個合成資料注數可能因濾網太嚴 = 0，但不變量應通過）
            result = backtest(path, tickets_per_draw=2, lookback=30, seed=1)
            self.assertIn("draws_evaluated", result)


class TestCanonDateRejectsImpossibleDates(unittest.TestCase):
    """Risk 2：_canon_date 只 zero-pad、不驗證日期合法性。"""

    def test_rejects_feb_30(self):
        self.assertEqual(_canon_date("2026/02/30"), "")

    def test_rejects_month_13(self):
        self.assertEqual(_canon_date("2026/13/05"), "")

    def test_rejects_day_32(self):
        self.assertEqual(_canon_date("2026/01/32"), "")

    def test_accepts_valid_leap_year(self):
        self.assertEqual(_canon_date("2024/02/29"), "2024/02/29")

    def test_rejects_non_leap_year_feb_29(self):
        # 2026 非閏年
        self.assertEqual(_canon_date("2026/02/29"), "")

    def test_accepts_normal_date(self):
        self.assertEqual(_canon_date("2026/06/01"), "2026/06/01")

    def test_dash_normalized(self):
        self.assertEqual(_canon_date("2026-5-9"), "2026/05/09")

    def test_unparseable_returns_input_unchanged(self):
        # 純文字（非數字）保持原樣 — 為兼容上游 API 偶發回奇怪格式
        self.assertEqual(_canon_date("abc/def/ghi"), "abc/def/ghi")


class TestPowerballAnalyzeRejectsInvalidSpecials(unittest.TestCase):
    """Risk 3：威力彩 analyze 應對歷史 specials 中超界值 raise。"""

    def test_special_above_8_raises(self):
        draws = [[1, 2, 3, 4, 5, 6]] * 30
        specials = [3] * 29 + [28]
        with self.assertRaises(ValueError) as ctx:
            pb_analyze(draws=draws, specials=specials)
        self.assertIn("28", str(ctx.exception))

    def test_special_below_1_raises(self):
        draws = [[1, 2, 3, 4, 5, 6]] * 30
        specials = [3] * 29 + [0]
        with self.assertRaises(ValueError):
            pb_analyze(draws=draws, specials=specials)

    def test_special_negative_raises(self):
        draws = [[1, 2, 3, 4, 5, 6]] * 30
        specials = [3] * 29 + [-1]
        with self.assertRaises(ValueError):
            pb_analyze(draws=draws, specials=specials)

    def test_clean_specials_pass(self):
        draws = [[1, 2, 3, 4, 5, 6]] * 30
        specials = [3] * 30
        result = pb_analyze(draws=draws, specials=specials)
        # 合法 3 的 gap 應為 0（最近一期）
        self.assertEqual(result.bonus_gaps[3], 0)


if __name__ == "__main__":
    unittest.main()
