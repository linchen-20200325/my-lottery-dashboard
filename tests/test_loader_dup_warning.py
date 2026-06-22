"""A3 — 兩 scraper `load_existing()` 對 CSV 內重複 `draw_term` 應 LOGGER.warning。

對應 CLAUDE.md §4.6「重複 draw_term `_gaps()` 用 setdefault 自然忽略」風險條 — v6.8 之前
sloader 沉默 last-write-wins、無診斷訊息。本測試確保 logger 觸發。
"""

from __future__ import annotations

import csv
import logging
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from src.scraper import lotto649_downloader as l649
from src.scraper import powerball_downloader as pb


def _write_csv(path: Path, rows: list[dict]) -> None:
    fields = ["draw_term", "draw_date", "n1", "n2", "n3",
              "n4", "n5", "n6", "special"]
    with path.open("w", encoding="utf-8", newline="") as fp:
        w = csv.DictWriter(fp, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def _row(term: str, date: str, special: int = 1) -> dict:
    return {
        "draw_term": term, "draw_date": date,
        "n1": 1, "n2": 2, "n3": 3, "n4": 4, "n5": 5, "n6": 6,
        "special": special,
    }


class TestLottoLoadExistingDupWarning(unittest.TestCase):

    def test_duplicate_draw_term_logs_warning(self):
        with TemporaryDirectory() as tmp:
            p = Path(tmp) / "x.csv"
            _write_csv(p, [
                _row("ABC", "2026/06/19"),
                _row("ABC", "2026/06/16"),  # 重複 term,應觸發 warning
            ])
            with self.assertLogs(l649.LOGGER, level=logging.WARNING) as cm:
                merged = l649.load_existing(p)
            self.assertEqual(len(merged), 1)  # last-write-wins
            self.assertTrue(
                any("duplicate draw_term=ABC" in r.message for r in cm.records),
                f"expected dup warning in records: {cm.records}",
            )

    def test_no_duplicate_no_warning(self):
        with TemporaryDirectory() as tmp:
            p = Path(tmp) / "x.csv"
            _write_csv(p, [
                _row("AAA", "2026/06/19"),
                _row("BBB", "2026/06/16"),
            ])
            # assertNoLogs: Python 3.10+;這裡用 assertLogs(level=WARNING) +
            # 預期沒有 records,但 assertLogs 預期至少 1 條會 fail。
            # 改寫:抓 logger output 自行驗證沒有 warning。
            logger = l649.LOGGER
            handler_records: list[logging.LogRecord] = []

            class _Capture(logging.Handler):
                def emit(self, record):
                    if record.levelno >= logging.WARNING:
                        handler_records.append(record)

            h = _Capture()
            logger.addHandler(h)
            try:
                l649.load_existing(p)
            finally:
                logger.removeHandler(h)
            dup_warnings = [
                r for r in handler_records
                if "duplicate draw_term" in r.getMessage()
            ]
            self.assertEqual(dup_warnings, [])


class TestPowerballLoadExistingDupWarning(unittest.TestCase):

    def test_duplicate_draw_term_logs_warning(self):
        with TemporaryDirectory() as tmp:
            p = Path(tmp) / "x.csv"
            _write_csv(p, [
                _row("PB1", "2026/06/22", special=3),
                _row("PB1", "2026/06/18", special=5),  # 重複 term
            ])
            with self.assertLogs(pb.LOGGER, level=logging.WARNING) as cm:
                merged = pb.load_existing(p)
            self.assertEqual(len(merged), 1)
            self.assertTrue(
                any("duplicate draw_term=PB1" in r.message for r in cm.records),
            )


if __name__ == "__main__":
    unittest.main()
