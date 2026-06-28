"""One-shot: 清洗並覆寫 data/powerball.csv 的歷史資料。

處理三類髒資料：
  1. 中文 Big5→UTF-8 損毀的日期（含 U+FFFD `��`）→ 清空 draw_date
  2. special 超出 [1,8] 的列 → 整列丟棄
  3. 日期含空白/不完整（如 `02/ 29 ` 無年份）→ 清空 draw_date

保留：n1-n6 ∈ [1,38] 且無重複的列（號碼是真開獎、引擎只需要 nums + special）。
排序：scheme-aware（長期別在新方案桶、4-digit 在舊方案桶；同桶內 int 排序）newest-first。

下游影響：`powerball_downloader.download()` 對 `if d.draw_date` 過濾，
空 date 不會佔 dedup key、下次 cron 抓到真實日期能正常入庫。

Run once:
    python -m scripts.import_powerball_history <source.csv>
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

DST = Path("data/powerball.csv")
FIELDS = ["draw_term", "draw_date", "n1", "n2", "n3", "n4", "n5", "n6", "special"]
MAIN_MIN, MAIN_MAX = 1, 38
BONUS_MIN, BONUS_MAX = 1, 8


def clean_date(raw: str) -> str:
    """Normalize to `YYYY/MM/DD`; empty if unparseable or contains replacement char."""
    if not raw or "�" in raw:
        return ""
    raw = raw.strip().replace("-", "/")
    parts = [p.strip() for p in raw.split("/")]
    if len(parts) < 3:
        return ""
    try:
        y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
    except ValueError:
        return ""
    if not (1 <= m <= 12 and 1 <= d <= 31):
        return ""
    return f"{y:04d}/{m:02d}/{d:02d}"


def _sort_key(term: str) -> tuple[int, int]:
    if len(term) >= 8:
        try:
            return (2, int(term))
        except ValueError:
            return (0, 0)
    try:
        return (1, int(term))
    except ValueError:
        return (0, 0)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("source", type=Path)
    ap.add_argument("--output", type=Path, default=DST)
    args = ap.parse_args(argv)

    with args.source.open("r", encoding="utf-8", errors="replace") as fp:
        rows = list(csv.DictReader(fp))

    cleaned: list[dict] = []
    dropped: list[tuple[str, str]] = []
    cleared_dates = 0

    for r in rows:
        term = r.get("draw_term", "").strip()
        try:
            nums = [int(r[f"n{k}"]) for k in range(1, 7)]
            special = int(r["special"])
        except (KeyError, ValueError) as e:
            dropped.append((term or "?", f"parse fail: {e}"))
            continue

        if not all(MAIN_MIN <= n <= MAIN_MAX for n in nums):
            dropped.append((term, f"main num out of [{MAIN_MIN},{MAIN_MAX}]: {nums}"))
            continue
        if len(set(nums)) != len(nums):
            dropped.append((term, f"duplicate main nums: {nums}"))
            continue
        if not (BONUS_MIN <= special <= BONUS_MAX):
            dropped.append((term, f"special out of [{BONUS_MIN},{BONUS_MAX}]: {special}"))
            continue

        raw_date = r.get("draw_date", "")
        date = clean_date(raw_date)
        if raw_date and not date:
            cleared_dates += 1

        cleaned.append({
            "draw_term": term,
            "draw_date": date,
            "n1": nums[0], "n2": nums[1], "n3": nums[2],
            "n4": nums[3], "n5": nums[4], "n6": nums[5],
            "special": special,
        })

    cleaned.sort(key=lambda r: _sort_key(r["draw_term"]), reverse=True)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(cleaned)

    print(f"✅ Wrote {len(cleaned)} rows to {args.output}")
    print(f"   Cleared {cleared_dates} unparseable dates (likely 中文 encoding loss)")
    print(f"   Dropped {len(dropped)} invalid rows:")
    for term, reason in dropped[:30]:
        print(f"     {term}: {reason}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
