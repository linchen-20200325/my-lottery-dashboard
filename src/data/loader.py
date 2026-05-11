"""History data loader (v3.0).

Supports three input paths so the live app never depends on live scraping:
1. CSV file on disk (scraper output committed to repo).
2. Raw CSV string (uploaded via Streamlit file_uploader).
3. JSON list of `{"draw": [n1..n6], "term": "...", "date": "..."}` objects.

Stdlib only. Returns plain `list[list[int]]` (newest first), which is what
`src.generator.history_engine` consumes.
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

TICKET_SIZE = 6
POOL_MIN, POOL_MAX = 1, 49


class HistoryLoadError(ValueError):
    """Raised when input cannot be parsed into valid draws."""


def _validate_draw(nums: list[int]) -> list[int]:
    if len(nums) != TICKET_SIZE:
        raise HistoryLoadError(
            f"draw must have {TICKET_SIZE} numbers, got {len(nums)}: {nums}"
        )
    if len(set(nums)) != TICKET_SIZE:
        raise HistoryLoadError(f"draw has duplicates: {nums}")
    for n in nums:
        if not isinstance(n, int) or isinstance(n, bool):
            raise HistoryLoadError(f"draw value must be int: {n!r}")
        if not (POOL_MIN <= n <= POOL_MAX):
            raise HistoryLoadError(f"draw value out of range: {n}")
    return sorted(nums)


def from_csv_rows(rows: list[dict]) -> list[list[int]]:
    """Build draws list from DictReader rows (newest first preserved)."""
    out: list[list[int]] = []
    for i, row in enumerate(rows, start=1):
        try:
            nums = [int(row[f"n{k}"]) for k in range(1, TICKET_SIZE + 1)]
        except (KeyError, ValueError) as exc:
            raise HistoryLoadError(f"row {i}: missing/invalid n1-n6 ({exc})") from exc
        out.append(_validate_draw(nums))
    if not out:
        raise HistoryLoadError("no rows parsed from CSV")
    return out


def load_csv_file(path: Path | str) -> list[list[int]]:
    p = Path(path)
    if not p.exists():
        raise HistoryLoadError(f"CSV file not found: {p}")
    with p.open("r", encoding="utf-8", newline="") as fp:
        rows = list(csv.DictReader(fp))
    return from_csv_rows(rows)


def load_csv_string(text: str) -> list[list[int]]:
    rows = list(csv.DictReader(io.StringIO(text)))
    return from_csv_rows(rows)


def load_json_string(text: str) -> list[list[int]]:
    """Accepts a JSON array of objects like:
    [{"draw": [5,12,18,25,33,42], "term": "114000123", "date": "2025-12-30"}, ...]
    """
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise HistoryLoadError(f"invalid JSON: {exc}") from exc
    if not isinstance(data, list):
        raise HistoryLoadError("JSON root must be a list")
    out: list[list[int]] = []
    for i, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            raise HistoryLoadError(f"item {i} is not an object")
        nums = item.get("draw") or item.get("numbers")
        if not isinstance(nums, list):
            raise HistoryLoadError(f"item {i}: missing 'draw' array")
        try:
            ints = [int(n) for n in nums]
        except (TypeError, ValueError) as exc:
            raise HistoryLoadError(f"item {i}: non-int in draw ({exc})") from exc
        out.append(_validate_draw(ints))
    if not out:
        raise HistoryLoadError("no entries parsed from JSON")
    return out


def load_auto(text: str) -> list[list[int]]:
    """Try CSV first, JSON second. Helpful for one-field 'paste anything' UI."""
    stripped = text.lstrip()
    if stripped.startswith("[") or stripped.startswith("{"):
        return load_json_string(text)
    return load_csv_string(text)
