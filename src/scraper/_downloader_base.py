"""Scraper 共用底座 — 兩 downloader(大樂透/威力彩)的 SSOT。

REFACTOR_AUDIT §5.2 / §6 B2。兩 downloader 原本 85-90% copy-paste,本模組把
所有 identical 部分(常數、`Draw`、月份迭代、session 建構、term 排序、CSV 寫入、
既有讀取、fetch 迴圈、append-only merge、CLI 入口)收斂為一,只留下真正的領域差異
(API path、回應欄名、schema 解析)由各 downloader 以**注入 callable** 提供。

可測試性契約(務必維持):
  - `run_fetch` / `run_download` / `run_main` 都把領域函式(`_fetch_month_raw`、
    `_parse_row`、`fetch`、`download`)當**參數**收;各 downloader 的薄 wrapper
    以「呼叫時查 module global」方式傳入 → `unittest.mock.patch.object(scraper, ...)`
    對這些名稱的 patch 才會生效。
  - 會 log 的函式(`load_existing` / `run_fetch` / `run_download` / `run_main`)
    一律收 `logger` 參數,各 downloader 傳自己的 LOGGER("lotto649"/"powerball"),
    保留既有 logger-name 行為(`test_loader_dup_warning` 用 assertLogs 綁定)。

Stdlib + requests(scraper-only 例外,CLAUDE.md §8.4)。
"""

from __future__ import annotations

import argparse
import csv
import logging
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Callable, Iterable

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from src.scraper._dates import canon_date

# ── 共用常數(原本兩 downloader 各刻一份,v6.4 抽出但未集中;此處收斂)──────────
CSV_FIELDS = [
    "draw_term", "draw_date", "n1", "n2", "n3", "n4", "n5", "n6", "special",
]
API_BASE = "https://api.taiwanlottery.com/TLCAPIWeB/Lottery"
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
    "Referer": "https://www.taiwanlottery.com/",
}
REQUEST_TIMEOUT = 15  # seconds
JSON_RETRY_ATTEMPTS = 3
JSON_RETRY_BACKOFF = 2.0  # seconds, exponential
# HTTP-layer retry (urllib3 adapter);語義獨立於 JSON_RETRY_*(應用層 decode 重試)
HTTP_RETRY_TOTAL = 3
HTTP_RETRY_BACKOFF = 2.0
# 單月 API window:31 天 = 行事曆月份最大可能開獎數窗口
API_PAGE_SIZE = 31
# 每月最多 ~8 期(週 2 開獎 × 4-5 週);buffer 2 個月容跨月邊界
MAX_DRAWS_PER_MONTH = 8
MONTHS_BUFFER = 2


@dataclass(frozen=True)
class Draw:
    draw_term: str
    draw_date: str
    n1: int
    n2: int
    n3: int
    n4: int
    n5: int
    n6: int
    special: int


def _months_back(n_months: int) -> list[tuple[str, str]]:
    today = date.today()
    y, m = today.year, today.month
    out: list[tuple[str, str]] = []
    for _ in range(n_months):
        out.append((f"{y:04d}", f"{m:02d}"))
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    return out


def _build_session() -> requests.Session:
    """Session with browser UA + retry adapter (429/5xx)."""
    sess = requests.Session()
    sess.headers.update(DEFAULT_HEADERS)
    retry = Retry(
        total=HTTP_RETRY_TOTAL,
        backoff_factor=HTTP_RETRY_BACKOFF,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
        raise_on_status=False,
    )
    sess.mount("https://", HTTPAdapter(max_retries=retry))
    return sess


def _term_sort_key(term: str) -> tuple[int, int]:
    """Scheme-aware sort key for `draw_term`.

    Official API switched mid-history from 4-digit (e.g. `'2446'`) to long-form
    (e.g. `'115000053'`). String-sort reverse puts long-form AFTER 4-digit
    (`'1' < '2'`), so the newest real draw ends up at the bottom. The historical
    CSV also has unreliable `draw_date` years, so we can't sort by date either.

    Rule: long-form scheme (len >= 8) sits in bucket 2 — always newer than any
    4-digit term (bucket 1). Within each bucket, sort by integer term value.
    Unparseable terms drop to bucket 0 (file tail).
    """
    if len(term) >= 8:
        try:
            return (2, int(term))
        except ValueError:
            return (0, 0)
    try:
        return (1, int(term))
    except ValueError:
        return (0, 0)


