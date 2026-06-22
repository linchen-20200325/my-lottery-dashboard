"""Freshness 模組單元測試 — 雙樂透開獎日 + 22:00 GMT+8 截止線。"""

from __future__ import annotations

import csv
import unittest
from datetime import date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from src.data.freshness import (
    DEADLINE_HOUR,
    GMT8,
    LOTTO649_DRAW_WEEKDAYS,
    POWERBALL_DRAW_WEEKDAYS,
    check_freshness,
    expected_latest_draw,
    latest_csv_date,
)


def _dt(y: int, m: int, d: int, h: int = 12) -> datetime:
    return datetime(y, m, d, h, 0, tzinfo=GMT8)


def _write_csv(path: Path, dates: list[str]) -> None:
    fields = ["draw_term", "draw_date", "n1", "n2", "n3",
              "n4", "n5", "n6", "special"]
    with path.open("w", encoding="utf-8", newline="") as fp:
        w = csv.DictWriter(fp, fieldnames=fields)
        w.writeheader()
        for i, d in enumerate(dates):
            w.writerow({
                "draw_term": f"X{1000 + i}",
                "draw_date": d,
                "n1": 1, "n2": 2, "n3": 3,
                "n4": 4, "n5": 5, "n6": 6,
                "special": 1,
            })


class TestExpectedLatestDraw(unittest.TestCase):

    def test_lotto649_friday_after_22_returns_today(self):
        # 2026-06-19 = Friday;晚上 23:00 → 預期今日已開
        now = _dt(2026, 6, 19, 23)
        self.assertEqual(now.weekday(), 4)
        self.assertEqual(
            expected_latest_draw(now, LOTTO649_DRAW_WEEKDAYS),
            date(2026, 6, 19),
        )

    def test_lotto649_friday_before_22_returns_tuesday(self):
        # 2026-06-19 = Friday;下午 14:00 → 還沒到 22:00,回退到週二 6/16
        now = _dt(2026, 6, 19, 14)
        self.assertEqual(
            expected_latest_draw(now, LOTTO649_DRAW_WEEKDAYS),
            date(2026, 6, 16),
        )

    def test_lotto649_wednesday_returns_tuesday(self):
        # 2026-06-17 = Wednesday → 上一個 draw day = 6/16 Tuesday
        now = _dt(2026, 6, 17, 12)
        self.assertEqual(
            expected_latest_draw(now, LOTTO649_DRAW_WEEKDAYS),
            date(2026, 6, 16),
        )

    def test_powerball_monday_after_22_returns_today(self):
        # 2026-06-22 = Monday;晚上 23:00
        now = _dt(2026, 6, 22, 23)
        self.assertEqual(now.weekday(), 0)
        self.assertEqual(
            expected_latest_draw(now, POWERBALL_DRAW_WEEKDAYS),
            date(2026, 6, 22),
        )

    def test_powerball_monday_before_22_returns_thursday(self):
        # 2026-06-22 = Monday;早上 10:00 → 還沒到 22:00,回退到上週四 6/18
        now = _dt(2026, 6, 22, 10)
        self.assertEqual(
            expected_latest_draw(now, POWERBALL_DRAW_WEEKDAYS),
            date(2026, 6, 18),
        )

    def test_empty_weekdays_raises(self):
        with self.assertRaises(ValueError):
            expected_latest_draw(_dt(2026, 6, 22), frozenset())

    def test_deadline_hour_boundary(self):
        # 剛好 22:00 整點 → 應視為已過截止
        now_at_22 = _dt(2026, 6, 19, DEADLINE_HOUR)
        self.assertEqual(
            expected_latest_draw(now_at_22, LOTTO649_DRAW_WEEKDAYS),
            date(2026, 6, 19),
        )


class TestLatestCsvDate(unittest.TestCase):

    def test_returns_first_nonempty(self):
        with TemporaryDirectory() as tmp:
            p = Path(tmp) / "x.csv"
            _write_csv(p, ["2026/06/19", "2026/06/16", "2026/06/12"])
            self.assertEqual(latest_csv_date(p), date(2026, 6, 19))

    def test_skips_empty_dates(self):
        with TemporaryDirectory() as tmp:
            p = Path(tmp) / "x.csv"
            _write_csv(p, ["", "", "2026/06/12"])
            self.assertEqual(latest_csv_date(p), date(2026, 6, 12))

    def test_all_empty_returns_none(self):
        with TemporaryDirectory() as tmp:
            p = Path(tmp) / "x.csv"
            _write_csv(p, ["", "", ""])
            self.assertIsNone(latest_csv_date(p))

    def test_missing_file_returns_none(self):
        self.assertIsNone(latest_csv_date(Path("/no/such/file.csv")))

    def test_malformed_date_skipped(self):
        with TemporaryDirectory() as tmp:
            p = Path(tmp) / "x.csv"
            _write_csv(p, ["not-a-date", "2026/06/12"])
            self.assertEqual(latest_csv_date(p), date(2026, 6, 12))


class TestCheckFreshness(unittest.TestCase):

    def test_fresh_returns_none(self):
        # Latest = 2026/06/19 Friday;now = same day 23:00
        with TemporaryDirectory() as tmp:
            p = Path(tmp) / "x.csv"
            _write_csv(p, ["2026/06/19", "2026/06/16"])
            self.assertIsNone(check_freshness(
                p, LOTTO649_DRAW_WEEKDAYS, now=_dt(2026, 6, 19, 23),
            ))

    def test_stale_returns_warning(self):
        # Latest = 2026/06/12 Friday;now = 2026/06/19 Friday 23:00
        # 預期至少要有 6/19,但只有 6/12 → 落後 7 天
        with TemporaryDirectory() as tmp:
            p = Path(tmp) / "x.csv"
            _write_csv(p, ["2026/06/12"])
            msg = check_freshness(
                p, LOTTO649_DRAW_WEEKDAYS, now=_dt(2026, 6, 19, 23),
            )
            self.assertIsNotNone(msg)
            self.assertIn("2026-06-12", msg)
            self.assertIn("2026-06-19", msg)
            self.assertIn("7", msg)  # 落後 7 天

    def test_empty_csv_returns_none(self):
        # 全空日期 → latest_csv_date 回 None → check_freshness 不發 warning
        with TemporaryDirectory() as tmp:
            p = Path(tmp) / "x.csv"
            _write_csv(p, ["", ""])
            self.assertIsNone(check_freshness(
                p, LOTTO649_DRAW_WEEKDAYS, now=_dt(2026, 6, 19, 23),
            ))

    def test_before_deadline_uses_previous_draw(self):
        # Latest = 6/16 Tue;now = 6/19 Fri 下午(未到 22:00) → expected = 6/16 → fresh
        with TemporaryDirectory() as tmp:
            p = Path(tmp) / "x.csv"
            _write_csv(p, ["2026/06/16"])
            self.assertIsNone(check_freshness(
                p, LOTTO649_DRAW_WEEKDAYS, now=_dt(2026, 6, 19, 14),
            ))


if __name__ == "__main__":
    unittest.main()
