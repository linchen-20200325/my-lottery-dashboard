"""威力彩 (Taiwan PowerLotto 6/38 + 1/8) 歷史抓檔器 (v6.0).

直打官方 API `https://api.taiwanlottery.com/TLCAPIWeB/Lottery/SuperLotto638Result`
（與大樂透 `Lotto649Result` 同 endpoint family）。沿用 lotto649_downloader v3.5
的強化模式：Mozilla UA + Referer + Retry adapter (429/5xx) + JSON-decode 外層 retry
+ per-month INFO log + current-month 失敗強制 raise（避免 stale CSV 偽綠燈）。

CLI:
    python -m src.scraper.powerball_downloader --periods 200
"""

from __future__ import annotations

import argparse
import csv
import logging
import sys
import time
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Iterable

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from src.scraper._dates import canon_date

LOGGER = logging.getLogger("powerball")
DEFAULT_OUTPUT = Path("data/powerball.csv")
CSV_FIELDS = [
    "draw_term", "draw_date", "n1", "n2", "n3", "n4", "n5", "n6", "special",
]

API_BASE = "https://api.taiwanlottery.com/TLCAPIWeB/Lottery"
API_PATH = "SuperLotto638Result"
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
    "Referer": "https://www.taiwanlottery.com/",
}
REQUEST_TIMEOUT = 15
JSON_RETRY_ATTEMPTS = 3
JSON_RETRY_BACKOFF = 2.0
# HTTP-layer retry(urllib3 adapter);與 JSON_RETRY_* 分離(語義不同)
HTTP_RETRY_TOTAL = 3
HTTP_RETRY_BACKOFF = 2.0
# 單月 API window:31 天 = 行事曆月份最大可能開獎數窗口
API_PAGE_SIZE = 31
# 威力彩每月最多 ~8 期(週 2 開獎 × 4-5 週);buffer 2 個月容跨月邊界
MAX_DRAWS_PER_MONTH = 8
MONTHS_BUFFER = 2


def _canon_date(s: str) -> str:
    """Delegates to scraper._dates.canon_date — single source (REFACTOR_AUDIT §5.3)."""
    return canon_date(s)


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


def _fetch_month_raw(sess: requests.Session, year: str, month: str) -> list[dict]:
    """單月 API 呼叫；JSON-decode 失敗自動 retry。"""
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
                # API field name varies; try common forms.
                rows = (
                    (content or {}).get("superLotto638Res")
                    or (content or {}).get("lotto638Res")
                    or (content or {}).get("powerLottoRes")
                    or []
                )
                return list(rows)
        if attempt < JSON_RETRY_ATTEMPTS - 1:
            time.sleep(JSON_RETRY_BACKOFF * (2 ** attempt))
    raise RuntimeError(f"All {JSON_RETRY_ATTEMPTS} attempts failed: {last_err}")


def _parse_row(row: dict) -> Draw | None:
    """Parse one API row → Draw（容兩種 schema：drawNumberSize 或 第一區/第二區）。"""
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


def fetch(periods: int = 200, session: requests.Session | None = None) -> list[Draw]:
    """抓最近 `periods` 期（newest first）。Current-month (idx=0) 失敗強制 raise。"""
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
            rows = _fetch_month_raw(sess, year, month)
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Fetch %s-%s failed: %s", year, month, exc)
            if idx == 0:
                raise RuntimeError(
                    f"Current month {year}-{month} fetch failed after retries: {exc}. "
                    "Likely Cloudflare / IP block on the Actions runner — see scraper "
                    "log tail in the auto-opened issue body."
                ) from exc
            continue
        LOGGER.info("Month %s-%s: API returned %d row(s)", year, month, len(rows))
        for row in rows:
            draw = _parse_row(row)
            if draw is None or draw.draw_term in seen:
                continue
            seen.add(draw.draw_term)
            out.append(draw)
            if len(out) >= periods:
                return out
    return out


def load_existing(path: Path) -> dict[str, Draw]:
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
                LOGGER.warning(
                    "duplicate draw_term=%s in CSV — last row wins (data integrity issue?)",
                    draw.draw_term,
                )
            merged[draw.draw_term] = draw
    return merged


def _term_sort_key(term: str) -> tuple[int, int]:
    """Scheme-aware sort：長期別 (>=8 digits) 在新方案桶、4-digit 在舊方案桶。"""
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
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = sorted(draws, key=lambda d: _term_sort_key(d.draw_term), reverse=True)
    with path.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for d in rows:
            writer.writerow(asdict(d))
    return len(rows)


def download(periods: int = 200, output: Path = DEFAULT_OUTPUT) -> int:
    """Append-only merge by canonical date（既有列永不覆蓋）。"""
    fetched = fetch(periods)
    if not fetched:
        raise RuntimeError(
            "Fetch returned no data. Network blocked? Use UI manual upload."
        )
    existing = load_existing(output)
    existing_dates = {_canon_date(d.draw_date) for d in existing.values() if d.draw_date}

    fetched_max = max(
        (_canon_date(d.draw_date) for d in fetched if d.draw_date),
        default="",
    )
    existing_max = max(existing_dates, default="")
    LOGGER.info(
        "Diagnostic: fetched=%d (max_date=%s) | existing=%d (max_date=%s)",
        len(fetched), fetched_max or "?", len(existing), existing_max or "?",
    )

    merged: dict[str, Draw] = dict(existing)
    added = 0
    for d in fetched:
        canon = _canon_date(d.draw_date)
        if canon and canon in existing_dates:
            continue
        if d.draw_term in merged:
            continue
        merged[d.draw_term] = d
        existing_dates.add(canon)
        added += 1
    LOGGER.info("Added %d new draw(s) (existing kept: %d)", added, len(existing))
    # §4.2 不變量:append-only — merged 不得少於 existing(永不覆蓋現有列)
    assert len(merged) >= len(existing), \
        f"append-only violated: merged={len(merged)} < existing={len(existing)}"
    return save_csv(merged.values(), output)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Refresh PowerLotto 6/38+1/8 historical CSV")
    ap.add_argument("--periods", type=int, default=200)
    ap.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    try:
        total = download(args.periods, args.output)
    except Exception as exc:  # noqa: BLE001
        LOGGER.error("Download failed: %s", exc)
        return 1
    LOGGER.info("OK. %d draws stored at %s", total, args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
