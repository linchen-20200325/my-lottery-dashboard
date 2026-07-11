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
    *,
    batch_disjoint: bool = False,
    howard_mode: bool = False,
    signal_params: dict | None = None,
) -> list[tuple[int, ...]]:
    """依樂透別 dispatch 至對應 picker;只取第一區 tickets(回測比對主號命中)。

    `batch_disjoint`:組與組之間 6 號完全不重複。
    `howard_mode`:霍華德嚴格模式(**僅大樂透**;威力彩無此策略,忽略)。
    `signal_params`:訊號參數 dict(hot_sigma_factor / sum_sma_window / … ),透傳
        `generate_tickets`;None → 引擎預設。**不含手動膽碼/排除**(乾淨策略回測)。
    """
    sp = signal_params or {}
    if dom is POWERBALL:
        tickets, _bonus, _ = _pb_generate(
            history_draws=history, num_tickets=num_tickets, rng=rng,
            batch_disjoint=batch_disjoint, **sp,
        )
    else:
        tickets, _ = _lotto_generate(
            history_draws=history, num_tickets=num_tickets, rng=rng,
            batch_disjoint=batch_disjoint, howard_mode=howard_mode, **sp,
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
    *,
    batch_disjoint: bool = False,
    howard_mode: bool = False,
    max_periods: int | None = None,
    signal_params: dict | None = None,
) -> dict[str, object]:
    """回測第一區命中分佈。`dom` 預設大樂透;傳 POWERBALL 跑威力彩第一區。

    每期 target = rows[k]、history = rows[k+1:k+1+lookback](嚴格較舊;防 lookahead)。
    `max_periods`:只評估最近 N 期(k 由 0=最新期起算);None = 全部可評估期。
    `batch_disjoint` / `howard_mode`(僅大樂透) / `signal_params` 透傳選號器
    (§7 對齊:乾淨策略回測,不套手動膽碼/排除)。

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
    n_eval = len(rows) - lookback - 1
    if max_periods is not None:
        if max_periods < 1:
            raise ValueError("max_periods must be >= 1")
        n_eval = min(n_eval, max_periods)

    rng = random.Random(seed)
    hit_counts: Counter[int] = Counter()      # 每「注」的命中分佈
    draws_best: Counter[int] = Counter()      # 每「期」最佳一注的命中分佈
    total_tickets = 0
    total_draws = 0
    payout = 0
    sample: dict | None = None                # 第一個評估期(最新期)的實選注範例

    for k in range(n_eval):
        target = set(rows[k])
        history = rows[k + 1 : k + 1 + lookback]
        try:
            tickets = _generate_for(
                dom, history, tickets_per_draw, random.Random(rng.random()),
                batch_disjoint=batch_disjoint, howard_mode=howard_mode,
                signal_params=signal_params,
            )
        except ValueError:
            continue
        if not tickets:
            continue
        total_draws += 1
        best = 0
        for t in tickets:
            total_tickets += 1
            hits = len(set(t) & target)
            hit_counts[hits] += 1
            best = max(best, hits)
            if prize_table is not None:
                payout += prize_table.get(hits, 0)
        draws_best[best] += 1
        if sample is None:
            # 秀最新一個評估期「當時實際選出的注」— 讓使用者眼見每期都重選號
            sample = {
                "date": dates[k] if k < len(dates) else "",
                "target": sorted(rows[k]),
                "tickets": [sorted(t) for t in tickets[:5]],
                "hits": [len(set(t) & target) for t in tickets[:5]],
            }

    cost = total_tickets * UNIT_PRICE_TWD
    result: dict[str, object] = {
        "periods_requested": n_eval,
        "draws_evaluated": total_draws,
        "tickets_generated": total_tickets,
        "hit_distribution": dict(sorted(hit_counts.items())),
        "draws_hit_distribution": dict(sorted(draws_best.items())),
        "cost_twd": cost,
        "sample": sample,
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
        f"Periods evaluated   : {result['draws_evaluated']} / {result['periods_requested']}",
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
    lines.append("Hit distribution (per ticket):")
    dist = result["hit_distribution"]
    assert isinstance(dist, dict)
    for k in sorted(dist):
        lines.append(f"  {k} hit(s): {dist[k]:>8}")
    lines.append("Per-draw best hit (幾期最佳一注中幾顆):")
    ddist = result["draws_hit_distribution"]
    assert isinstance(ddist, dict)
    for k in sorted(ddist):
        lines.append(f"  {k} hit(s): {ddist[k]:>8} 期")
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
    ap.add_argument(
        "--max-periods", type=int, default=None,
        help="只評估最近 N 期(省略 = 全部可評估期)",
    )
    ap.add_argument(
        "--batch-disjoint", action="store_true",
        help="組與組之間 6 號完全不重複",
    )
    ap.add_argument(
        "--howard", action="store_true",
        help="霍華德嚴格模式(僅大樂透;威力彩忽略)",
    )
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
        batch_disjoint=args.batch_disjoint,
        howard_mode=args.howard,
        max_periods=args.max_periods,
    )
    print(_format_report(result))


if __name__ == "__main__":
    main()
