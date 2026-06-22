"""§2.2 Provenance 單元測試 — HistoryProvenance + extract_dates + loader 變體。"""

from __future__ import annotations

import csv
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from src.data.loader import (
    load_csv_file_with_provenance,
    load_csv_string_with_provenance,
)
from src.data.loader_powerball import (
    load_csv_file_with_provenance as pb_load_csv_file_with_provenance,
    load_csv_string_with_provenance as pb_load_csv_string_with_provenance,
)
from src.data.provenance import (
    HistoryProvenance,
    build_provenance_from_rows,
    extract_dates,
    format_provenance_caption,
    now_utc,
)


# 大樂透 CSV 用 6 顆 1-49,威力彩用 6 顆 1-38 + special 1-8
def _write_lotto_csv(path: Path, dates: list[str]) -> None:
    fields = ["draw_term", "draw_date", "n1", "n2", "n3",
              "n4", "n5", "n6", "special"]
    with path.open("w", encoding="utf-8", newline="") as fp:
        w = csv.DictWriter(fp, fieldnames=fields)
        w.writeheader()
        for i, d in enumerate(dates):
            w.writerow({
                "draw_term": f"X{1000 + i}",
                "draw_date": d,
                "n1": 5, "n2": 12, "n3": 18,
                "n4": 25, "n5": 33, "n6": 42,
                "special": 7,
            })


def _write_pb_csv(path: Path, dates: list[str]) -> None:
    fields = ["draw_term", "draw_date", "n1", "n2", "n3",
              "n4", "n5", "n6", "special"]
    with path.open("w", encoding="utf-8", newline="") as fp:
        w = csv.DictWriter(fp, fieldnames=fields)
        w.writeheader()
        for i, d in enumerate(dates):
            w.writerow({
                "draw_term": f"Y{2000 + i}",
                "draw_date": d,
                "n1": 3, "n2": 8, "n3": 15,
                "n4": 22, "n5": 28, "n6": 35,
                "special": 4,
            })


class TestHistoryProvenanceDataclass(unittest.TestCase):

    def test_frozen(self):
        prov = HistoryProvenance(
            source="x", fetched_at=now_utc(), n_rows=5,
        )
        with self.assertRaises(Exception):  # frozen dataclass → can't assign
            prov.source = "y"  # type: ignore[misc]

    def test_default_dates_are_none(self):
        prov = HistoryProvenance(source="x", fetched_at=now_utc(), n_rows=0)
        self.assertIsNone(prov.as_of)
        self.assertIsNone(prov.earliest)

    def test_now_utc_is_tz_aware(self):
        n = now_utc()
        self.assertEqual(n.tzinfo, timezone.utc)


class TestExtractDates(unittest.TestCase):

    def test_returns_max_and_min(self):
        rows = [
            {"draw_date": "2026/06/19"},
            {"draw_date": "2026/06/16"},
            {"draw_date": "2026/06/12"},
        ]
        as_of, earliest = extract_dates(rows)
        self.assertEqual(as_of, date(2026, 6, 19))
        self.assertEqual(earliest, date(2026, 6, 12))

    def test_skips_empty(self):
        rows = [
            {"draw_date": ""},
            {"draw_date": "2026/06/19"},
            {"draw_date": ""},
        ]
        as_of, earliest = extract_dates(rows)
        self.assertEqual(as_of, date(2026, 6, 19))
        self.assertEqual(earliest, date(2026, 6, 19))

    def test_all_empty_returns_none_pair(self):
        rows = [{"draw_date": ""}, {"draw_date": ""}]
        self.assertEqual(extract_dates(rows), (None, None))

    def test_malformed_dates_skipped(self):
        rows = [
            {"draw_date": "not-a-date"},
            {"draw_date": "2026/06/12"},
        ]
        as_of, earliest = extract_dates(rows)
        self.assertEqual(as_of, date(2026, 6, 12))
        self.assertEqual(earliest, date(2026, 6, 12))


