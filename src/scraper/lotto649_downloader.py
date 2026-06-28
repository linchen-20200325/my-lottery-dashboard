"""Taiwan Lotto 6/49 historical fetcher (v3.1 — direct API).

Direct call to the official Taiwan Lottery API
(`https://api.taiwanlottery.com/TLCAPIWeB/Lottery/Lotto649Result`),
bypassing the fragile `taiwanlottery` PyPI wrapper. Iterates months
backwards from today and accumulates draws until `periods` records
are collected.

Why direct: the upstream wrapper calls `response.json()` with no
User-Agent / retry / timeout / diagnostic logging — when the API
returns HTML or empty body (cloud-IP block, rate limit, transient
outage), it dies with a cryptic `JSONDecodeError` and the workflow
opens an issue with zero context. This rewrite adds: browser UA,
status/body preview on parse failure, retry adapter (4xx/5xx),
and an outer retry loop for transient JSON-decode errors.

This module is offline tooling: run it locally / in CI to refresh
`data/lotto649.csv`, then commit the CSV. Streamlit Cloud reads the
CSV checked into the repo (or accepts a manual upload via the UI);
the live app never makes outbound API calls (CLAUDE.md §3).

CLI:
    python -m src.scraper.lotto649_downloader --periods 500
"""

from __future__ import annotations

import argparse
import csv
import logging
import sys
import time
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Iterable

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from src.scraper._dates import canon_date

LOGGER = logging.getLogger("lotto649")
DEFAULT_OUTPUT = Path("data/lotto649.csv")
CSV_FIELDS = [
    "draw_term", "draw_date", "n1", "n2", "n3", "n4", "n5", "n6", "special",
]

API_BASE = "https://api.taiwanlottery.com/TLCAPIWeB/Lottery"
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
    "Referer": "https://www.taiwanlottery.com/",
}
REQUEST_TIMEOUT = 15  # seconds
JSON_RETRY_ATTEMPTS = 3
JSON_RETRY_BACKOFF = 2.0  # seconds, exponential
# HTTP-layer retry (urllib3 adapter); semantically distinct from JSON_RETRY_* which
# handles application-level decode errors. Keep separate even if values coincide.
HTTP_RETRY_TOTAL = 3
HTTP_RETRY_BACKOFF = 2.0
# Per-month API request: 31 days = max possible draw count window per calendar month.
API_PAGE_SIZE = 31
# 大樂透每月最多 ~8 期（週 2 開獎 × 4-5 週）;buffer 2 個月容納跨月邊界。
MAX_DRAWS_PER_MONTH = 8
MONTHS_BUFFER = 2


def _canon_date(s: str) -> str:
    """Delegates to scraper._dates.canon_date — single source (REFACTOR_AUDIT §5.3)."""
    return canon_date(s)


@dataclass(frozen=True)
class Draw:
    draw_term: str
    draw_date: str
    n1: int
    n2: int
    n3: int
    n4: int
    n5: int
    n6: int
    special: int


def _months_back(n_months: int) -> list[tuple[str, str]]:
    today = date.today()
    y, m = today.year, today.month
    out: list[tuple[str, str]] = []
    for _ in range(n_months):
        out.append((f"{y:04d}", f"{m:02d}"))
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    return out


def _build_session() -> requests.Session:
    """Session with browser UA + retry adapter (429/5xx)."""
    sess = requests.Session()
    sess.headers.update(DEFAULT_HEADERS)
    retry = Retry(
        total=HTTP_RETRY_TOTAL,
        backoff_factor=HTTP_RETRY_BACKOFF,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
        raise_on_status=False,
    )
    sess.mount("https://", HTTPAdapter(max_retries=retry))
    return sess


