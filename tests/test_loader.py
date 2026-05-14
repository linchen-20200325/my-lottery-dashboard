"""Unit tests for src.data.loader."""

import json
import tempfile
import unittest
from pathlib import Path

from src.data.loader import (
    HistoryLoadError,
    load_auto,
    load_csv_file,
    load_csv_string,
    load_json_string,
    preview_recent,
)

GOOD_CSV = """draw_term,draw_date,n1,n2,n3,n4,n5,n6,special
115050,2026-05-09,5,12,18,25,33,42,7
115049,2026-05-06,3,11,17,24,32,41,8
"""


class TestCsv(unittest.TestCase):
    def test_string_ok(self):
        draws = load_csv_string(GOOD_CSV)
        self.assertEqual(len(draws), 2)
        self.assertEqual(draws[0], [5, 12, 18, 25, 33, 42])

    def test_file_ok(self):
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as f:
            f.write(GOOD_CSV)
            p = Path(f.name)
        try:
            draws = load_csv_file(p)
            self.assertEqual(len(draws), 2)
        finally:
            p.unlink()

    def test_missing_file(self):
        with self.assertRaises(HistoryLoadError):
            load_csv_file("/nonexistent/path.csv")

    def test_out_of_range(self):
        bad = "n1,n2,n3,n4,n5,n6\n1,2,3,4,5,50\n"
        with self.assertRaises(HistoryLoadError):
            load_csv_string(bad)

    def test_duplicate_rejected(self):
        bad = "n1,n2,n3,n4,n5,n6\n1,1,2,3,4,5\n"
        with self.assertRaises(HistoryLoadError):
            load_csv_string(bad)


class TestJson(unittest.TestCase):
    def test_string_ok(self):
        payload = json.dumps([
            {"draw": [1, 2, 3, 4, 5, 6]},
            {"draw": [10, 20, 30, 40, 41, 42]},
        ])
        draws = load_json_string(payload)
        self.assertEqual(draws[0], [1, 2, 3, 4, 5, 6])

    def test_non_list_rejected(self):
        with self.assertRaises(HistoryLoadError):
            load_json_string('{"draw": [1,2,3,4,5,6]}')

    def test_invalid_json(self):
        with self.assertRaises(HistoryLoadError):
            load_json_string("{not json")


class TestAuto(unittest.TestCase):
    def test_routes_to_json(self):
        payload = '[{"draw":[1,2,3,4,5,6]}]'
        draws = load_auto(payload)
        self.assertEqual(draws[0], [1, 2, 3, 4, 5, 6])

    def test_routes_to_csv(self):
        draws = load_auto(GOOD_CSV)
        self.assertEqual(len(draws), 2)


class TestPreviewRecent(unittest.TestCase):
    def test_csv_string_first_n_with_metadata(self):
        preview = preview_recent(GOOD_CSV, limit=5)
        self.assertEqual(len(preview), 2)
        self.assertEqual(preview[0]["term"], "115050")
        self.assertEqual(preview[0]["date"], "2026-05-09")
        self.assertEqual(preview[0]["nums"], [5, 12, 18, 25, 33, 42])
        self.assertEqual(preview[0]["special"], "7")

    def test_limit_clamps_to_smaller_count(self):
        preview = preview_recent(GOOD_CSV, limit=1)
        self.assertEqual(len(preview), 1)
        self.assertEqual(preview[0]["term"], "115050")

    def test_empty_input_returns_empty(self):
        self.assertEqual(preview_recent("", limit=5), [])
        self.assertEqual(preview_recent("   \n   ", limit=5), [])
        self.assertEqual(preview_recent(GOOD_CSV, limit=0), [])

    def test_bytes_input_decoded(self):
        preview = preview_recent(GOOD_CSV.encode("utf-8"), limit=5)
        self.assertEqual(len(preview), 2)

    def test_json_array_with_term_and_special(self):
        payload = json.dumps([
            {"draw": [1, 2, 3, 4, 5, 6], "term": "115050",
             "date": "2026-05-09", "special": 7},
        ])
        preview = preview_recent(payload, limit=5)
        self.assertEqual(len(preview), 1)
        self.assertEqual(preview[0]["term"], "115050")
        self.assertEqual(preview[0]["special"], "7")

    def test_malformed_input_returns_empty(self):
        # missing n1-n6 columns -> graceful empty (does not raise)
        self.assertEqual(
            preview_recent("foo,bar\n1,2\n", limit=5), []
        )


if __name__ == "__main__":
    unittest.main()