def save_csv(draws: Iterable[Draw], path: Path) -> int:
    """Append-safe CSV writer; sorts newest-first via `_term_sort_key`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = sorted(draws, key=lambda d: _term_sort_key(d.draw_term), reverse=True)
    with path.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for d in rows:
            writer.writerow(asdict(d))
    return len(rows)


def load_existing(path: Path, *, logger: logging.Logger) -> dict[str, Draw]:
    """Load existing CSV keyed by `draw_term` (preserves history as-is).

    重複 draw_term → `logger.warning` + last-write-wins(append-only 是 download()
    端合約,load 端只負責讀;CLAUDE.md §4.6)。
    """
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8", newline="") as fp:
        reader = csv.DictReader(fp)
        merged: dict[str, Draw] = {}
        for row in reader:
            try:
                draw = Draw(
                    draw_term=row["draw_term"],
                    draw_date=row["draw_date"],
                    n1=int(row["n1"]), n2=int(row["n2"]), n3=int(row["n3"]),
                    n4=int(row["n4"]), n5=int(row["n5"]), n6=int(row["n6"]),
                    special=int(row["special"]),
                )
            except (KeyError, ValueError):
                continue
            if draw.draw_term in merged:
                logger.warning(
                    "duplicate draw_term=%s in CSV — last row wins (data integrity issue?)",
                    draw.draw_term,
                )
            merged[draw.draw_term] = draw
    return merged


def run_fetch(
    periods: int,
    session: requests.Session | None,
    *,
    fetch_month_raw: Callable[[requests.Session, str, str], list[dict]],
    parse_row: Callable[[dict], Draw | None],
    logger: logging.Logger,
) -> list[Draw]:
    """Fetch up to `periods` recent draws (newest first).

    `fetch_month_raw` / `parse_row` 由各 downloader 注入(領域差異)。

    Current-month (idx=0) failure is fatal — that's how stale data slips through
    cron silently: if Cloudflare blocks the runner on the current-month fetch but
    an older month still works, `out` fills with already-known draws, download()
    reports "added=0", and the workflow goes green with no new data. Raise on
    idx=0 so the workflow turns red and opens an issue with diagnostics.
    """
    sess = session or _build_session()
    seen: set[str] = set()
    out: list[Draw] = []
    # ceil(periods / MAX_DRAWS_PER_MONTH) + MONTHS_BUFFER
    months = (
        (periods + MAX_DRAWS_PER_MONTH - 1) // MAX_DRAWS_PER_MONTH
        + MONTHS_BUFFER
    )

    for idx, (year, month) in enumerate(_months_back(months)):
        try:
            rows = fetch_month_raw(sess, year, month)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Fetch %s-%s failed: %s", year, month, exc)
            if idx == 0:
                raise RuntimeError(
                    f"Current month {year}-{month} fetch failed after retries: {exc}. "
                    "Likely Cloudflare / IP block on the Actions runner — see the "
                    "scraper log tail in the auto-opened issue body for HTTP status "
                    "and body preview."
                ) from exc
            continue
        logger.info("Month %s-%s: API returned %d row(s)", year, month, len(rows))
        for row in rows:
            draw = parse_row(row)
            if draw is None or draw.draw_term in seen:
                continue
            seen.add(draw.draw_term)
            out.append(draw)
            if len(out) >= periods:
                return out
    return out


def run_download(
    periods: int,
    output: Path,
    *,
    fetch: Callable[[int], list[Draw]],
    logger: logging.Logger,
) -> int:
    """Append-only merge: skip API rows whose canonical date matches any existing row.

    Date is the stable identity (official API switched draw_term scheme mid-history).
    Existing rows are NEVER overwritten — even malformed `draw_date` stays untouched.
    `fetch` 由 downloader 注入(呼叫時查 module global → 可被測試 patch)。
    """
    fetched = fetch(periods)
    if not fetched:
        raise RuntimeError(
            "Fetch returned no data. Network blocked? Use UI manual upload."
        )
    existing = load_existing(output, logger=logger)
    existing_dates = {canon_date(d.draw_date) for d in existing.values() if d.draw_date}

    fetched_max = max(
        (canon_date(d.draw_date) for d in fetched if d.draw_date),
        default="",
    )
    existing_max = max(existing_dates, default="")
    logger.info(
        "Diagnostic: fetched=%d (max_date=%s) | existing=%d (max_date=%s)",
        len(fetched), fetched_max or "?", len(existing), existing_max or "?",
    )

    merged: dict[str, Draw] = dict(existing)
    added = 0
    for d in fetched:
        canon = canon_date(d.draw_date)
        if canon and canon in existing_dates:
            continue  # same date already in CSV — skip regardless of term scheme
        if d.draw_term in merged:
            continue  # extra safety against term-level collision
        merged[d.draw_term] = d
        existing_dates.add(canon)
        added += 1
    logger.info("Added %d new draw(s) (existing kept: %d)", added, len(existing))
    # §4.2 不變量:append-only — merged 不得少於 existing(永不覆蓋現有列)
    assert len(merged) >= len(existing), \
        f"append-only violated: merged={len(merged)} < existing={len(existing)}"
    return save_csv(merged.values(), output)


def run_main(
    argv: list[str] | None,
    *,
    description: str,
    default_periods: int,
    default_output: Path,
    download: Callable[[int, Path], int],
    logger: logging.Logger,
) -> int:
    """Shared CLI entry; `download` 由 downloader 注入(呼叫時查 module global)。"""
    ap = argparse.ArgumentParser(description=description)
    ap.add_argument("--periods", type=int, default=default_periods)
    ap.add_argument("--output", type=Path, default=default_output)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    try:
        total = download(args.periods, args.output)
    except Exception as exc:  # noqa: BLE001
        logger.error("Download failed: %s", exc)
        return 1
    logger.info("OK. %d draws stored at %s", total, args.output)
    return 0
