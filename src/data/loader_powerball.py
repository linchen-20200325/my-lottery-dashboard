"""威力彩 history loader (v6.0).

CSV/JSON 載入器；對應威力彩第一區 1-38、第二區 1-8。Stdlib only。
回傳 `(draws, specials)` 雙序列（newest first），供 powerball_engine.analyze() 消費。
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

TICKET_SIZE = 6
MAIN_POOL_MIN, MAIN_POOL_MAX = 1, 38
BONUS_POOL_MIN, BONUS_POOL_MAX = 1, 8


class PowerballLoadError(ValueError):
    """Raised when input cannot be parsed into valid 威力彩 draws."""


def _validate_draw(nums: list[int]) -> list[int]:
    if len(nums) != TICKET_SIZE:
        raise PowerballLoadError(
            f"draw must have {TICKET_SIZE} numbers, got {len(nums)}: {nums}"
        )
    if len(set(nums)) != TICKET_SIZE:
        raise PowerballLoadError(f"draw has duplicates: {nums}")
    for n in nums:
        if not isinstance(n, int) or isinstance(n, bool):
            raise PowerballLoadError(f"draw value must be int: {n!r}")
        if not (MAIN_POOL_MIN <= n <= MAIN_POOL_MAX):
            raise PowerballLoadError(f"draw value out of range [1-38]: {n}")
    return sorted(nums)


def _validate_special(s: int) -> int:
    if not isinstance(s, int) or isinstance(s, bool):
        raise PowerballLoadError(f"special must be int: {s!r}")
    if not (BONUS_POOL_MIN <= s <= BONUS_POOL_MAX):
        raise PowerballLoadError(f"special out of range [1-8]: {s}")
    return s


def from_csv_rows(rows: list[dict]) -> tuple[list[list[int]], list[int]]:
    """CSV DictReader rows → (draws, specials)（newest first preserved）。"""
    draws: list[list[int]] = []
    specials: list[int] = []
    for i, row in enumerate(rows, start=1):
        try:
            nums = [int(row[f"n{k}"]) for k in range(1, TICKET_SIZE + 1)]
            special = int(row["special"])
        except (KeyError, ValueError) as exc:
            raise PowerballLoadError(
                f"row {i}: missing/invalid n1-n6 or special ({exc})"
            ) from exc
        draws.append(_validate_draw(nums))
        specials.append(_validate_special(special))
    if not draws:
        raise PowerballLoadError("no rows parsed from CSV")
    return draws, specials


def load_csv_file(path: Path | str) -> tuple[list[list[int]], list[int]]:
    p = Path(path)
    if not p.exists():
        raise PowerballLoadError(f"CSV file not found: {p}")
    with p.open("r", encoding="utf-8", newline="") as fp:
        rows = list(csv.DictReader(fp))
    return from_csv_rows(rows)


def load_csv_string(text: str) -> tuple[list[list[int]], list[int]]:
    rows = list(csv.DictReader(io.StringIO(text)))
    return from_csv_rows(rows)


def load_json_string(text: str) -> tuple[list[list[int]], list[int]]:
    """JSON 格式：`[{"draw": [..6..], "special": int, "term": "...", "date": "..."}, ...]`"""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise PowerballLoadError(f"invalid JSON: {exc}") from exc
    if not isinstance(data, list):
        raise PowerballLoadError("JSON root must be a list")
    draws: list[list[int]] = []
    specials: list[int] = []
    for i, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            raise PowerballLoadError(f"item {i} is not an object")
        nums_raw = item.get("draw") or item.get("numbers")
        if not isinstance(nums_raw, list):
            raise PowerballLoadError(f"item {i}: missing 'draw' array")
        special_raw = item.get("special") or item.get("bonus")
        if special_raw is None:
            raise PowerballLoadError(f"item {i}: missing 'special'")
        try:
            nums = [int(n) for n in nums_raw]
            special = int(special_raw)
        except (TypeError, ValueError) as exc:
            raise PowerballLoadError(f"item {i}: non-int value ({exc})") from exc
        draws.append(_validate_draw(nums))
        specials.append(_validate_special(special))
    if not draws:
        raise PowerballLoadError("no entries parsed from JSON")
    return draws, specials


def load_auto(text: str) -> tuple[list[list[int]], list[int]]:
    """CSV first, JSON second（pasted-anything UI fallback）。"""
    stripped = text.lstrip()
    if stripped.startswith("[") or stripped.startswith("{"):
        return load_json_string(text)
    return load_csv_string(text)


# --- UI-only helpers (lenient, never raise; for preview pane) -----------------


def preview_recent(source: Path | str | bytes, limit: int = 5) -> list[dict]:
    """近 N 期顯示用；任何解析失敗回空陣列、不爆掉預覽面板。"""
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
            "special": str(item.get("special") or item.get("bonus") or "—"),
        })
    return out
