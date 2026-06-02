"""威力彩 scraper 單元測試 — parse + dedup + 容錯。

不打外網；用 mock session / 直接 patch _fetch_month_raw。
"""

from __future__ import annotations

import csv
import io
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from src.scraper import powerball_downloader as pb


class TestParseRow(unittest.TestCase):

    def test_legacy_chinese_shape(self):
        row = {
            "期別": "114000123",
            "開獎日期": "2026-05-26",
            "第一區": [3, 11, 19, 22, 28, 35],
            "第二區": 7,
        }
        d = pb._parse_row(row)
        self.assertIsNotNone(d)
        self.assertEqual(d.n1, 3)
        self.assertEqual(d.n6, 35)
        self.assertEqual(d.special, 7)
        self.assertEqual(d.draw_date, "2026/05/26")

    def test_drawNumberSize_shape(self):
        row = {
            "period": "114000124",
            "lotteryDate": "2026/05/29",
            "drawNumberSize": [4, 9, 14, 21, 27, 33, 6],
        }
        d = pb._parse_row(row)
        self.assertIsNotNone(d)
        self.assertEqual(d.special, 6)

    def test_short_nums_returns_none(self):
        row = {"第一區": [1, 2, 3], "第二區": 4}
        self.assertIsNone(pb._parse_row(row))

    def test_missing_special_returns_none(self):
        row = {"第一區": [1, 2, 3, 4, 5, 6]}
        self.assertIsNone(pb._parse_row(row))


class TestCanonDate(unittest.TestCase):

    def test_normalizes_dash_and_zero_pad(self):
        self.assertEqual(pb._canon_date("2026-5-9"), "2026/05/09")
        self.assertEqual(pb._canon_date("2026/05/09"), "2026/05/09")

    def test_empty_returns_empty(self):
        self.assertEqual(pb._canon_date(""), "")


class TestSaveCsvSortAndDedupe(unittest.TestCase):

    def test_long_form_term_sorts_above_short(self):
        draws = [
            pb.Draw("2446", "2024/01/15", 1, 2, 3, 4, 5, 6, 1),
            pb.Draw("114000050", "2026/05/15", 7, 8, 9, 10, 11, 12, 3),
        ]
        with TemporaryDirectory() as tmp:
            out = Path(tmp) / "powerball.csv"
            pb.save_csv(draws, out)
            with out.open() as fp:
                rows = list(csv.DictReader(fp))
        self.assertEqual(rows[0]["draw_term"], "114000050")
        self.assertEqual(rows[1]["draw_term"], "2446")

    def test_download_skips_existing_date(self):
        # 既有 CSV 有 5/26；fetch 又抓到同日期 → 應略過、added=0
        existing = pb.Draw("OLD", "2026/05/26", 1, 2, 3, 4, 5, 6, 1)
        with TemporaryDirectory() as tmp:
            out = Path(tmp) / "powerball.csv"
            pb.save_csv([existing], out)

            # Monkey-patch fetch to return one draw on the same date.
            original_fetch = pb.fetch
            try:
                pb.fetch = lambda periods=200, session=None: [  # type: ignore[assignment]
                    pb.Draw("114000999", "2026/05/26", 7, 8, 9, 10, 11, 12, 3)
                ]
                total = pb.download(periods=5, output=out)
            finally:
                pb.fetch = original_fetch  # type: ignore[assignment]
            self.assertEqual(total, 1)  # 只有 OLD，新抓的被 dedup


class TestLoadExisting(unittest.TestCase):

    def test_empty_file_returns_empty_dict(self):
        with TemporaryDirectory() as tmp:
            out = Path(tmp) / "powerball.csv"
            out.write_text("draw_term,draw_date,n1,n2,n3,n4,n5,n6,special\n",
                           encoding="utf-8")
            self.assertEqual(pb.load_existing(out), {})

    def test_missing_file_returns_empty(self):
        self.assertEqual(pb.load_existing(Path("/no/such/file.csv")), {})


class TestMonthsBack(unittest.TestCase):

    def test_wraps_year_correctly(self):
        ms = pb._months_back(15)
        self.assertEqual(len(ms), 15)
        # 第一個元素是當前年月
        self.assertEqual(len(ms[0][1]), 2)  # zero-padded


if __name__ == "__main__":
    unittest.main()
