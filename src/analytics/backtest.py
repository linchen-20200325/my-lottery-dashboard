"""Offline hit-rate backtest for the 4-phase picker.

OFFLINE-ONLY: this module reads historical CSV produced by `src.scraper`.
It is NOT imported by `streamlit_app.py`. The live picker still operates under
§6 "no historical database" — backtest is a meta-evaluation of the algorithm,
not a predictor.

Usage:
    python -m src.analytics.backtest \\
        --csv data/lotto649.csv \\
        --tickets-per-draw 5 \\
        --seed 2026

Output: per-prize-tier hit count, ticket totals, return summary.
"""

from __future__ import annotations

import argparse
import csv
import random
from collections import Counter
from pathlib import Path

from src.analytics.cost_calc import UNIT_PRICE_TWD
from src.generator.lotto_picker import TICKET_SIZE, generate_tickets

# Taiwan Lotto 6/49 simplified prize table (NT$, rounded; ignores 二獎 special ball,
# since backtest evaluates the white-ball picker only).
PRIZE_TWD: dict[int, int] = {
    6: 100_000_000,  # 頭獎 — pari-mutuel; illustrative ceiling
    5: 150_000,      # 三獎 approx (no special ball in picker scope)
    4: 2_000,        # 四獎
    3: 400,          # 普獎 (五獎 approx)
}


def _read_csv(path: Path) -> list[tuple[str, list[int]]]:
    rows: list[tuple[str, list[int]]] = []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                nums = sorted(int(row[f"n{i}"]) for i in range(1, TICKET_SIZE + 1))
            except (KeyError, ValueError):
                continue
            if len(nums) != TICKET_SIZE:
                continue
            rows.append((row.get("draw_term", ""), nums))
    return rows


def backtest(
    csv_path: Path,
    tickets_per_draw: int = 5,
    seed: int = 2026,
    key_count: int = 2,
) -> dict[str, object]:
    """Walk historical draws, simulate picks against next draw, tally hits.

    For each draw i (i >= 1), use row[i-1] as previous_draw and pick the top
    `key_count` numbers from row[i-1] as keys (a naive policy). Generate
    `tickets_per_draw` tickets; count hits against row[i] white balls.
    """
    rows = _read_csv(csv_path)
    if len(rows) < 2:
        raise ValueError(f"need >=2 draws in CSV, got {len(rows)}")

    rng = random.Random(seed)
    hit_counts: Counter[int] = Counter()
    total_tickets = 0
    total_draws = 0
    payout = 0

    for i in range(1, len(rows)):
        prev = rows[i - 1][1]
        target = set(rows[i][1])
        # naive key policy: take first k numbers of prev draw
        keys = prev[:key_count]
        try:
            tickets = generate_tickets(
                previous_draw=prev,
                exclude_tails=[],
                key_nums=keys,
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
        "=== Lotto 6/49 Picker Backtest ===",
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
    ap = argparse.ArgumentParser(description="Offline backtest for picker")
    ap.add_argument("--csv", type=Path, default=Path("data/lotto649.csv"))
    ap.add_argument("--tickets-per-draw", type=int, default=5)
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--key-count", type=int, default=2)
    args = ap.parse_args()

    result = backtest(
        csv_path=args.csv,
        tickets_per_draw=args.tickets_per_draw,
        seed=args.seed,
        key_count=args.key_count,
    )
    print(_format_report(result))


if __name__ == "__main__":
    main()