def _fetch_month_raw(sess: requests.Session, year: str, month: str) -> list[dict]:
    """Call API for one month; returns raw row list. Retries on JSON decode failures."""
    url = f"{API_BASE}/Lotto649Result?period&month={year}-{month}&pageSize={API_PAGE_SIZE}"
    last_err: Exception | None = None
    for attempt in range(JSON_RETRY_ATTEMPTS):
        resp = sess.get(url, timeout=REQUEST_TIMEOUT)
        if resp.status_code != 200:
            LOGGER.warning(
                "API %s-%s HTTP %s (attempt %d/%d): %r",
                year, month, resp.status_code, attempt + 1, JSON_RETRY_ATTEMPTS,
                resp.content[:200],
            )
            last_err = RuntimeError(f"HTTP {resp.status_code}")
        else:
            try:
                payload = resp.json()
            except ValueError as exc:
                LOGGER.warning(
                    "API %s-%s JSON parse failed (attempt %d/%d). "
                    "Content-Type=%s. Body preview: %r",
                    year, month, attempt + 1, JSON_RETRY_ATTEMPTS,
                    resp.headers.get("content-type", "?"),
                    resp.content[:200],
                )
                last_err = exc
            else:
                content = payload.get("content") if isinstance(payload, dict) else None
                rows = (content or {}).get("lotto649Res") or []
                return list(rows)
        if attempt < JSON_RETRY_ATTEMPTS - 1:
            time.sleep(JSON_RETRY_BACKOFF * (2 ** attempt))
    raise RuntimeError(f"All {JSON_RETRY_ATTEMPTS} attempts failed: {last_err}")


def _parse_row(row: dict) -> Draw | None:
    """Parse one API row (or legacy taiwanlottery shape) into a Draw."""
    # Direct API shape: drawNumberSize is a list of 7 ints (6 main + 1 special).
    # Legacy taiwanlottery shape: 獎號 (list[6]) + 特別號 (int).
    nums = row.get("獎號")
    special = row.get("特別號")
    if nums is None:
        dn = row.get("drawNumberSize") or []
        if len(dn) >= 7:
            nums = dn[:6]
            special = dn[6]
    if not nums or len(nums) < 6:
        return None
    try:
        return Draw(
            draw_term=str(row.get("期別") or row.get("period") or ""),
            draw_date=_canon_date(str(row.get("開獎日期") or row.get("lotteryDate") or "")),
            n1=int(nums[0]), n2=int(nums[1]), n3=int(nums[2]),
            n4=int(nums[3]), n5=int(nums[4]), n6=int(nums[5]),
            special=int(special or 0),
        )
    except (TypeError, ValueError):
        return None


def fetch(periods: int = 500, session: requests.Session | None = None) -> list[Draw]:
    """Fetch up to `periods` recent draws (newest first).

    `session` is injectable for tests; defaults to a fresh hardened session.

    Current-month (idx=0) failure is fatal — that's how stale data slips through
    cron silently: if Cloudflare blocks the runner IP on May fetch but April
    still works, `fetched` ends up full of already-known draws, `download()`
    reports "added=0", and the workflow goes green with no new lottery data.
    Raise on idx=0 so the workflow turns red and opens an issue with diagnostics.
    """
    sess = session or _build_session()
    seen: set[str] = set()
    out: list[Draw] = []
    # ceil(periods / MAX_DRAWS_PER_MONTH) + MONTHS_BUFFER
    months = (
        (periods + MAX_DRAWS_PER_MONTH - 1) // MAX_DRAWS_PER_MONTH
        + MONTHS_BUFFER
    )

    for idx, (year, month) in enumerate(_months_back(months)):
        try:
            rows = _fetch_month_raw(sess, year, month)
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Fetch %s-%s failed: %s", year, month, exc)
            if idx == 0:
                raise RuntimeError(
                    f"Current month {year}-{month} fetch failed after retries: {exc}. "
                    "Likely Cloudflare / IP block on the Actions runner — see the "
                    "scraper log tail in the auto-opened issue body for HTTP status "
                    "and body preview."
                ) from exc
            continue
        LOGGER.info("Month %s-%s: API returned %d row(s)", year, month, len(rows))
        for row in rows:
            draw = _parse_row(row)
            if draw is None or draw.draw_term in seen:
                continue
            seen.add(draw.draw_term)
            out.append(draw)
            if len(out) >= periods:
                return out
    return out


