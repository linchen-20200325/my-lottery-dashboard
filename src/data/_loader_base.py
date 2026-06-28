"""History loader 共用底座 — 兩 loader(大樂透/威力彩)的 SSOT。

REFACTOR_AUDIT §5.2 / §6 B3。兩 loader 原本 75-80% copy-paste(逐列 schema 驗證、
CSV/JSON 載入、provenance 變體、preview helper)。本模組把共用邏輯收斂為一,由
`LoaderConfig`(純 primitives + error class + 是否強制特別號)參數化。

領域差異(各 loader 提供):
  - 號池 / 特別號值域 / ticket_size → 由各 loader **從 `DomainConfig` 取**(SSOT),
    塞進 `LoaderConfig`;base 不直接依賴 generator 層,保持泛用。
  - error class(`HistoryLoadError` / `PowerballLoadError`)。
  - `special_required`:威力彩 True(必有第二區);大樂透 False —— **DR-1 修正**:
    大樂透特別號改為「有就驗 [1,49]、無則略過」,既補上原本完全不驗的漏洞,又不
    破壞無 special 欄的上傳/JSON(`special` 非分析必需,僅顯示用)。

回傳統一 `(draws, specials)`;各 loader 薄 wrapper 自行決定要不要把 specials 透出
(大樂透丟棄、回 `list[list[int]]`;威力彩保留、回 tuple)。

Stdlib only。
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from pathlib import Path

from src.data.provenance import (
    HistoryProvenance,
    build_provenance_from_rows,
)


@dataclass(frozen=True)
class LoaderConfig:
    ticket_size: int
    pool_min: int
    pool_max: int
    special_min: int
    special_max: int
    special_required: bool
    error_cls: type[Exception]


def validate_draw(nums: list[int], cfg: LoaderConfig) -> list[int]:
    if len(nums) != cfg.ticket_size:
        raise cfg.error_cls(
            f"draw must have {cfg.ticket_size} numbers, got {len(nums)}: {nums}"
        )
    if len(set(nums)) != cfg.ticket_size:
        raise cfg.error_cls(f"draw has duplicates: {nums}")
    for n in nums:
        if not isinstance(n, int) or isinstance(n, bool):
            raise cfg.error_cls(f"draw value must be int: {n!r}")
        if not (cfg.pool_min <= n <= cfg.pool_max):
            raise cfg.error_cls(
                f"draw value out of range [{cfg.pool_min}-{cfg.pool_max}]: {n}"
            )
    return sorted(nums)


def validate_special(s: int, cfg: LoaderConfig) -> int:
    if not isinstance(s, int) or isinstance(s, bool):
        raise cfg.error_cls(f"special must be int: {s!r}")
    if not (cfg.special_min <= s <= cfg.special_max):
        raise cfg.error_cls(
            f"special out of range [{cfg.special_min}-{cfg.special_max}]: {s}"
        )
    return s


def _extract_special(raw, idx: int, cfg: LoaderConfig, label: str) -> int | None:
    """Validate special if present;若缺且非強制則回 None(DR-1:大樂透有才驗)。"""
    if raw is None or (isinstance(raw, str) and raw.strip() == ""):
        if cfg.special_required:
            raise cfg.error_cls(f"{label} {idx}: missing special")
        return None
    try:
        s = int(raw)
    except (TypeError, ValueError) as exc:
        raise cfg.error_cls(f"{label} {idx}: invalid special ({exc})") from exc
    return validate_special(s, cfg)


def from_csv_rows(
    rows: list[dict], cfg: LoaderConfig,
) -> tuple[list[list[int]], list[int | None]]:
    """CSV DictReader rows → (draws, specials)(newest first preserved)。"""
    draws: list[list[int]] = []
    specials: list[int | None] = []
    for i, row in enumerate(rows, start=1):
        try:
            nums = [int(row[f"n{k}"]) for k in range(1, cfg.ticket_size + 1)]
        except (KeyError, ValueError) as exc:
            raise cfg.error_cls(f"row {i}: missing/invalid n1-n6 ({exc})") from exc
        draws.append(validate_draw(nums, cfg))
        specials.append(_extract_special(row.get("special"), i, cfg, "row"))
    if not draws:
        raise cfg.error_cls("no rows parsed from CSV")
    return draws, specials


def load_csv_file(
    path: Path | str, cfg: LoaderConfig,
) -> tuple[list[list[int]], list[int | None]]:
    p = Path(path)
    if not p.exists():
        raise cfg.error_cls(f"CSV file not found: {p}")
    with p.open("r", encoding="utf-8", newline="") as fp:
        rows = list(csv.DictReader(fp))
    return from_csv_rows(rows, cfg)


def load_csv_string(
    text: str, cfg: LoaderConfig,
) -> tuple[list[list[int]], list[int | None]]:
    rows = list(csv.DictReader(io.StringIO(text)))
    return from_csv_rows(rows, cfg)


def load_csv_file_with_provenance(
    path: Path | str, cfg: LoaderConfig,
) -> tuple[list[list[int]], list[int | None], HistoryProvenance]:
    p = Path(path)
    if not p.exists():
        raise cfg.error_cls(f"CSV file not found: {p}")
    with p.open("r", encoding="utf-8", newline="") as fp:
        rows = list(csv.DictReader(fp))
    draws, specials = from_csv_rows(rows, cfg)
    prov = build_provenance_from_rows(rows, source=str(p), n_parsed=len(draws))
    return draws, specials, prov


def load_csv_string_with_provenance(
    text: str, cfg: LoaderConfig, source: str = "<paste>",
) -> tuple[list[list[int]], list[int | None], HistoryProvenance]:
    rows = list(csv.DictReader(io.StringIO(text)))
    draws, specials = from_csv_rows(rows, cfg)
    prov = build_provenance_from_rows(rows, source=source, n_parsed=len(draws))
    return draws, specials, prov


def load_json_string(
    text: str, cfg: LoaderConfig,
) -> tuple[list[list[int]], list[int | None]]:
    """JSON array of `{"draw": [..], "special"/"bonus": int, "term", "date"}`."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise cfg.error_cls(f"invalid JSON: {exc}") from exc
    if not isinstance(data, list):
        raise cfg.error_cls("JSON root must be a list")
    draws: list[list[int]] = []
    specials: list[int | None] = []
    for i, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            raise cfg.error_cls(f"item {i} is not an object")
        nums_raw = item.get("draw") or item.get("numbers")
        if not isinstance(nums_raw, list):
            raise cfg.error_cls(f"item {i}: missing 'draw' array")
        try:
            ints = [int(n) for n in nums_raw]
        except (TypeError, ValueError) as exc:
            raise cfg.error_cls(f"item {i}: non-int in draw ({exc})") from exc
        draws.append(validate_draw(ints, cfg))
        special_raw = item.get("special")
        if special_raw is None:
            special_raw = item.get("bonus")
        specials.append(_extract_special(special_raw, i, cfg, "item"))
    if not draws:
        raise cfg.error_cls("no entries parsed from JSON")
    return draws, specials