class TestBuildProvenanceFromRows(unittest.TestCase):

    def test_sets_fields(self):
        rows = [
            {"draw_date": "2026/06/19"},
            {"draw_date": "2026/06/12"},
        ]
        prov = build_provenance_from_rows(rows, source="data/test.csv", n_parsed=2)
        self.assertEqual(prov.source, "data/test.csv")
        self.assertEqual(prov.n_rows, 2)
        self.assertEqual(prov.as_of, date(2026, 6, 19))
        self.assertEqual(prov.earliest, date(2026, 6, 12))
        self.assertEqual(prov.fetched_at.tzinfo, timezone.utc)


class TestLottoLoaderProvenance(unittest.TestCase):

    def test_load_csv_file_with_provenance(self):
        with TemporaryDirectory() as tmp:
            p = Path(tmp) / "x.csv"
            _write_lotto_csv(p, ["2026/06/19", "2026/06/12"])
            draws, prov = load_csv_file_with_provenance(p)
            self.assertEqual(len(draws), 2)
            self.assertEqual(prov.n_rows, 2)
            self.assertEqual(prov.source, str(p))
            self.assertEqual(prov.as_of, date(2026, 6, 19))
            self.assertEqual(prov.earliest, date(2026, 6, 12))

    def test_load_csv_string_with_provenance(self):
        text = (
            "draw_term,draw_date,n1,n2,n3,n4,n5,n6,special\n"
            "X1,2026/06/19,5,12,18,25,33,42,7\n"
        )
        draws, prov = load_csv_string_with_provenance(text, source="<paste>")
        self.assertEqual(len(draws), 1)
        self.assertEqual(prov.source, "<paste>")
        self.assertEqual(prov.as_of, date(2026, 6, 19))

    def test_all_empty_dates_yields_none_as_of(self):
        with TemporaryDirectory() as tmp:
            p = Path(tmp) / "x.csv"
            _write_lotto_csv(p, ["", ""])
            draws, prov = load_csv_file_with_provenance(p)
            self.assertEqual(len(draws), 2)
            self.assertIsNone(prov.as_of)
            self.assertIsNone(prov.earliest)


class TestPowerballLoaderProvenance(unittest.TestCase):

    def test_load_csv_file_with_provenance(self):
        with TemporaryDirectory() as tmp:
            p = Path(tmp) / "pb.csv"
            _write_pb_csv(p, ["2026/06/22", "2026/06/15"])
            draws, specials, prov = pb_load_csv_file_with_provenance(p)
            self.assertEqual(len(draws), 2)
            self.assertEqual(len(specials), 2)
            self.assertEqual(prov.n_rows, 2)
            self.assertEqual(prov.as_of, date(2026, 6, 22))
            self.assertEqual(prov.earliest, date(2026, 6, 15))

    def test_load_csv_string_with_provenance(self):
        text = (
            "draw_term,draw_date,n1,n2,n3,n4,n5,n6,special\n"
            "Y1,2026/06/22,3,8,15,22,28,35,4\n"
        )
        draws, specials, prov = pb_load_csv_string_with_provenance(
            text, source="<paste>",
        )
        self.assertEqual(len(draws), 1)
        self.assertEqual(prov.as_of, date(2026, 6, 22))


class TestFormatProvenanceCaption(unittest.TestCase):

    def test_caption_includes_all_fields(self):
        prov = HistoryProvenance(
            source="data/lotto649.csv",
            fetched_at=datetime(2026, 6, 22, 14, 30, tzinfo=timezone.utc),
            n_rows=571,
            as_of=date(2026, 6, 19),
            earliest=date(2024, 1, 1),
        )
        cap = format_provenance_caption(prov)
        self.assertIn("571", cap)
        self.assertIn("2026-06-19", cap)
        self.assertIn("2024-01-01", cap)
        self.assertIn("lotto649.csv", cap)
        self.assertIn("14:30 UTC", cap)

    def test_long_source_truncated(self):
        prov = HistoryProvenance(
            source="a" * 100,
            fetched_at=now_utc(),
            n_rows=1,
        )
        cap = format_provenance_caption(prov)
        # 起頭應該是省略符號(來源被截斷)
        self.assertIn("…", cap)


if __name__ == "__main__":
    unittest.main()
