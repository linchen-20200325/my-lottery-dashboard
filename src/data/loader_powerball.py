"""威力彩 history loader (6/38 + 1/8).

CSV/JSON 載入器;對應威力彩第一區 1-38、第二區 1-8。回傳 `(draws, specials)`
雙序列(newest first),供 `powerball_engine.analyze()` 消費。

v6.22(B3):逐列驗證 / 載入 / provenance / preview 收斂至 `src.data._loader_base`;
本檔只保留威力彩 config(號池/特別號值域源自 `DomainConfig.POWERBALL` → SSOT)與
薄 wrapper。`special_required=True`(第二區為威力彩分析必需)。

Stdlib only。
"""

from __future__ import annotations

from pathlib import Path

from src.data import _loader_base as base
from src.data._loader_base import LoaderConfig
from src.data.provenance import HistoryProvenance
from src.generator.domain import POWERBALL as _DOM

TICKET_SIZE = _DOM.ticket_size
MAIN_POOL_MIN, MAIN_POOL_MAX = _DOM.pool_min, _DOM.pool_max
BONUS_POOL_MIN, BONUS_POOL_MAX = _DOM.special_min, _DOM.special_max


class PowerballLoadError(ValueError):
    """Raised when input cannot be parsed into valid 威力彩 draws."""


# 威力彩 LoaderConfig — 主號池/第二區值域源自 DomainConfig(SSOT)。
# special_required=True:第二區為分析必需,缺則 raise。
_CFG = LoaderConfig(
    ticket_size=_DOM.ticket_size,
    pool_min=_DOM.pool_min,
    pool_max=_DOM.pool_max,
    special_min=_DOM.special_min,
    special_max=_DOM.special_max,
    special_required=True,
    error_cls=PowerballLoadError,
)


def from_csv_rows(rows: list[dict]) -> tuple[list[list[int]], list[int]]:
    """CSV DictReader rows → (draws, specials)（newest first preserved）。"""
    draws, specials = base.from_csv_rows(rows, _CFG)
    return draws, specials


def load_csv_file(path: Path | str) -> tuple[list[list[int]], list[int]]:
    draws, specials = base.load_csv_file(path, _CFG)
    return draws, specials


def load_csv_string(text: str) -> tuple[list[list[int]], list[int]]:
    draws, specials = base.load_csv_string(text, _CFG)
    return draws, specials


# --- §2.2 Provenance-annotated variants (additive; existing API unchanged) ---


def load_csv_file_with_provenance(
    path: Path | str,
) -> tuple[list[list[int]], list[int], HistoryProvenance]:
    """Like `load_csv_file` 但同時回傳 §2.2 血緣 metadata(三元組)。"""
    draws, specials, prov = base.load_csv_file_with_provenance(path, _CFG)
    return draws, specials, prov


def load_csv_string_with_provenance(
    text: str, source: str = "<paste>",
) -> tuple[list[list[int]], list[int], HistoryProvenance]:
    draws, specials, prov = base.load_csv_string_with_provenance(text, _CFG, source)
    return draws, specials, prov


def load_json_string(text: str) -> tuple[list[list[int]], list[int]]:
    """JSON：`[{"draw": [..6..], "special"/"bonus": int, "term", "date"}, ...]`"""
    draws, specials = base.load_json_string(text, _CFG)
    return draws, specials


def load_auto(text: str) -> tuple[list[list[int]], list[int]]:
    """CSV first, JSON second（pasted-anything UI fallback）。"""
    draws, specials = base.load_auto(text, _CFG)
    return draws, specials


# --- UI-only helpers (lenient, never raise; for preview pane) -----------------


def preview_recent(source: Path | str | bytes, limit: int = 5) -> list[dict]:
    """近 N 期顯示用；任何解析失敗回空陣列、不爆掉預覽面板。"""
    return base.preview_recent(source, _CFG, limit)