def load_auto(
    text: str, cfg: LoaderConfig,
) -> tuple[list[list[int]], list[int | None]]:
    """CSV first, JSON second（pasted-anything UI fallback）。"""
    stripped = text.lstrip()
    if stripped.startswith("[") or stripped.startswith("{"):
        return load_json_string(text, cfg)
    return load_csv_string(text, cfg)


# --- UI-only helpers (lenient, never raise; for preview pane) -----------------


def preview_recent(
    source: Path | str | bytes, cfg: LoaderConfig, limit: int = 5,
) -> list[dict]:
    """近 N 期顯示用(term/date/nums/special);任何解析失敗回空陣列、不爆預覽面板。"""
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
            return _preview_json(text, cfg.ticket_size, limit)
        return _preview_csv(text, cfg.ticket_size, limit)
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


def _preview_csv(text: str, ticket_size: int, limit: int) -> list[dict]:
    rows = list(csv.DictReader(io.StringIO(text)))
    out: list[dict] = []
    for row in rows[:limit]:
        try:
            nums = [int(row[f"n{k}"]) for k in range(1, ticket_size + 1)]
        except (KeyError, ValueError):
            continue
        out.append({
            "term": str(row.get("draw_term") or row.get("term") or "—"),
            "date": str(row.get("draw_date") or row.get("date") or "—"),
            "nums": nums,
            "special": str(row.get("special") or "—"),
        })
    return out


def _preview_json(text: str, ticket_size: int, limit: int) -> list[dict]:
    data = json.loads(text)
    if not isinstance(data, list):
        return []
    out: list[dict] = []
    for item in data[:limit]:
        if not isinstance(item, dict):
            continue
        nums_raw = item.get("draw") or item.get("numbers")
        if not isinstance(nums_raw, list) or len(nums_raw) < ticket_size:
            continue
        try:
            nums = [int(n) for n in nums_raw[:ticket_size]]
        except (TypeError, ValueError):
            continue
        out.append({
            "term": str(item.get("term") or "—"),
            "date": str(item.get("date") or "—"),
            "nums": nums,
            # DR-6:統一讀 special 後備 bonus(原本大樂透只讀 special、威力彩讀 both)
            "special": str(item.get("special") or item.get("bonus") or "—"),
        })
    return out
