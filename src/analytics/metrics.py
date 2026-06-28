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

# v6.24 B6:分析層參數化吃 DomainConfig(預設大樂透,新增威力彩路徑)。
# 5 濾網不在此重刻 → 委派 base_picker.passes_base_filters(SSOT;消第 5 份副本)。
from src.generator.base_picker import passes_base_filters
from src.generator.domain import DomainConfig, LOTTO649, POWERBALL

# 向後相容:模組常數維持大樂透 C(49,6)(test_metrics 依賴);動態值見 _total_combos。
TOTAL_COMBINATIONS = comb(LOTTO649.pool_max, LOTTO649.ticket_size)  # 13,983,816


def _total_combos(dom: DomainConfig) -> int:
    return comb(dom.pool_max, dom.ticket_size)


def _sum_bounds(dom: DomainConfig, sum_lo: int | None, sum_hi: int | None) -> tuple[int, int]:
    """None → 取該樂透靜態 fallback 和值區間(SSOT:domain.static_sum_*)。"""
    lo = dom.static_sum_min if sum_lo is None else sum_lo
    hi = dom.static_sum_max if sum_hi is None else sum_hi
    return lo, hi


def _passes_static_filters(
    ticket: tuple[int, ...],
    sum_lo: int,
    sum_hi: int,
    dom: DomainConfig = LOTTO649,
) -> bool:
    """5 濾網(sum/奇偶/大小/質數/連號)委派 base_picker;ticket 須已排序。"""
    return passes_base_filters(
        ticket, sum_lo, sum_hi, apply_secondary=True, cfg=dom,
    )


def compression_rate(
    sum_lo: int | None = None,
    sum_hi: int | None = None,
    dom: DomainConfig = LOTTO649,
) -> dict[str, float | int]:
    """Walk all C(pool, ticket) combos; report survival count + ratio。

    `sum_lo/hi=None` → 取 `dom` 靜態 fallback 和值區間;`dom` 預設大樂透
    (向後相容),傳 `POWERBALL` 即跑威力彩第一區 1-38 全列舉(v6.24 B6)。
    """
    lo, hi = _sum_bounds(dom, sum_lo, sum_hi)
    total = _total_combos(dom)
    survived = 0
    for combo in combinations(range(dom.pool_min, dom.pool_max + 1), dom.ticket_size):
        if _passes_static_filters(combo, lo, hi, dom):
            survived += 1
    return {
        "total_combinations": total,
        "survived": survived,
        "compression_ratio": survived / total,
        "rejected": total - survived,
    }


def survival_rate(
    csv_path: Path,
    sum_lo: int | None = None,
    sum_hi: int | None = None,
    dom: DomainConfig = LOTTO649,
) -> dict[str, float | int]:
    """Read historical winning draws (n1..n_ticket); fraction passing filters。"""
    lo, hi = _sum_bounds(dom, sum_lo, sum_hi)
    with csv_path.open(newline="", encoding="utf-8") as fp:
        reader = csv.DictReader(fp)
        draws: list[tuple[int, ...]] = []
        for row in reader:
            try:
                nums = tuple(
                    sorted(int(row[f"n{i}"]) for i in range(1, dom.ticket_size + 1))
                )
                if len(nums) == dom.ticket_size:
                    draws.append(nums)
            except (KeyError, ValueError):
                continue
    if not draws:
        raise ValueError(f"no valid draws in {csv_path}")
    survived = sum(1 for d in draws if _passes_static_filters(d, lo, hi, dom))
    return {
        "draws_total": len(draws),
        "survived": survived,
        "survival_ratio": survived / len(draws),
        "killed": len(draws) - survived,
    }


def compression_rate_monte_carlo(
    sum_lo: int | None = None,
    sum_hi: int | None = None,
    n_samples: int = 100_000,
    seed: int = 2026,
    dom: DomainConfig = LOTTO649,
) -> dict[str, float | int]:
    """憲法 §4.3 — 第二種算法對帳:抽樣估算 compression_rate。

    從 `[dom.pool_min, dom.pool_max]` 隨機抽 `n_samples` 個組合,跑同一套濾網,
    估算存活比例。`n=10^5` 時 std error ≈ sqrt(p(1-p)/n) ≈ 0.0011(p=0.15),
    rel_tol 5% 內幾乎必收斂至真值。
    """
    lo, hi = _sum_bounds(dom, sum_lo, sum_hi)
    rng = random.Random(seed)
    pool = list(range(dom.pool_min, dom.pool_max + 1))
    survived = 0
    for _ in range(n_samples):
        combo = tuple(sorted(rng.sample(pool, dom.ticket_size)))
        if _passes_static_filters(combo, lo, hi, dom):
            survived += 1
    return {
        "n_samples": n_samples,
        "survived": survived,
        "estimated_ratio": survived / n_samples,
    }


def reconcile_compression(
    sum_lo: int | None = None,
    sum_hi: int | None = None,
    n_samples: int = 100_000,
    seed: int = 2026,
    rel_tol: float = 0.05,
    exact_result: dict[str, float | int] | None = None,
    dom: DomainConfig = LOTTO649,
) -> dict[str, float | int | bool]:
    """憲法 §4.3 — 對帳:exact 列舉 vs Monte Carlo 抽樣應一致(rel_diff ≤ rel_tol)。

    抓 production bug:若 `_passes_static_filters` 邏輯被改錯或濾網參數
    對不上,兩條路徑會發散、`passed=False`,呼叫端應視為 regression。

    `exact_result`:可傳入已算好的 `compression_rate()` 結果避免重算
    (full walk 約 30-60s)。
    """
    exact = (
        exact_result if exact_result is not None
        else compression_rate(sum_lo, sum_hi, dom)
    )
    mc = compression_rate_monte_carlo(sum_lo, sum_hi, n_samples, seed, dom)
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
    ap.add_argument(
        "--lottery", choices=["lotto649", "powerball"], default="lotto649",
        help="lotto649 = 6/49(預設);powerball = 威力彩第一區 6/38",
    )
    ap.add_argument(
        "--sum-lo", type=int, default=None,
        help="和值下界(省略 → 該樂透靜態 fallback 區間)",
    )
    ap.add_argument("--sum-hi", type=int, default=None)
    ap.add_argument(
        "--reconcile", action="store_true",
        help="Run Monte Carlo reconciliation (憲法 §4.3 第二種算法對帳)",
    )
    ap.add_argument("--mc-samples", type=int, default=100_000)
    ap.add_argument("--mc-seed", type=int, default=2026)
    args = ap.parse_args()

    dom = LOTTO649 if args.lottery == "lotto649" else POWERBALL

    print(
        f"Computing compression rate "
        f"(full C({dom.pool_max}, {dom.ticket_size}) walk; "
        f"{_total_combos(dom):,} combos)..."
    )
    comp = compression_rate(sum_lo=args.sum_lo, sum_hi=args.sum_hi, dom=dom)

    surv = None
    if args.csv:
        if not args.csv.exists():
            print(f"WARN: CSV not found at {args.csv}; skipping survival rate.")
        else:
            surv = survival_rate(
                args.csv, sum_lo=args.sum_lo, sum_hi=args.sum_hi, dom=dom,
            )

    print(_format(comp, surv))

    if args.reconcile:
        print("")
        print("[Monte Carlo Reconciliation]")
        rec = reconcile_compression(
            sum_lo=args.sum_lo, sum_hi=args.sum_hi,
            n_samples=args.mc_samples, seed=args.mc_seed, dom=dom,
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
