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


# --- UI-only helpers (lenient, never raise; for preview pane) -----------------


def preview_recent(source: Path | str | bytes, limit: int = 5) -> list[dict]:
    """Extract latest N rows with display metadata (term/date/nums/special).

    UI helper: returns [] silently on any parse failure so a malformed file
    doesn't crash the preview pane. The strict `load_csv_*` / `load_json_string`
    functions remain the source of truth for the generator engine.

    `source` may be a Path, a path-like string, raw CSV/JSON text, or bytes
    (e.g. from Streamlit's file_uploader).
    """
    if limit <= 0:
        return []
    try:
        text = _read_text(source)
    except (OSError, UnicodeDecodeError):
        return []
    stripped = text.lstrip()
    if not stripped:
        return []
    try:
        if stripped.startswith("[") or stripped.startswith("{"):
            return _preview_json(text, limit)
        return _preview_csv(text, limit)
    except (csv.Error, json.JSONDecodeError, ValueError):
        return []


def _read_text(source: Path | str | bytes) -> str:
    if isinstance(source, bytes):
        return source.decode("utf-8", errors="replace")
    if isinstance(source, Path):
        return source.read_text(encoding="utf-8")
    if isinstance(source, str):
        # Distinguish file path vs raw content: a path can't contain newlines.
        if "\n" not in source and "\r" not in source:
            p = Path(source)
            if p.exists() and p.is_file():
                return p.read_text(encoding="utf-8")
        return source
    raise TypeError(f"unsupported source type: {type(source).__name__}")


def _preview_csv(text: str, limit: int) -> list[dict]:
    rows = list(csv.DictReader(io.StringIO(text)))
    out: list[dict] = []
    for row in rows[:limit]:
        try:
            nums = [int(row[f"n{k}"]) for k in range(1, TICKET_SIZE + 1)]
        except (KeyError, ValueError):
            continue
        out.append({
            "term": str(row.get("draw_term") or row.get("term") or "—"),
            "date": str(row.get("draw_date") or row.get("date") or "—"),
            "nums": nums,
            "special": str(row.get("special") or "—"),
        })
    return out


def _preview_json(text: str, limit: int) -> list[dict]:
    data = json.loads(text)
    if not isinstance(data, list):
        return []
    out: list[dict] = []
    for item in data[:limit]:
        if not isinstance(item, dict):
            continue
        nums_raw = item.get("draw") or item.get("numbers")
        if not isinstance(nums_raw, list) or len(nums_raw) < TICKET_SIZE:
            continue
        try:
            nums = [int(n) for n in nums_raw[:TICKET_SIZE]]
        except (TypeError, ValueError):
            continue
        out.append({
            "term": str(item.get("term") or "—"),
            "date": str(item.get("date") or "—"),
            "nums": nums,
            "special": str(item.get("special") or "—"),
        })
    return out