def load_existing(path: Path) -> dict[str, Draw]:
    """Load existing CSV keyed by `draw_term` (preserves history as-is)."""
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8", newline="") as fp:
        reader = csv.DictReader(fp)
        merged: dict[str, Draw] = {}
        for row in reader:
            try:
                draw = Draw(
                    draw_term=row["draw_term"],
                    draw_date=row["draw_date"],
                    n1=int(row["n1"]), n2=int(row["n2"]), n3=int(row["n3"]),
                    n4=int(row["n4"]), n5=int(row["n5"]), n6=int(row["n6"]),
                    special=int(row["special"]),
                )
            except (KeyError, ValueError):
                continue
            if draw.draw_term in merged:
                # CLAUDE.md §4.6:重複 draw_term 過去沉默 overwrite。
                # 警告但保留 last-write-wins 行為避免破壞既有 CSV(append-only 是
                # download() 端的合約,load 端只負責讀)。
                LOGGER.warning(
                    "duplicate draw_term=%s in CSV — last row wins (data integrity issue?)",
                    draw.draw_term,
                )
            merged[draw.draw_term] = draw
    return merged


def _term_sort_key(term: str) -> tuple[int, int]:
    """Scheme-aware sort key for `draw_term`.

    Official API switched mid-history from 4-digit (e.g. `'2446'`) to long-form
    (e.g. `'115000053'`). String-sort reverse puts long-form AFTER 4-digit
    (`'1' < '2'`), so the newest real draw ends up at the bottom. The historical
    CSV also has unreliable `draw_date` years (some rows hardcode '2026' across
    multi-year synthetic data), so we can't sort by date either.

    Rule: long-form scheme (len >= 8) sits in bucket 2 — always newer than any
    4-digit term (bucket 1). Within each bucket, sort by integer term value.
    Unparseable terms drop to bucket 0 (file tail).
    """
    if len(term) >= 8:
        try:
            return (2, int(term))
        except ValueError:
            return (0, 0)
    try:
        return (1, int(term))
    except ValueError:
        return (0, 0)


def save_csv(draws: Iterable[Draw], path: Path) -> int:
    """Append-safe CSV writer; sorts newest-first via `_term_sort_key`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = sorted(draws, key=lambda d: _term_sort_key(d.draw_term), reverse=True)
    with path.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for d in rows:
            writer.writerow(asdict(d))
    return len(rows)


def download(periods: int = 500, output: Path = DEFAULT_OUTPUT) -> int:
    """Append-only merge: skip API rows whose canonical date matches any existing row.

    Why date-based skip (not term-based merge): official API switched draw_term scheme
    from traditional 4-digit (e.g. '2446') to internal long form (e.g. '115000052').
    Pure term-keyed dedup would treat these as different draws and bloat the CSV.
    Date is the stable identity. Existing rows are NEVER overwritten — even if their
    `draw_date` field is malformed, they stay untouched.
    """
    fetched = fetch(periods)
    if not fetched:
        raise RuntimeError(
            "Fetch returned no data. Network blocked? Use UI manual upload."
        )
    existing = load_existing(output)
    existing_dates = {_canon_date(d.draw_date) for d in existing.values() if d.draw_date}

    fetched_max = max(
        (_canon_date(d.draw_date) for d in fetched if d.draw_date),
        default="",
    )
    existing_max = max(existing_dates, default="")
    LOGGER.info(
        "Diagnostic: fetched=%d (max_date=%s) | existing=%d (max_date=%s)",
        len(fetched), fetched_max or "?", len(existing), existing_max or "?",
    )

    merged: dict[str, Draw] = dict(existing)
    added = 0
    for d in fetched:
        canon = _canon_date(d.draw_date)
        if canon and canon in existing_dates:
            continue  # same date already in CSV — skip regardless of term scheme
        if d.draw_term in merged:
            continue  # extra safety against term-level collision
        merged[d.draw_term] = d
        existing_dates.add(canon)
        added += 1
    LOGGER.info("Added %d new draw(s) (existing kept: %d)", added, len(existing))
    # §4.2 不變量:append-only — merged 不得少於 existing(永不覆蓋現有列)
    assert len(merged) >= len(existing), \
        f"append-only violated: merged={len(merged)} < existing={len(existing)}"
    return save_csv(merged.values(), output)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Refresh Lotto 6/49 historical CSV")
    ap.add_argument("--periods", type=int, default=500)
    ap.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    try:
        total = download(args.periods, args.output)
    except Exception as exc:  # noqa: BLE001
        LOGGER.error("Download failed: %s", exc)
        return 1
    LOGGER.info("OK. %d draws stored at %s", total, args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
