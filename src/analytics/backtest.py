"""Offline hit-rate backtest for the v3.0 dynamic picker.

OFFLINE-ONLY: reads historical CSV produced by `src.scraper`.
NOT imported by `streamlit_app.py`. Backtest is a meta-evaluation of the
algorithm; EV<0 is still the math reality of lotteries.

For each evaluation point at index k in the CSV (newest first):
  target  = rows[k]
  history = rows[k+1 : k+1+lookback]  (the data that would have been
                                       available at the time of that draw)

Usage:
    python -m src.analytics.backtest \\
        --csv data/lotto649.csv \\
        --tickets-per-draw 5 \\
        --lookback 30 \\
        --seed 2026
"""

from __future__ import annotations

import argparse
import csv
import random
from collections import Counter
from pathlib import Path

from src.analytics.cost_calc import UNIT_PRICE_TWD
from src.generator.lotto_picker import TICKET_SIZE, generate_tickets

# Simplified prize table (white-ball only; ignores special-ball tiers)
PRIZE_TWD: dict[int, int] = {
    6: 100_000_000,
    5: 150_000,
    4: 2_000,
    3: 400,
}


def _read_csv(path: Path) -> tuple[list[list[int]], list[str]]:
    """Load (nums, dates) preserving CSV order. Caller must verify newest-first."""
    out_nums: list[list[int]] = []
    out_dates: list[str] = []
    with path.open(newline="", encoding="utf-8") as fp:
        reader = csv.DictReader(fp)
        for row in reader:
            try:
                nums = sorted(int(row[f"n{i}"]) for i in range(1, TICKET_SIZE + 1))
            except (KeyError, ValueError):
                continue
            if len(nums) == TICKET_SIZE:
                out_nums.append(nums)
                out_dates.append(row.get("draw_date", ""))
    return out_nums, out_dates


def _assert_newest_first(dates: list[str]) -> None:
    """v6.3 — Guard against silent lookahead.

    Backtest semantics require `rows[0]` to be the latest draw so that
    `history = rows[k+1 : k+1+lookback]` is strictly older than `target = rows[k]`.
    If CSV is oldest-first, the loop predicts the past using future draws —
    silent data corruption with no exception.
    """
    nonempty = [d for d in dates if d]
    if len(nonempty) < 2:
        return  # not enough signal to check
    if nonempty[0] < nonempty[-1]:
        raise ValueError(
            "CSV must be sorted newest-first (rows[0] = latest draw); "
            f"got rows[0]={nonempty[0]!r} < rows[-1]={nonempty[-1]!r}. "
            "Re-export via src.scraper.lotto649_downloader (auto newest-first)."
        )


def backtest(
    csv_path: Path,
    tickets_per_draw: int = 5,
    lookback: int = 30,
    seed: int = 2026,
) -> dict[str, object]:
    rows, dates = _read_csv(csv_path)
    _assert_newest_first(dates)
    if len(rows) < lookback + 2:
        raise ValueError(
            f"need >= {lookback + 2} draws in CSV, got {len(rows)}"
        )
    rng = random.Random(seed)
    hit_counts: Counter[int] = Counter()
    total_tickets = 0
    total_draws = 0
    payout = 0

    for k in range(len(rows) - lookback - 1):
        target = set(rows[k])
        history = rows[k + 1 : k + 1 + lookback]
        try:
            tickets, _ = generate_tickets(
                history_draws=history,
                num_tickets=tickets_per_draw,
                rng=random.Random(rng.random()),
            )
        except ValueError:
            continue
        if not tickets:
            continue
        total_draws += 1
        for t in tickets:
            total_tickets += 1
            hits = len(set(t) & target)
            hit_counts[hits] += 1
            payout += PRIZE_TWD.get(hits, 0)

    cost = total_tickets * UNIT_PRICE_TWD
    return {
        "draws_evaluated": total_draws,
        "tickets_generated": total_tickets,
        "hit_distribution": dict(sorted(hit_counts.items())),
        "cost_twd": cost,
        "payout_twd": payout,
        "net_twd": payout - cost,
        "roi_percent": (payout - cost) / cost * 100 if cost else 0.0,
    }


def _format_report(result: dict[str, object]) -> str:
    lines = [
        "=== Lotto 6/49 Picker Backtest (v3.0) ===",
        f"Draws evaluated     : {result['draws_evaluated']}",
        f"Tickets generated   : {result['tickets_generated']}",
        f"Cost (NT$)          : {result['cost_twd']:,}",
        f"Payout (NT$, capped): {result['payout_twd']:,}",
        f"Net (NT$)           : {result['net_twd']:,}",
        f"ROI                 : {result['roi_percent']:.2f}%",
        "Hit distribution    :",
    ]
    dist = result["hit_distribution"]
    assert isinstance(dist, dict)
    for k in sorted(dist):
        lines.append(f"  {k} hit(s): {dist[k]:>8}")
    lines.append(
        "Note: 頭獎為彩金分潤制，此處以名目上限估算；"
        "EV<0 為大樂透數學本質，本回測僅作演算法行為審視。"
    )
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description="Offline backtest for v3.0 picker")
    ap.add_argument("--csv", type=Path, default=Path("data/lotto649.csv"))
    ap.add_argument("--tickets-per-draw", type=int, default=5)
    ap.add_argument("--lookback", type=int, default=30)
    ap.add_argument("--seed", type=int, default=2026)
    args = ap.parse_args()

    result = backtest(
        csv_path=args.csv,
        tickets_per_draw=args.tickets_per_draw,
        lookback=args.lookback,
        seed=args.seed,
    )
    print(_format_report(result))


if __name__ == "__main__":
    main()
