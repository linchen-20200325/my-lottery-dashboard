"""One-shot: clear synthetic `draw_date` on 4-digit-term rows.

Background (STATE.md 第七層): CSV had 518 real lottery draws loaded with
fabricated `draw_date` values — every row's date sits in calendar 2026
regardless of the actual draw. New scraper rows (long-form term, e.g.
`115000053`) carry the true API date, but old 4-digit terms (`2446`, `2094`, …)
do not. The collision is silent and catastrophic: a fake row dated
`2026/5/19` squats the dedup key, so the real 5/19 draw from the API
gets dropped — `download() → added=0 → workflow green, CSV stale.`

Fix: clear the polluted dates to empty string. `download()` already filters
empty dates out of its `existing_dates` set (`if d.draw_date`), so real
dates from future fetches will land cleanly. The numbers themselves
(n1-n6 + special) are real and stay untouched — they feed the Z-score
engine which doesn't depend on dates.

Run once:
    python -m scripts.sanitize_legacy_dates
"""

from __future__ import annotations

import csv
from pathlib import Path

CSV_PATH = Path("data/lotto649.csv")
FIELDS = [
    "draw_term", "draw_date", "n1", "n2", "n3", "n4", "n5", "n6", "special",
]


def is_synthetic(term: str, date: str) -> bool:
    """Pollution = old-scheme 4-digit term + fabricated 2026 date.

    Real 4-digit terms span ~2014-2024 in the upstream lottery; their dates
    being uniformly 2026/* is the synthetic-data fingerprint. New API rows
    use ≥8-digit terms (e.g. `115000053`) and carry real dates.
    """
    return len(term) < 8 and date.startswith("2026")


def main() -> int:
    with CSV_PATH.open(encoding="utf-8", newline="") as fp:
        rows = list(csv.DictReader(fp))
    cleared = 0
    for r in rows:
        if is_synthetic(r["draw_term"], r["draw_date"]):
            r["draw_date"] = ""
            cleared += 1
    with CSV_PATH.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Cleared synthetic dates on {cleared} of {len(rows)} rows.")
    print(f"Remaining real-dated rows: {len(rows) - cleared}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
