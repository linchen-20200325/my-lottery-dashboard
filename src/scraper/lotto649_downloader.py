"""Taiwan Lotto 6/49 historical fetcher (v3.0).

Thin wrapper over the `taiwanlottery` PyPI package
(https://pypi.org/project/taiwanlottery/). Iterates months backwards from
today and accumulates draws until `periods` records are collected.

This module is offline tooling: run it locally / in CI to refresh
`data/lotto649.csv`, then commit the CSV. Streamlit Cloud reads the CSV
checked into the repo (or accepts a manual upload via the UI).

CLI:
    python -m src.scraper.lotto649_downloader --periods 500
"""

from __future__ import annotations

import argparse
import csv
import logging
import sys
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Iterable

LOGGER = logging.getLogger("lotto649")
DEFAULT_OUTPUT = Path("data/lotto649.csv")
CSV_FIELDS = [
    "draw_term", "draw_date", "n1", "n2", "n3", "n4", "n5", "n6", "special",
]


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


def _parse_row(row: dict) -> Draw | None:
    nums = row.get("獎號") or row.get("drawNumber") or []
    if len(nums) < 6:
        return None
    try:
        return Draw(
            draw_term=str(row.get("期別") or row.get("period") or ""),
            draw_date=str(row.get("開獎日期") or row.get("lotteryDate") or "")[:10],
            n1=int(nums[0]), n2=int(nums[1]), n3=int(nums[2]),
            n4=int(nums[3]), n5=int(nums[4]), n6=int(nums[5]),
            special=int(row.get("特別號") or row.get("specialNumber") or 0),
        )
    except (TypeError, ValueError):
        return None


def fetch(periods: int = 500) -> list[Draw]:
    """Fetch up to `periods` recent draws (newest first)."""
    from TaiwanLottery import TaiwanLotteryCrawler  # lazy import for offline ok

    crawler = TaiwanLotteryCrawler()
    seen: set[str] = set()
    out: list[Draw] = []
    months = (periods + 7) // 8 + 2  # ~8 draws/month max; pad

    for year, month in _months_back(months):
        try:
            rows = crawler.lotto649(back_time=[year, month])
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Fetch %s-%s failed: %s", year, month, exc)
            continue
        for row in rows or []:
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
