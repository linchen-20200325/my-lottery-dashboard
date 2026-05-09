"""Taiwan Lotto 6/49 (大樂透) historical draw downloader.

Primary source: Taiwan Lottery official JSON API.
Fallback source: Pilio mirror (HTML table) - long-stable community mirror.

CLI:
    python -m src.scraper.lotto649_downloader --periods 500
"""

from __future__ import annotations

import argparse
import csv
import logging
import re
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

import requests
from bs4 import BeautifulSoup

LOGGER = logging.getLogger("lotto649")

# --- Constants ----------------------------------------------------------------

OFFICIAL_API = (
    "https://api.taiwanlottery.com.tw/TLCAPIWeB/Lottery/Lotto649Result"
)
PILIO_URL = "https://www.pilio.idv.tw/lto649/list.asp"

DEFAULT_OUTPUT = Path("data/lotto649.csv")
CSV_FIELDS = [
    "draw_term",
    "draw_date",
    "n1",
    "n2",
    "n3",
    "n4",
    "n5",
    "n6",
    "special",
]

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)
REQUEST_TIMEOUT = 15
RETRY_BACKOFF = (2, 4, 8, 16)


# --- Data model ---------------------------------------------------------------


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


# --- HTTP helper --------------------------------------------------------------


def _request(method: str, url: str, **kwargs) -> requests.Response:
    headers = kwargs.pop("headers", {})
    headers.setdefault("User-Agent", USER_AGENT)
    last_exc: Exception | None = None
    for attempt, backoff in enumerate((0, *RETRY_BACKOFF)):
        if backoff:
            time.sleep(backoff)
        try:
            resp = requests.request(
                method, url, headers=headers, timeout=REQUEST_TIMEOUT, **kwargs
            )
            resp.raise_for_status()
            return resp
        except requests.RequestException as exc:
            last_exc = exc
            LOGGER.warning(
                "Request failed (attempt %d): %s", attempt + 1, exc
            )
    raise RuntimeError(f"All retries exhausted for {url}: {last_exc}")


# --- Source: Official Taiwan Lottery API --------------------------------------


def fetch_official(periods: int) -> list[Draw]:
    """Fetch from Taiwan Lottery official JSON API.

    Endpoint paginates by `pageNum`/`pageSize`; we iterate until enough rows.
    """
    out: list[Draw] = []
    page_size = 50
    page = 1
    while len(out) < periods:
        params = {"pageNum": page, "pageSize": page_size}
        resp = _request("GET", OFFICIAL_API, params=params)
        try:
            data = resp.json()
        except ValueError as exc:
            raise RuntimeError("Official API returned non-JSON") from exc

        rows = (
            data.get("content", {}).get("lotto649Res")
            or data.get("content", {}).get("lottoRes")
            or []
        )
        if not rows:
            break

        for row in rows:
            draw = _parse_official_row(row)
            if draw is not None:
                out.append(draw)
            if len(out) >= periods:
                break
        page += 1
    return out


def _parse_official_row(row: dict) -> Draw | None:
    nums = (
        row.get("drawNumberSize")
        or row.get("drawNumberAppend")
        or row.get("drawNumber")
        or []
    )
    if len(nums) < 6:
        return None
    try:
        return Draw(
            draw_term=str(row.get("period") or row.get("drawTerm") or ""),
            draw_date=str(row.get("drwDate") or row.get("drawDate") or "")[:10],
            n1=int(nums[0]),
            n2=int(nums[1]),
            n3=int(nums[2]),
            n4=int(nums[3]),
            n5=int(nums[4]),
            n6=int(nums[5]),
            special=int(
                row.get("specialNumber") or row.get("drawNumberSpecial") or 0
            ),
        )
    except (TypeError, ValueError):
        return None


# --- Source: Pilio mirror (HTML) ---------------------------------------------

_DATE_RE = re.compile(r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})")
_TERM_RE = re.compile(r"(\d{6,})")


def fetch_pilio(periods: int) -> list[Draw]:
    """Fetch from Pilio mirror (well-known stable HTML table)."""
    resp = _request("GET", PILIO_URL)
    resp.encoding = resp.apparent_encoding or "big5"
    soup = BeautifulSoup(resp.text, "lxml")

    out: list[Draw] = []
    for tr in soup.find_all("tr"):
        cells = [c.get_text(strip=True) for c in tr.find_all(["td", "th"])]
        draw = _parse_pilio_row(cells)
        if draw is not None:
            out.append(draw)
            if len(out) >= periods:
                break
    return out


def _parse_pilio_row(cells: list[str]) -> Draw | None:
    if len(cells) < 9:
        return None
    date_match = _DATE_RE.search(cells[0])
    term_match = _TERM_RE.search(cells[1]) if len(cells) > 1 else None
    if not date_match or not term_match:
        return None
    try:
        nums = [int(c) for c in cells[2:8]]
        special = int(cells[8])
    except ValueError:
        return None
    yyyy, mm, dd = date_match.groups()
    return Draw(
        draw_term=term_match.group(1),
        draw_date=f"{yyyy}-{int(mm):02d}-{int(dd):02d}",
        n1=nums[0], n2=nums[1], n3=nums[2],
        n4=nums[3], n5=nums[4], n6=nums[5],
        special=special,
    )


# --- CSV I/O ------------------------------------------------------------------


def load_existing(path: Path) -> dict[str, Draw]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8", newline="") as fp:
        reader = csv.DictReader(fp)
        out: dict[str, Draw] = {}
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
            out[draw.draw_term] = draw
    return out


def save_csv(draws: Iterable[Draw], path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = sorted(draws, key=lambda d: d.draw_term, reverse=True)
    with path.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for d in rows:
            writer.writerow(asdict(d))
    return len(rows)


# --- Orchestration ------------------------------------------------------------


def download(
    periods: int = 500,
    output: Path = DEFAULT_OUTPUT,
    source: str = "auto",
) -> int:
    """Download `periods` historical draws and merge into `output` CSV.

    Returns total number of unique draws stored.
    """
    sources = {
        "official": [fetch_official],
        "pilio": [fetch_pilio],
        "auto": [fetch_official, fetch_pilio],
    }[source]

    fetched: list[Draw] = []
    for fn in sources:
        try:
            LOGGER.info("Fetching via %s ...", fn.__name__)
            fetched = fn(periods)
            if fetched:
                LOGGER.info("Fetched %d draws via %s", len(fetched), fn.__name__)
                break
        except Exception as exc:  # noqa: BLE001  - try next source
            LOGGER.warning("%s failed: %s", fn.__name__, exc)

    if not fetched:
        raise RuntimeError("All sources failed; no data downloaded.")

    existing = load_existing(output)
    merged = {**existing}
    for d in fetched:
        merged[d.draw_term] = d  # newer pull wins on conflict

    return save_csv(merged.values(), output)


# --- CLI ----------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Download Lotto 6/49 history.")
    p.add_argument("--periods", type=int, default=500, help="Number of periods (default: 500)")
    p.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output CSV path")
    p.add_argument(
        "--source",
        choices=["auto", "official", "pilio"],
        default="auto",
        help="Data source (default: auto = official then pilio fallback)",
    )
    p.add_argument("-v", "--verbose", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    try:
        total = download(args.periods, args.output, args.source)
    except Exception as exc:  # noqa: BLE001
        LOGGER.error("Download failed: %s", exc)
        return 1
    LOGGER.info("OK. %d unique draws stored at %s", total, args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
