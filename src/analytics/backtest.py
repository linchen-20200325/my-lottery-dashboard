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
from src.generator.domain import DomainConfig, LOTTO649, POWERBALL
from src.generator.lotto_picker import generate_tickets as _lotto_generate
from src.generator.powerball_picker import generate_tickets as _pb_generate

# Simplified prize table — 大樂透 white-ball only(忽略特別號分級;名目估算)。
# v6.24 B6:威力彩第二區 + 第一區雙池獎金結構不同,**不在此捏造**名目表
# (§1 Fail Loud / §3.3 反捏造)→ 威力彩回測只報 hit 分佈 + 成本,payout/ROI 為 None。
PRIZE_TWD: dict[int, int] = {
    6: 100_000_000,
    5: 150_000,
    4: 2_000,
    3: 400,
}


def _generate_for(
    dom: DomainConfig,
    history: list[list[int]],
    num_tickets: int,
    rng: random.Random,
) -> list[tuple[int, ...]]:
    """依樂透別 dispatch 至對應 picker;只取第一區 tickets(回測比對主號命中)。"""
    if dom is POWERBALL:
        tickets, _bonus, _ = _pb_generate(
            history_draws=history, num_tickets=num_tickets, rng=rng,
        )
    else:
        tickets, _ = _lotto_generate(
            history_draws=history, num_tickets=num_tickets, rng=rng,
        )
    return tickets


def _read_csv(
    path: Path, dom: DomainConfig = LOTTO649
) -> tuple[list[list[int]], list[str]]:
    """Load (nums, dates) preserving CSV order. Caller must verify newest-first."""
    out_nums: list[list[int]] = []
    out_dates: list[str] = []
    with path.open(newline="", encoding="utf-8") as fp:
        reader = csv.DictReader(fp)
        for row in reader:
            try:
                nums = sorted(int(row[f"n{i}"]) for i in range(1, dom.ticket_size + 1))
            except (KeyError, ValueError):
                continue
            if len(nums) == dom.ticket_size:
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
    dom: DomainConfig = LOTTO649,
) -> dict[str, object]:
    """回測第一區命中分佈。`dom` 預設大樂透;傳 POWERBALL 跑威力彩第一區。

    payout/ROI 僅在有名目獎金表時計算(目前僅大樂透);威力彩無 honest 主號
    獎金表 → payout/net/roi 為 None(§1 不捏造),只報 hit 分佈 + 成本。
    """
    prize_table = PRIZE_TWD if dom is LOTTO649 else None
    rows, dates = _read_csv(csv_path, dom)
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
            tickets = _generate_for(
                dom, history, tickets_per_draw, random.Random(rng.random()),
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
            if prize_table is not None:
                payout += prize_table.get(hits, 0)

    cost = total_tickets * UNIT_PRICE_TWD
    result: dict[str, object] = {
        "draws_evaluated": total_draws,
        "tickets_generated": total_tickets,
        "hit_distribution": dict(sorted(hit_counts.items())),
        "cost_twd": cost,
    }
    if prize_table is not None:
        result["payout_twd"] = payout
        result["net_twd"] = payout - cost
        result["roi_percent"] = (payout - cost) / cost * 100 if cost else 0.0
    else:
        # 威力彩:無 honest 名目獎金表 → 不捏造 payout/ROI(§1/§3.3)
        result["payout_twd"] = None
        result["net_twd"] = None
        result["roi_percent"] = None
    return result


def _format_report(result: dict[str, object]) -> str:
    lines = [
        "=== Picker Backtest (v3.0) ===",
        f"Draws evaluated     : {result['draws_evaluated']}",
        f"Tickets generated   : {result['tickets_generated']}",
        f"Cost (NT$)          : {result['cost_twd']:,}",
    ]
    if result["payout_twd"] is not None:
        lines += [
            f"Payout (NT$, capped): {result['payout_twd']:,}",
            f"Net (NT$)           : {result['net_twd']:,}",
            f"ROI                 : {result['roi_percent']:.2f}%",
        ]
    else:
        lines.append(
            "Payout / Net / ROI  : N/A（威力彩無 honest 名目獎金表,§1 不捏造)"
        )
    lines.append("Hit distribution    :")
    dist = result["hit_distribution"]
    assert isinstance(dist, dict)
    for k in sorted(dist):
        lines.append(f"  {k} hit(s): {dist[k]:>8}")
    lines.append(
        "Note: 頭獎為彩金分潤制，此處以名目上限估算；"
        "EV<0 為樂透數學本質，本回測僅作演算法行為審視。"
    )
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description="Offline backtest for v3.0 picker")
    ap.add_argument(
        "--lottery", choices=["lotto649", "powerball"], default="lotto649",
    )
    ap.add_argument("--csv", type=Path, default=None)
    ap.add_argument("--tickets-per-draw", type=int, default=5)
    ap.add_argument("--lookback", type=int, default=30)
    ap.add_argument("--seed", type=int, default=2026)
    args = ap.parse_args()

    dom = LOTTO649 if args.lottery == "lotto649" else POWERBALL
    csv_path = args.csv or Path(
        "data/lotto649.csv" if dom is LOTTO649 else "data/powerball.csv"
    )

    result = backtest(
        csv_path=csv_path,
        tickets_per_draw=args.tickets_per_draw,
        lookback=args.lookback,
        seed=args.seed,
        dom=dom,
    )
    print(_format_report(result))


if __name__ == "__main__":
    main()
