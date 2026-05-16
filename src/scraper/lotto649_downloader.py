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
        total=3,
        backoff_factor=2.0,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
        raise_on_status=False,
    )
    sess.mount("https://", HTTPAdapter(max_retries=retry))
    return sess


def _fetch_month_raw(sess: requests.Session, year: str, month: str) -> list[dict]:
    """Call API for one month; returns raw row list. Retries on JSON decode failures."""
    url = f"{API_BASE}/Lotto649Result?period&month={year}-{month}&pageSize=31"
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
            draw_date=str(row.get("開獎日期") or row.get("lotteryDate") or "")[:10],
            n1=int(nums[0]), n2=int(nums[1]), n3=int(nums[2]),
            n4=int(nums[3]), n5=int(nums[4]), n6=int(nums[5]),
            special=int(special or 0),
        )
    except (TypeError, ValueError):
        return None


def fetch(periods: int = 500, session: requests.Session | None = None) -> list[Draw]:
    """Fetch up to `periods` recent draws (newest first).

    `session` is injectable for tests; defaults to a fresh hardened session.
    """
    sess = session or _build_session()
    seen: set[str] = set()
    out: list[Draw] = []
    months = (periods + 7) // 8 + 2  # ~8 draws/month max; pad

    for year, month in _months_back(months):
        try:
            rows = _fetch_month_raw(sess, year, month)
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Fetch %s-%s failed: %s", year, month, exc)
            continue
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
            merged[draw.draw_term] = draw
    return merged


def save_csv(draws: Iterable[Draw], path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = sorted(draws, key=lambda d: d.draw_term, reverse=True)
    with path.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for d in rows:
            writer.writerow(asdict(d))
    return len(rows)


def download(periods: int = 500, output: Path = DEFAULT_OUTPUT) -> int:
    fetched = fetch(periods)
    if not fetched:
        raise RuntimeError(
            "Fetch returned no data. Network blocked? Use UI manual upload."
        )
    existing = load_existing(output)
    merged = {**existing}
    for d in fetched:
        merged[d.draw_term] = d
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
