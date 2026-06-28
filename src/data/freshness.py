"""Freshness check — 依憲法 §2.4 規則：開獎日當日 22:00 GMT+8 截止線。

雙樂透各自的開獎日不同（大樂透週二/五、威力彩週一/四），各算各的。
過了當日 22:00 GMT+8 仍無新資料 → UI 顯示 warning（非 raise，因 fallback
可降級至 STATIC_FALLBACK_ANALYSIS）。

Stdlib only。pure function 設計、易於 mock now_gmt8 供測試。
"""

from __future__ import annotations

import csv
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from src.data._dates import parse_csv_date

# 台灣固定 GMT+8、無 DST
GMT8 = timezone(timedelta(hours=8))

# Python weekday(): Mon=0, Tue=1, Wed=2, Thu=3, Fri=4, Sat=5, Sun=6
LOTTO649_DRAW_WEEKDAYS: frozenset[int] = frozenset({1, 4})    # 週二、週五
POWERBALL_DRAW_WEEKDAYS: frozenset[int] = frozenset({0, 3})   # 週一、週四

# 當日 22:00 GMT+8 截止線（開獎 21:30 + API 上線延遲 30-60 分緩衝）
DEADLINE_HOUR = 22


def now_gmt8() -> datetime:
    """Inject point for tests; production always returns wall-clock GMT+8."""
    return datetime.now(GMT8)


def expected_latest_draw(
    now: datetime, draw_weekdays: frozenset[int],
) -> date:
    """Most recent draw day whose 22:00 GMT+8 deadline has passed.

    本週若已有 draw day 過了 22:00,回傳該日;否則回退到上一個 draw day。

    Raises ValueError if `draw_weekdays` is empty.
    """
    if not draw_weekdays:
        raise ValueError("draw_weekdays must not be empty")
    today = now.date()
    for back in range(0, 8):
        cand = today - timedelta(days=back)
        if cand.weekday() not in draw_weekdays:
            continue
        if back == 0 and now.hour < DEADLINE_HOUR:
            continue  # 今天是 draw day 但未到 22:00 截止線
        return cand
    # Unreachable: any 8-day window covers all 7 weekdays
    raise RuntimeError("unreachable: no draw day in past 8 days")


def latest_csv_date(path: Path | str) -> date | None:
    """Scan CSV, return first non-empty parseable `draw_date` (newest first).

    Returns None if CSV missing / empty / all dates blank or unparseable.
    Pure read — does not raise on malformed rows (defer to loader's strict path).
    """
    p = Path(path)
    if not p.exists():
        return None
    try:
        with p.open("r", encoding="utf-8", newline="") as fp:
            reader = csv.DictReader(fp)
            for row in reader:
                d = parse_csv_date(row.get("draw_date") or "")
                if d is not None:
                    return d  # newest-first → 第一個可解析即最新
                # 空 / 非法 → 繼續往後找
    except OSError:
        return None
    return None


def check_freshness(
    path: Path | str,
    draw_weekdays: frozenset[int],
    now: datetime | None = None,
) -> str | None:
    """Return warning text if CSV stale,else None.

    `now` injectable for tests;production 傳 None → 用 `now_gmt8()`。
    """
    if now is None:
        now = now_gmt8()
    latest = latest_csv_date(path)
    if latest is None:
        return None  # 無法判定（空 CSV / 全清洗日期）→ 不發 warning,讓 loader 自己處理
    expected = expected_latest_draw(now, draw_weekdays)
    if latest >= expected:
        return None
    days_behind = (expected - latest).days
    return (
        f"CSV 最新一期為 **{latest.isoformat()}**,但預期至少要有 "
        f"**{expected.isoformat()}** 的開獎(落後 {days_behind} 天)。"
        f"請按「觸發 GitHub Actions 抓檔」或手動上傳最新 CSV。"
    )
