"""Backtesting metrics for v5.0 filter validation (offline analytics).

Two diagnostic indicators per protocol §3:

  - **compression_rate**: fraction of total C(49, 6) ≈ 14M combinations
    that survive the static filters. A healthy filter aggressively trims
    junk combinations; near 1.0 means the filter is too loose.

  - **survival_rate**: fraction of historical winning draws (read from
    scraper CSV) that would still pass the filters. Near 1.0 means the
    filter does not "kill" historically valid winners (avoids overfitting).

Naming convention (CLAUDE.md §4.1):
  - Dict keys ending in `_ratio` are decimals in [0, 1].
  - Dict keys ending in `_percent` are already ×100 (display-ready).
  - Function names use operation-style `_rate` suffix; the returned
    decimal lives under a `_ratio` key (e.g. `compression_rate()` returns
    `{"compression_ratio": ...}`; `survival_rate()` returns
    `{"survival_ratio": ...}`).

NOT imported by streamlit_app.py — pure offline diagnostic.

Usage:
    python -m src.analytics.metrics --csv data/lotto649.csv
"""

from __future__ import annotations

import argparse
import csv
import random
from itertools import combinations
from math import comb
from pathlib import Path

from src.generator.history_engine import POOL_MAX, POOL_MIN
from src.generator.lotto_picker import (
    ALLOWED_ODD_COUNTS,
    BIG_THRESHOLD,
    MAX_CONSECUTIVE_PAIRS,
    MAX_PRIME_COUNT,
    MIN_BIG_COUNT,
    MIN_PRIME_COUNT,
    PRIMES_SET,
    SUM_MAX,
    SUM_MIN,
    TICKET_SIZE,
)

# POOL_MIN / POOL_MAX 不在此重刻,改 import 自定義主源 history_engine(SSOT)。
TOTAL_COMBINATIONS = comb(POOL_MAX, TICKET_SIZE)  # C(49,6) = 13,983,816


def _passes_static_filters(
    ticket: tuple[int, ...],
    sum_lo: int = SUM_MIN,
    sum_hi: int = SUM_MAX,
) -> bool:
    if not (sum_lo <= sum(ticket) <= sum_hi):
        return False
    odd = sum(1 for n in ticket if n % 2 == 1)
    if odd not in ALLOWED_ODD_COUNTS:
        return False
    if sum(1 for n in ticket if n > BIG_THRESHOLD) < MIN_BIG_COUNT:
        return False
    primes = sum(1 for n in ticket if n in PRIMES_SET)
    if not (MIN_PRIME_COUNT <= primes <= MAX_PRIME_COUNT):
        return False
    s = sorted(ticket)
    consec = sum(
        1 for i in range(TICKET_SIZE - 1) if s[i + 1] - s[i] == 1
    )
    if consec > MAX_CONSECUTIVE_PAIRS:
        return False
    return True


def compression_rate(
    sum_lo: int = SUM_MIN,
    sum_hi: int = SUM_MAX,
) -> dict[str, float | int]:
    """Walk all C(49, 6) combos; report survival count + ratio."""
    survived = 0
    for combo in combinations(range(POOL_MIN, POOL_MAX + 1), TICKET_SIZE):
        if _passes_static_filters(combo, sum_lo, sum_hi):
            survived += 1
    return {
        "total_combinations": TOTAL_COMBINATIONS,
        "survived": survived,
        "compression_ratio": survived / TOTAL_COMBINATIONS,
        "rejected": TOTAL_COMBINATIONS - survived,
    }


def survival_rate(
    csv_path: Path,
    sum_lo: int = SUM_MIN,
    sum_hi: int = SUM_MAX,
) -> dict[str, float | int]:
    """Read historical winning draws; check what fraction passes filters."""
    with csv_path.open(newline="", encoding="utf-8") as fp:
        reader = csv.DictReader(fp)
        draws: list[tuple[int, ...]] = []
        for row in reader:
            try:
                nums = tuple(
                    sorted(int(row[f"n{i}"]) for i in range(1, TICKET_SIZE + 1))
                )
                if len(nums) == TICKET_SIZE:
                    draws.append(nums)
            except (KeyError, ValueError):
                continue
    if not draws:
        raise ValueError(f"no valid draws in {csv_path}")
    survived = sum(1 for d in draws if _passes_static_filters(d, sum_lo, sum_hi))
    return {
        "draws_total": len(draws),
        "survived": survived,
        "survival_ratio": survived / len(draws),
        "killed": len(draws) - survived,
    }


def compression_rate_monte_carlo(
    sum_lo: int = SUM_MIN,
    sum_hi: int = SUM_MAX,
    n_samples: int = 100_000,
    seed: int = 2026,
) -> dict[str, float | int]:
    """憲法 §4.3 — 第二種算法對帳:抽樣估算 compression_rate。

    從 [POOL_MIN, POOL_MAX] 隨機抽 `n_samples` 個 6-號組合,跑同一套濾網,
    估算存活比例。`n=10^5` 時 std error ≈ sqrt(p(1-p)/n) ≈ 0.0011(p=0.15),
    rel_tol 5% 內幾乎必收斂至真值。
    """
    rng = random.Random(seed)
    pool = list(range(POOL_MIN, POOL_MAX + 1))
    survived = 0
    for _ in range(n_samples):
        combo = tuple(sorted(rng.sample(pool, TICKET_SIZE)))
        if _passes_static_filters(combo, sum_lo, sum_hi):
            survived += 1
    return {
        "n_samples": n_samples,
        "survived": survived,
        "estimated_ratio": survived / n_samples,
    }


