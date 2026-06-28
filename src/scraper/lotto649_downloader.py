"""Taiwan Lotto 6/49 historical fetcher (v3.1 — direct API).

Direct call to the official Taiwan Lottery API
(`https://api.taiwanlottery.com/TLCAPIWeB/Lottery/Lotto649Result`),
bypassing the fragile `taiwanlottery` PyPI wrapper. Iterates months
backwards from today and accumulates draws until `periods` records
are collected.

v6.22(B2):共用骨架(Draw / session / 月份迭代 / term 排序 / CSV 讀寫 /
fetch 迴圈 / append-only merge / CLI)收斂至 `src.scraper._downloader_base`;
本檔只保留大樂透的領域差異(API path、回應欄名 `lotto649Res`、schema 解析)
與薄 wrapper。所有舊有 module-level 名稱(`Draw`、`fetch`、`download`、
`save_csv`、`load_existing`、`_build_session`、`_months_back`、`_canon_date`、
`JSON_RETRY_ATTEMPTS` …)維持可 import / 可 patch。

This module is offline tooling: run it locally / in CI to refresh
`data/lotto649.csv`, then commit the CSV. Streamlit Cloud reads the CSV
checked into the repo; the live app never makes outbound API calls.

CLI:
    python -m src.scraper.lotto649_downloader --periods 500
"""

from __future__ import annotations

import logging
import sys
import time  # noqa: F401 — 供 _fetch_month_raw retry 與測試 patch(scraper.time.sleep)
from pathlib import Path

from src.scraper import _downloader_base as base
from src.scraper._dates import canon_date
from src.scraper._downloader_base import (  # noqa: F401 — re-export 保留舊 API 表面
    API_BASE,
    API_PAGE_SIZE,
    CSV_FIELDS,
    DEFAULT_HEADERS,
    Draw,
    JSON_RETRY_ATTEMPTS,
    JSON_RETRY_BACKOFF,
    REQUEST_TIMEOUT,
    _build_session,
    _months_back,
    _term_sort_key,
    save_csv,
)

LOGGER = logging.getLogger("lotto649")
DEFAULT_OUTPUT = Path("data/lotto649.csv")
DEFAULT_PERIODS = 500
# 領域差異:大樂透 endpoint path 與回應欄名。
API_PATH = "Lotto649Result"
RESPONSE_FIELD = "lotto649Res"


def _canon_date(s: str) -> str:
    """Delegates to scraper._dates.canon_date — single source (REFACTOR_AUDIT §5.3)."""
    return canon_date(s)


def _fetch_month_raw(sess, year: str, month: str) -> list[dict]:
    """Call API for one month; returns raw row list. Retries on JSON decode failures.

    領域差異點:URL 的 `API_PATH` 與回應的 `RESPONSE_FIELD`。retry/log 骨架與威力彩
    相同但保留於各 downloader,以維持 `scraper.time` patch 與直接 patch 本函式的契約。
    """
    url = f"{API_BASE}/{API_PATH}?period&month={year}-{month}&pageSize={API_PAGE_SIZE}"
    last_err: Exception | None = None
    for attempt in range(JSON_RETRY_ATTEMPTS):
        resp = sess.get(url, timeout=REQUEST_TIMEOUT)
        if resp.status_code != 200:
            LOGGER.warning(
                "API %s-%s HTTP %s (attempt %d/%d): %r",
                year, month, resp.status_code, attempt + 1, JSON_RETRY_ATTEMPTS,
                resp.content[:200],
            )
            last_err = RuntimeError(f"HTTP {resp.status_code}")
        else:
            try:
                payload = resp.json()
            except ValueError as exc:
                LOGGER.warning(
                    "API %s-%s JSON parse failed (attempt %d/%d). "
                    "Content-Type=%s. Body preview: %r",
                    year, month, attempt + 1, JSON_RETRY_ATTEMPTS,
                    resp.headers.get("content-type", "?"),
                    resp.content[:200],
                )
                last_err = exc
            else:
                content = payload.get("content") if isinstance(payload, dict) else None
                rows = (content or {}).get(RESPONSE_FIELD) or []
                return list(rows)
        if attempt < JSON_RETRY_ATTEMPTS - 1:
            time.sleep(JSON_RETRY_BACKOFF * (2 ** attempt))
    raise RuntimeError(f"All {JSON_RETRY_ATTEMPTS} attempts failed: {last_err}")


def _parse_row(row: dict) -> Draw | None:
    """Parse one API row (or legacy taiwanlottery shape) into a Draw."""
    # Direct API shape: drawNumberSize is a list of 7 ints (6 main + 1 special).
    # Legacy taiwanlottery shape: 獎號 (list[6]) + 特別號 (int).
    nums = row.get("獎號")
    special = row.get("特別號")
    if nums is None:
        dn = row.get("drawNumberSize") or []
        if len(dn) >= 7:
            nums = dn[:6]
            special = dn[6]
    if not nums or len(nums) < 6:
        return None
    try:
        return Draw(
            draw_term=str(row.get("期別") or row.get("period") or ""),
            draw_date=_canon_date(str(row.get("開獎日期") or row.get("lotteryDate") or "")),
            n1=int(nums[0]), n2=int(nums[1]), n3=int(nums[2]),
            n4=int(nums[3]), n5=int(nums[4]), n6=int(nums[5]),
            special=int(special or 0),
        )
    except (TypeError, ValueError):
        return None


def load_existing(path: Path) -> dict[str, Draw]:
    """Load existing CSV keyed by `draw_term`（dup 警告記於 lotto649 logger）。"""
    return base.load_existing(path, logger=LOGGER)


def fetch(periods: int = DEFAULT_PERIODS, session=None) -> list[Draw]:
    """Fetch up to `periods` recent draws (newest first). `session` injectable."""
    return base.run_fetch(
        periods, session,
        fetch_month_raw=_fetch_month_raw,
        parse_row=_parse_row,
        logger=LOGGER,
    )


def download(periods: int = DEFAULT_PERIODS, output: Path = DEFAULT_OUTPUT) -> int:
    """Append-only merge (date-keyed). `fetch` 查 module global → 可被測試 patch。"""
    return base.run_download(periods, output, fetch=fetch, logger=LOGGER)


def main(argv: list[str] | None = None) -> int:
    return base.run_main(
        argv,
        description="Refresh Lotto 6/49 historical CSV",
        default_periods=DEFAULT_PERIODS,
        default_output=DEFAULT_OUTPUT,
        download=download,
        logger=LOGGER,
    )


if __name__ == "__main__":
    sys.exit(main())
