"""Unit tests for src.scraper.lotto649_downloader (no network)."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from src.scraper import lotto649_downloader as scraper


def _mk_resp(status: int, body, content_type: str = "application/json"):
    resp = MagicMock()
    resp.status_code = status
    resp.headers = {"content-type": content_type}
    if isinstance(body, (bytes, bytearray)):
        resp.content = bytes(body)
        resp.json.side_effect = ValueError("not json")
    else:
        resp.content = repr(body).encode("utf-8")
        resp.json.return_value = body
    return resp


SAMPLE_PAYLOAD = {
    "content": {
        "totalSize": 2,
        "lotto649Res": [
            {
                "period": "2446",
                "lotteryDate": "2026-05-12T00:00:00",
                "drawNumberSize": [6, 12, 18, 19, 32, 36, 34],
            },
            {
                "period": "2447",
                "lotteryDate": "2026-05-15T00:00:00",
                "drawNumberSize": [3, 8, 22, 27, 41, 45, 17],
            },
        ],
    }
}


class TestParseRow(unittest.TestCase):
    def test_direct_api_shape(self):
        row = SAMPLE_PAYLOAD["content"]["lotto649Res"][0]
        d = scraper._parse_row(row)
        self.assertIsNotNone(d)
        self.assertEqual(d.draw_term, "2446")
        self.assertEqual(d.draw_date, "2026/05/12")  # _parse_row canonicalizes for new fetches
        self.assertEqual((d.n1, d.n2, d.n3, d.n4, d.n5, d.n6), (6, 12, 18, 19, 32, 36))
        self.assertEqual(d.special, 34)

    def test_legacy_taiwanlottery_shape(self):
        row = {
            "期別": "2445",
            "開獎日期": "2026-05-08",
            "獎號": [10, 18, 25, 28, 39, 43],
            "特別號": 48,
        }
        d = scraper._parse_row(row)
        self.assertIsNotNone(d)
        self.assertEqual(d.draw_term, "2445")
        self.assertEqual(d.special, 48)

    def test_invalid_short_nums(self):
        self.assertIsNone(scraper._parse_row({"drawNumberSize": [1, 2, 3]}))
        self.assertIsNone(scraper._parse_row({"獎號": []}))
        self.assertIsNone(scraper._parse_row({}))


class TestFetchMonthRaw(unittest.TestCase):
    def test_success_returns_rows(self):
        sess = MagicMock()
        sess.get.return_value = _mk_resp(200, SAMPLE_PAYLOAD)
        rows = scraper._fetch_month_raw(sess, "2026", "05")
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["period"], "2446")

    def test_http_error_retries_then_raises(self):
        sess = MagicMock()
        sess.get.return_value = _mk_resp(403, b"Host not in allowlist", "text/plain")
        with patch.object(scraper.time, "sleep") as sleep:  # don't actually wait
            with self.assertRaises(RuntimeError) as cm:
                scraper._fetch_month_raw(sess, "2026", "05")
        self.assertEqual(sess.get.call_count, scraper.JSON_RETRY_ATTEMPTS)
        self.assertIn("HTTP 403", str(cm.exception))
        self.assertEqual(sleep.call_count, scraper.JSON_RETRY_ATTEMPTS - 1)

    def test_json_decode_failure_retries(self):
        sess = MagicMock()
        sess.get.return_value = _mk_resp(200, b"<html>nope</html>", "text/html")
        with patch.object(scraper.time, "sleep"):
            with self.assertRaises(RuntimeError):
                scraper._fetch_month_raw(sess, "2026", "05")
        self.assertEqual(sess.get.call_count, scraper.JSON_RETRY_ATTEMPTS)

    def test_recovers_on_second_attempt(self):
        sess = MagicMock()
        sess.get.side_effect = [
            _mk_resp(503, b"upstream timeout", "text/plain"),
            _mk_resp(200, SAMPLE_PAYLOAD),
        ]
        with patch.object(scraper.time, "sleep"):
            rows = scraper._fetch_month_raw(sess, "2026", "05")
        self.assertEqual(len(rows), 2)
        self.assertEqual(sess.get.call_count, 2)

    def test_empty_content_returns_empty_list(self):
        sess = MagicMock()
        sess.get.return_value = _mk_resp(200, {"content": None})
        rows = scraper._fetch_month_raw(sess, "2026", "05")
        self.assertEqual(rows, [])


class TestFetch(unittest.TestCase):
    def test_fetch_dedupes_across_months(self):
        sess = MagicMock()
        # Every month returns the same 2 rows; fetch() must dedupe by draw_term
        sess.get.return_value = _mk_resp(200, SAMPLE_PAYLOAD)
        out = scraper.fetch(periods=10, session=sess)
        self.assertEqual(len(out), 2)
        self.assertEqual({d.draw_term for d in out}, {"2446", "2447"})

    def test_fetch_stops_at_periods_limit(self):
        # 5 distinct rows across months; cap at 3
        rows_a = {
            "content": {
                "lotto649Res": [
                    {"period": "100", "lotteryDate": "2026-01-01",
                     "drawNumberSize": [1, 2, 3, 4, 5, 6, 7]},
                    {"period": "101", "lotteryDate": "2026-01-04",
                     "drawNumberSize": [2, 3, 4, 5, 6, 7, 8]},
                ]
            }
        }
        rows_b = {
            "content": {
                "lotto649Res": [
                    {"period": "102", "lotteryDate": "2026-01-08",
                     "drawNumberSize": [3, 4, 5, 6, 7, 8, 9]},
                    {"period": "103", "lotteryDate": "2026-01-11",
                     "drawNumberSize": [4, 5, 6, 7, 8, 9, 10]},
                ]
            }
        }
        sess = MagicMock()
        sess.get.side_effect = [_mk_resp(200, rows_a), _mk_resp(200, rows_b)]
        out = scraper.fetch(periods=3, session=sess)
        self.assertEqual(len(out), 3)


class TestCanonDate(unittest.TestCase):
    def test_slash_no_zero_pad(self):
        self.assertEqual(scraper._canon_date("2026/5/12"), "2026/05/12")

    def test_dash_iso(self):
        self.assertEqual(scraper._canon_date("2026-05-15"), "2026/05/15")

    def test_iso_with_time(self):
        self.assertEqual(scraper._canon_date("2026-05-15T22:00:00"), "2026/05/15")

    def test_empty(self):
        self.assertEqual(scraper._canon_date(""), "")

    def test_garbage_returns_input(self):
        self.assertEqual(scraper._canon_date("not-a-date"), "not-a-date")


class TestDownloadDedupByDate(unittest.TestCase):
    """Critical: existing CSV (old term '2446') + API (new term '115000052') for
    SAME date must NOT produce two rows. Dedup key is `draw_date`, not `draw_term`."""

    def test_no_duplicate_when_terms_differ_but_date_matches(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "lotto.csv"
            csv_path.write_text(
                "draw_term,draw_date,n1,n2,n3,n4,n5,n6,special\n"
                "2446,2026/5/12,6,12,18,19,32,36,34\n"
                "2445,2026/5/8,10,18,25,28,39,43,48\n",
                encoding="utf-8",
            )
            api_draws = [
                # Same date as existing 2446 but with new term scheme — must skip
                scraper.Draw(draw_term="115000052", draw_date="2026/05/12",
                             n1=6, n2=12, n3=18, n4=19, n5=32, n6=36, special=34),
                # New date — must add
                scraper.Draw(draw_term="115000053", draw_date="2026/05/15",
                             n1=16, n2=29, n3=30, n4=35, n5=42, n6=43, special=1),
            ]
            with patch.object(scraper, "fetch", return_value=api_draws):
                count = scraper.download(periods=10, output=csv_path)

            # 2 existing + 1 new = 3 (NOT 4 — 2026/5/12 must dedupe across term schemes)
            self.assertEqual(count, 3)
            content = csv_path.read_text(encoding="utf-8")
            self.assertIn("2026/05/15", content)  # new draw added
            self.assertNotIn("115000052", content)  # duplicate date skipped
            self.assertIn("2446,2026/5/12", content)  # existing row untouched

    def test_existing_rows_unchanged_even_if_malformed(self):
        """If existing CSV has dates that fail _canon_date (e.g. garbage),
        they stay in the file — we never destroy history."""
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "lotto.csv"
            csv_path.write_text(
                "draw_term,draw_date,n1,n2,n3,n4,n5,n6,special\n"
                "9999,not-a-date,1,2,3,4,5,6,7\n",
                encoding="utf-8",
            )
            with patch.object(scraper, "fetch", return_value=[
                scraper.Draw("115000053", "2026/05/15", 16, 29, 30, 35, 42, 43, 1)
            ]):
                count = scraper.download(periods=10, output=csv_path)
            self.assertEqual(count, 2)  # garbage row preserved + new added
            content = csv_path.read_text(encoding="utf-8")
            self.assertIn("9999,not-a-date", content)


class TestSessionBuilder(unittest.TestCase):
    def test_has_ua_and_referer(self):
        sess = scraper._build_session()
        self.assertIn("Mozilla", sess.headers["User-Agent"])
        self.assertEqual(sess.headers["Referer"], "https://www.taiwanlottery.com/")
        self.assertIn("application/json", sess.headers["Accept"])

    def test_https_adapter_mounted(self):
        sess = scraper._build_session()
        self.assertIn("https://", sess.adapters)


if __name__ == "__main__":
    unittest.main()