def reconcile_compression(
    sum_lo: int = SUM_MIN,
    sum_hi: int = SUM_MAX,
    n_samples: int = 100_000,
    seed: int = 2026,
    rel_tol: float = 0.05,
    exact_result: dict[str, float | int] | None = None,
) -> dict[str, float | int | bool]:
    """憲法 §4.3 — 對帳:exact 列舉 vs Monte Carlo 抽樣應一致(rel_diff ≤ rel_tol)。

    抓 production bug:若 `_passes_static_filters` 邏輯被改錯或濾網參數
    對不上,兩條路徑會發散、`passed=False`,呼叫端應視為 regression。

    `exact_result`:可傳入已算好的 `compression_rate()` 結果避免重算
    (full walk 約 30-60s)。
    """
    exact = exact_result if exact_result is not None else compression_rate(sum_lo, sum_hi)
    mc = compression_rate_monte_carlo(sum_lo, sum_hi, n_samples, seed)
    exact_ratio = float(exact["compression_ratio"])
    mc_ratio = float(mc["estimated_ratio"])
    rel_diff = (
        abs(exact_ratio - mc_ratio) / exact_ratio
        if exact_ratio > 0 else float("inf")
    )
    return {
        "exact_ratio": exact_ratio,
        "monte_carlo_ratio": mc_ratio,
        "abs_diff": abs(exact_ratio - mc_ratio),
        "rel_diff": rel_diff,
        "rel_tol": rel_tol,
        "n_samples": n_samples,
        "passed": rel_diff <= rel_tol,
    }


def _format(comp: dict, surv: dict | None) -> str:
    out = [
        "=== v5.0 Filter Diagnostics ===",
        "",
        "[Compression Rate]",
        f"  Total combinations : {comp['total_combinations']:>12,}",
        f"  Survived filters   : {comp['survived']:>12,}",
        f"  Rejected           : {comp['rejected']:>12,}",
        f"  Compression ratio  : {comp['compression_ratio']*100:>11.4f}%",
        "  → 越低越好（剃除的垃圾注越多）",
    ]
    if surv is not None:
        out += [
            "",
            "[Historical Survival Rate]",
            f"  Historical draws   : {surv['draws_total']:>12,}",
            f"  Survived filters   : {surv['survived']:>12,}",
            f"  Killed             : {surv['killed']:>12,}",
            f"  Survival rate      : {surv['survival_ratio']*100:>11.2f}%",
            "  → 越高越好（不傷及真實開出組合，避免 overfitting）",
        ]
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser(description="v5.0 filter diagnostics")
    ap.add_argument(
        "--csv", type=Path, default=None,
        help="historical CSV; omit to skip survival_rate",
    )
    ap.add_argument("--sum-lo", type=int, default=SUM_MIN)
    ap.add_argument("--sum-hi", type=int, default=SUM_MAX)
    ap.add_argument(
        "--reconcile", action="store_true",
        help="Run Monte Carlo reconciliation (憲法 §4.3 第二種算法對帳)",
    )
    ap.add_argument("--mc-samples", type=int, default=100_000)
    ap.add_argument("--mc-seed", type=int, default=2026)
    args = ap.parse_args()

    print("Computing compression rate (full C(49, 6) walk; ~14M combos)...")
    comp = compression_rate(sum_lo=args.sum_lo, sum_hi=args.sum_hi)

    surv = None
    if args.csv:
        if not args.csv.exists():
            print(f"WARN: CSV not found at {args.csv}; skipping survival rate.")
        else:
            surv = survival_rate(args.csv, sum_lo=args.sum_lo, sum_hi=args.sum_hi)

    print(_format(comp, surv))

    if args.reconcile:
        print("")
        print("[Monte Carlo Reconciliation]")
        rec = reconcile_compression(
            sum_lo=args.sum_lo, sum_hi=args.sum_hi,
            n_samples=args.mc_samples, seed=args.mc_seed,
        )
        status = "✅ PASS" if rec["passed"] else "❌ FAIL"
        print(f"  Exact ratio        : {rec['exact_ratio']*100:>11.4f}%")
        print(f"  Monte Carlo ratio  : {rec['monte_carlo_ratio']*100:>11.4f}%")
        print(f"  Absolute diff      : {rec['abs_diff']*100:>11.4f}%")
        print(f"  Relative diff      : {rec['rel_diff']*100:>11.4f}%")
        print(f"  Tolerance          : {rec['rel_tol']*100:>11.4f}%")
        print(f"  Samples            : {rec['n_samples']:>12,}")
        print(f"  Status             : {status}")


if __name__ == "__main__":
    main()
