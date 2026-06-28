"""威力彩 (Taiwan PowerLotto 6/38 + 1/8) 歷史抓檔器 (v6.0).

直打官方 API `https://api.taiwanlottery.com/TLCAPIWeB/Lottery/SuperLotto638Result`
(與大樂透 `Lotto649Result` 同 endpoint family)。

v6.22(B2):共用骨架收斂至 `src.scraper._downloader_base`;本檔只保留威力彩的
領域差異(API path、三種回應欄名候選、第一區/第二區 schema 解析)與薄 wrapper。
所有舊有 module-level 名稱維持可 import / 可 patch。

CLI:
    python -m src.scraper.powerball_downloader --periods 200
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

LOGGER = logging.getLogger("powerball")
DEFAULT_OUTPUT = Path("data/powerball.csv")
DEFAULT_PERIODS = 200
# 領域差異:威力彩 endpoint path 與「回應欄名可能有三種」。
API_PATH = "SuperLotto638Result"
RESPONSE_FIELDS = ("superLotto638Res", "lotto638Res", "powerLottoRes")


def _canon_date(s: str) -> str:
    """Delegates to scraper._dates.canon_date — single source (REFACTOR_AUDIT §5.3)."""
    return canon_date(s)


def _fetch_month_raw(sess, year: str, month: str) -> list[dict]:
    """單月 API 呼叫;JSON-decode 失敗自動 retry。回應欄名嘗試三種候選。"""
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
                rows: list = []
                for field in RESPONSE_FIELDS:
                    candidate = (content or {}).get(field)
                    if candidate:
                        rows = candidate
                        break
                return list(rows)
        if attempt < JSON_RETRY_ATTEMPTS - 1:
            time.sleep(JSON_RETRY_BACKOFF * (2 ** attempt))
    raise RuntimeError(f"All {JSON_RETRY_ATTEMPTS} attempts failed: {last_err}")


def _parse_row(row: dict) -> Draw | None:
    """Parse one API row → Draw(容兩種 schema:drawNumberSize 或 第一區/第二區)。"""
    nums = row.get("第一區") or row.get("firstDrawNumberSize")
    special = row.get("第二區") or row.get("secondDrawNumber")
    if nums is None:
        dn = row.get("drawNumberSize") or []
        if len(dn) >= 6:
            nums = dn[:6]
        if special is None and len(dn) >= 7:
            special = dn[6]
    if not nums or len(nums) < 6:
        return None
    if isinstance(special, list):
        special = special[0] if special else None
    if special is None:
        return None
    try:
        return Draw(
            draw_term=str(row.get("期別") or row.get("period") or ""),
            draw_date=_canon_date(str(row.get("開獎日期") or row.get("lotteryDate") or "")),
            n1=int(nums[0]), n2=int(nums[1]), n3=int(nums[2]),
            n4=int(nums[3]), n5=int(nums[4]), n6=int(nums[5]),
            special=int(special),
        )
    except (TypeError, ValueError):
        return None


def load_existing(path: Path) -> dict[str, Draw]:
    """Load existing CSV keyed by `draw_term`(dup 警告記於 powerball logger)。"""
    return base.load_existing(path, logger=LOGGER)


def fetch(periods: int = DEFAULT_PERIODS, session=None) -> list[Draw]:
    """抓最近 `periods` 期(newest first)。`session` 可注入。"""
    return base.run_fetch(
        periods, session,
        fetch_month_raw=_fetch_month_raw,
        parse_row=_parse_row,
        logger=LOGGER,
    )


def download(periods: int = DEFAULT_PERIODS, output: Path = DEFAULT_OUTPUT) -> int:
    """Append-only merge by canonical date。`fetch` 查 module global → 可被測試 patch。"""
    return base.run_download(periods, output, fetch=fetch, logger=LOGGER)


def main(argv: list[str] | None = None) -> int:
    return base.run_main(
        argv,
        description="Refresh PowerLotto 6/38+1/8 historical CSV",
        default_periods=DEFAULT_PERIODS,
        default_output=DEFAULT_OUTPUT,
        download=download,
        logger=LOGGER,
    )


if __name__ == "__main__":
    sys.exit(main())
